#!/usr/bin/env python3
"""
Test-only plain-HTTP harness wrapping ControlPlaneApplication.
NOT for production — transport only (plain HTTP, no auth middleware, no TLS).
The application logic, services, and SQLite persistence are REAL.

AC10 E2E extensions (AG3-094):
  POST /_test/seed-kpi-facts  -- write real KPI fact rows into the FactStore
  POST /_test/emit-sse-event  -- append a real execution event (triggers SSE stream)

These endpoints are test-only surface — they write directly to the same SQLite
store that the real KPI and SSE endpoints read from. No mocking.

Usage:
  python python_harness.py [port]
  # Prints the actual bound port to stdout, then serves until killed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.control_plane_http.app import ControlPlaneApplication

# Point to the real agentkit package.
# Harness lives at: <repo>/frontend/prototype/tests/python_harness.py
# So 4 levels up is the repo root T:/codebase/claude-agentkit3.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # T:/codebase/claude-agentkit3
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Set AGENTKIT_STORE_DIR to a tmp dir for each test run.
# Force SQLite backend regardless of any environment configuration —
# the E2E test must use a real but isolated local store, never production Postgres.
_tmp_dir = tempfile.mkdtemp(prefix="ak3_e2e_")
# AG3-094 (E9, FIX THE MODEL): AGENTKIT_STORE_DIR is the single explicit root for
# BOTH the per-project FactStore (StateBackendFactRepository(store_dir=...)) and
# the SQLite global execution-event store (sqlite_store._global_store_dir reads
# this env, fail-closed). No os.chdir crutch is needed any more — the global store
# no longer keys off the process working directory.
os.environ["AGENTKIT_STORE_DIR"] = _tmp_dir
os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
# AGENTKIT_ALLOW_SQLITE is required by the SQLite backend guard for non-unit-test paths.
# The harness is test-only and uses a real but isolated ephemeral SQLite store.
os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"


def build_app() -> ControlPlaneApplication:
    from agentkit.control_plane_http.app import (
        ControlPlaneApplication,
        ControlPlaneApplicationRoutes,
    )

    # Use NO auth middleware so the test can call endpoints directly
    return ControlPlaneApplication(routes=ControlPlaneApplicationRoutes())


def _coerce_datetimes(raw: dict[str, Any], field_names: tuple[str, ...]) -> None:
    """Normalise ISO strings → aware datetimes in-place for the given fields."""
    from datetime import UTC, datetime

    for field_name in field_names:
        val = raw.get(field_name)
        if isinstance(val, str) and val:
            raw[field_name] = datetime.fromisoformat(val.replace("Z", "+00:00"))
        elif field_name in ("started_at", "period_start") and not val:
            raw[field_name] = datetime.now(UTC)


def _seed_kpi_facts(body: bytes) -> tuple[int, bytes]:
    """POST /_test/seed-kpi-facts — persist real fact rows via the real FactStore.

    Accepts a JSON payload with one or more dimension arrays. AG3-094 (E7): the
    E2E seeds EVERY KPI dimension the Analytics view consumes (stories + guards +
    pools + pipeline + corpus), so every ``/kpi/*`` read the view makes is
    non-empty against the real persistence:

      {
        "project_key": "...",
        "facts":    [ <FactStory wire dict>, ... ],          # stories dimension
        "guards":   [ <FactGuardPeriod wire dict>, ... ],
        "pools":    [ <FactPoolPeriod wire dict>, ... ],
        "pipeline": [ <FactPipelinePeriod wire dict>, ... ],
        "corpus":   [ <FactCorpusPeriod wire dict>, ... ]
      }

    Uses the same StateBackendFactRepository that the real /kpi/* endpoints read
    from — so the seed is immediately visible to those endpoints. No mocking.
    """
    from agentkit.kpi_analytics.fact_store.models import (
        FactCorpusPeriod,
        FactGuardPeriod,
        FactPipelinePeriod,
        FactPoolPeriod,
        FactStory,
    )
    from agentkit.state_backend.store.fact_repository import StateBackendFactRepository

    try:
        payload = json.loads(body)
        project_key: str = payload["project_key"]
    except (json.JSONDecodeError, KeyError) as exc:
        return 400, json.dumps({"error": f"Invalid payload: {exc}"}).encode()

    # Use the same store_dir as the harness (_tmp_dir) so the seed goes to the
    # same SQLite database that the real KPI endpoints read from. The global
    # event store resolves from the SAME AGENTKIT_STORE_DIR (E9), so seed + SSE
    # stream + reads all share one configured store.
    repo = StateBackendFactRepository(store_dir=Path(_tmp_dir))
    seeded = 0

    period_fields = ("period_start", "period_end")
    try:
        for raw in payload.get("facts", []):
            _coerce_datetimes(raw, ("started_at", "completed_at"))
            raw.setdefault("project_key", project_key)
            raw.setdefault("agentkit_version", "3.0.0-test")
            raw.setdefault("agentkit_commit", "test-commit")
            repo.upsert_fact_story(FactStory(**raw))
            seeded += 1
        for raw in payload.get("guards", []):
            _coerce_datetimes(raw, period_fields)
            raw.setdefault("project_key", project_key)
            repo.upsert_fact_guard(FactGuardPeriod(**raw))
            seeded += 1
        for raw in payload.get("pools", []):
            _coerce_datetimes(raw, period_fields)
            raw.setdefault("project_key", project_key)
            repo.upsert_fact_pool(FactPoolPeriod(**raw))
            seeded += 1
        for raw in payload.get("pipeline", []):
            _coerce_datetimes(raw, period_fields)
            raw.setdefault("project_key", project_key)
            repo.upsert_fact_pipeline(FactPipelinePeriod(**raw))
            seeded += 1
        for raw in payload.get("corpus", []):
            _coerce_datetimes(raw, period_fields)
            raw.setdefault("project_key", project_key)
            repo.upsert_fact_corpus(FactCorpusPeriod(**raw))
            seeded += 1
    except Exception as exc:  # noqa: BLE001
        return 400, json.dumps({"error": f"Invalid fact row: {exc}"}).encode()

    return 200, json.dumps({"seeded": seeded}).encode()


def _emit_sse_event(body: bytes) -> tuple[int, bytes]:
    """POST /_test/emit-sse-event — append a real execution event that the SSE stream emits.

    Accepts a JSON payload:
      { "project_key": "...", "event_type": "...", "payload": { ... } }

    The event is written via append_execution_event_global — the SAME path the
    SSE stream reads from (iter_project_sse_stream → source.events_for_project
    → load_execution_events_for_project_global). Topic routing uses _topic_for_record
    in sse_stream.py: a payload with {"topic": "kpi"} emits a kpi-topic event.
    """
    import uuid
    from datetime import UTC, datetime

    from agentkit.state_backend.store.facade import append_execution_event_global
    from agentkit.telemetry.contract.records import ExecutionEventRecord

    try:
        payload = json.loads(body)
        project_key: str = payload["project_key"]
        event_type: str = payload.get("event_type", "telemetry_event")
        event_payload: dict[str, Any] = payload.get("payload", {})
    except (json.JSONDecodeError, KeyError) as exc:
        return 400, json.dumps({"error": f"Invalid payload: {exc}"}).encode()

    record = ExecutionEventRecord(
        project_key=project_key,
        story_id=payload.get("story_id", "_test"),
        run_id=payload.get("run_id", str(uuid.uuid4())),
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        source_component="test-harness",
        severity="info",
        payload=event_payload,
    )
    try:
        append_execution_event_global(record)
    except Exception as exc:  # noqa: BLE001
        return 500, json.dumps({"error": f"Failed to append event: {exc}"}).encode()

    return 200, json.dumps({"event_id": record.event_id}).encode()


def _seed_task(body: bytes) -> tuple[int, bytes]:
    """POST /_test/seed-task -- create a real Task via TaskManagement.create_task.

    Accepts a JSON payload matching the Task wire shape (Task.model_dump(mode="json")):
      {
        "project_key": "...",
        "task_id": "TM-2025-0001",   # required for test seeding (bypasses HTTP allocation)
        "kind": "actionable",
        "priority": "normal",
        "title": "...",
        "body": "...",               # wire field is `body` (NOT description)
        "source_story_id": "..."     # wire field is `source_story_id` (NOT story_id), optional
      }

    Uses the same ProjectionRepositories that the real task endpoints read from --
    so the seeded task is immediately visible to GET /v1/projects/{key}/tasks.
    No mocking.
    """
    from agentkit.state_backend.store.projection_repositories import build_projection_repositories
    from agentkit.task_management.models import Task
    from agentkit.task_management.service import TaskManagement
    from agentkit.telemetry.projection_accessor import ProjectionAccessor

    from datetime import UTC, datetime

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return 400, json.dumps({"error": f"Invalid JSON: {exc}"}).encode()

    # Supply defaults for fields that the lightweight seed payload omits.
    payload.setdefault("type", "general")
    payload.setdefault("body", payload.get("title", "seeded task"))
    payload.setdefault("status", "open")
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(UTC)

    try:
        task = Task(**payload)
    except Exception as exc:  # noqa: BLE001
        return 400, json.dumps({"error": f"Invalid task payload: {exc}"}).encode()

    try:
        repos = build_projection_repositories(Path(_tmp_dir))
        accessor = ProjectionAccessor(repos)
        svc = TaskManagement(accessor)
        svc.create_task(task)
    except Exception as exc:  # noqa: BLE001
        return 500, json.dumps({"error": f"Failed to seed task: {exc}"}).encode()

    return 200, json.dumps({"task_id": task.task_id}).encode()


def _seed_story(body: bytes) -> tuple[int, bytes]:
    """POST /_test/seed-story -- persist a real Story row via the real repository.

    Writes a canonical Story row into the SAME SQLite store the task-link
    validator reads from (``story_target_exists``), so a UI-driven
    ``link_task`` with ``target_kind=story`` can target it. Test-only seeding of
    REAL data (mirrors ``/_test/seed-task``) — no backend/DB stub.

    Payload (minimal):
      { "project_key": "...", "story_display_id": "P-0001", "title": "..." }
    """
    from agentkit.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )
    from agentkit.story_context_manager.story_model import Story

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return 400, json.dumps({"error": f"Invalid JSON: {exc}"}).encode()

    payload.setdefault("story_number", 1)
    payload.setdefault("title", "Seeded story")
    payload.setdefault("story_type", "implementation")

    try:
        story = Story(**payload)
    except Exception as exc:  # noqa: BLE001
        return 400, json.dumps({"error": f"Invalid story payload: {exc}"}).encode()

    try:
        StateBackendStoryRepository(Path(_tmp_dir)).save(story)
    except Exception as exc:  # noqa: BLE001
        return 500, json.dumps({"error": f"Failed to seed story: {exc}"}).encode()

    return 200, json.dumps({"story_display_id": story.story_display_id}).encode()


def make_handler(app: ControlPlaneApplication) -> type[BaseHTTPRequestHandler]:
    _app = app

    # Test-only endpoints (AG3-094 AC10 E2E seeding).
    _test_endpoints: dict[str, Callable[[bytes], tuple[int, bytes]]] = {
        "/_test/seed-kpi-facts": _seed_kpi_facts,
        "/_test/emit-sse-event": _emit_sse_event,
        "/_test/seed-task": _seed_task,
        "/_test/seed-story": _seed_story,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length) if content_length > 0 else b""

                # Route test-only seed/emit endpoints (POST only).
                path_only = self.path.split("?")[0]
                if self.command == "POST" and path_only in _test_endpoints:
                    handler_fn = _test_endpoints[path_only]
                    status_code, resp_body = handler_fn(body)
                    self.send_response(status_code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return

                response = _app.handle_request(
                    method=self.command,
                    path=self.path,
                    body=body,
                    request_headers=dict(self.headers.items()),
                )
                self.send_response(response.status_code)
                for key, value in response.headers:
                    self.send_header(key, value)
                if "content-type" not in {k.lower() for k, _ in response.headers}:
                    self.send_header("Content-Type", "application/json")
                # Always close the connection so Node.js fetch does not hang waiting
                # for keep-alive reuse on a single-threaded server.
                self.send_header("Connection", "close")
                if response.stream is None:
                    self.send_header("Content-Length", str(len(response.body)))
                    self.end_headers()
                    self.wfile.write(response.body)
                else:
                    self.end_headers()
                    for chunk in response.stream:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except Exception as exc:  # noqa: BLE001
                # Guarantee a response so the client never sees a bare socket close.
                error_body = json.dumps({"error": f"Internal server error: {exc}"}).encode()
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(error_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(error_body)
                except Exception:  # noqa: BLE001
                    pass  # socket already gone — nothing to do

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
            pass  # suppress request logs during tests

    return Handler


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app = build_app()
    handler = make_handler(app)
    # ThreadingHTTPServer: each request is handled in its own thread so that
    # HTTP/1.1 keep-alive connections from Node.js fetch do not deadlock against
    # a single-threaded server that is blocked waiting for the next request.
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    # Print port to stdout so the test can read it
    print(actual_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
