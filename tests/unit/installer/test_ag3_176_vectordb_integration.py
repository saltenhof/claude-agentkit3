"""Boundary tests for the AG3-176 mandatory VectorDB installer integration."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from tests.unit.vectordb.corpus_doubles import (
    RealQueryBoundaryWeaviateClient,
    RecordingWeaviateClient,
)

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.exceptions import ConfigError, InstallationError, ProjectError
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    run_checkpoint_install,
)
from agentkit.backend.installer.cp10a_initial_sync import (
    InitialSyncReceipt,
    run_initial_sync,
    verify_initial_sync,
)
from agentkit.backend.installer.runner import InstallConfig
from agentkit.backend.installer.upgrade.hook_migration import (
    migrate_git_hook_dispatch,
    verify_git_hook_dispatch,
)
from agentkit.backend.installer.vectordb_preflight import (
    HttpVectorDbPreflight,
    _wait_for_explicit_endpoints,
)
from agentkit.backend.vectordb.commit_recovery import (
    project_commit_recovery_journal,
)
from agentkit.backend.vectordb.corpus_store import WeaviateCorpusStore
from agentkit.backend.vectordb.engine import compose_runtime
from agentkit.backend.vectordb.hook_dispatch import _changed_paths
from agentkit.backend.vectordb.mcp_server import McpToolService
from agentkit.backend.vectordb.sync import (
    ProducerCompletion,
    SyncReceipt,
    completion_run_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.installer.vectordb_preflight import VectorDbPreflightReceipt


class RejectingPreflight:
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    def check(self, config: ProjectConfig) -> VectorDbPreflightReceipt:
        del config
        self.calls += 1
        raise ProjectError("preflight rejected", detail={"reason": self.reason})


class MutatingSuccessfulPreflight:
    """Benign probe seam that changes config between both strict reads."""

    def __init__(self, config_path: Path, replacement: str) -> None:
        self._config_path = config_path
        self._replacement = replacement

    def check(self, config: ProjectConfig) -> VectorDbPreflightReceipt:
        from agentkit.backend.installer.vectordb_preflight import (
            VectorDbPreflightReceipt,
        )

        vectordb = config.pipeline.vectordb
        assert vectordb is not None
        assert vectordb.weaviate_http_endpoint is not None
        assert vectordb.weaviate_grpc_endpoint is not None
        self._config_path.write_text(self._replacement, encoding="utf-8")
        return VectorDbPreflightReceipt(
            http_endpoint=vectordb.weaviate_http_endpoint,
            grpc_endpoint=vectordb.weaviate_grpc_endpoint,
            server_version="1.25.9",
        )


class _WeaviateHandler(BaseHTTPRequestHandler):
    """Tiny real HTTP boundary for readiness/identity/version tests."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        mode = str(self.server.mode)  # type: ignore[attr-defined]
        if self.path.endswith("/ready"):
            if mode == "not_ready":
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"true")
            return
        self.send_response(200)
        self.end_headers()
        if mode == "not_weaviate":
            self.wfile.write(b"<html>another service</html>")
        else:
            version = "1.24.9" if mode == "incompatible" else "1.25.9"
            self.wfile.write(json.dumps({"version": version}).encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _TcpBoundary(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _preflight_config(http_port: int, grpc_port: int) -> ProjectConfig:
    raw = _project_config().model_dump(mode="json", exclude_none=True)
    raw["pipeline"]["vectordb"] = {  # type: ignore[index]
        "weaviate_http_endpoint": f"http://127.0.0.1:{http_port}",
        "weaviate_grpc_endpoint": f"127.0.0.1:{grpc_port}",
    }
    return ProjectConfig.model_validate(raw)


def _boundary_readiness(
    http: ThreadingHTTPServer,
) -> Callable[[str, int, bool, str, int, bool, float], bool]:
    def _ready(
        http_host: str,
        http_port: int,
        http_secure: bool,
        grpc_host: str,
        grpc_port: int,
        grpc_secure: bool,
        timeout: float,
    ) -> bool:
        assert not http_secure
        assert not grpc_secure
        assert (http_host, http_port) == (
            str(http.server_address[0]),
            int(http.server_address[1]),
        )
        with socket.create_connection((grpc_host, grpc_port), timeout=timeout):
            pass
        return str(http.mode) != "not_ready"  # type: ignore[attr-defined]

    return _ready


@pytest.fixture
def weaviate_boundaries() -> tuple[ThreadingHTTPServer, _TcpBoundary]:
    http = ThreadingHTTPServer(("127.0.0.1", 0), _WeaviateHandler)
    grpc = _TcpBoundary(("127.0.0.1", 0), socketserver.BaseRequestHandler)
    http.mode = "ready"  # type: ignore[attr-defined]
    threads = [
        threading.Thread(target=http.serve_forever),
        threading.Thread(target=grpc.serve_forever),
    ]
    for thread in threads:
        thread.start()
    try:
        yield http, grpc
    finally:
        http.shutdown()
        grpc.shutdown()
        http.server_close()
        grpc.server_close()
        for thread in threads:
            thread.join(timeout=5)


def _project_config() -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project_key": "AG3",
            "project_name": "AgentKit",
            "repositories": [{"name": "main", "path": "."}],
            "story_types": ["concept"],
            "concepts_dir": "architecture",
            "wiki_stories_dir": "work-items",
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "vectordb": {
                    "weaviate_http_endpoint": "http://weaviate.invalid:8080",
                    "weaviate_grpc_endpoint": "weaviate.invalid:50051",
                },
            },
        }
    )


@pytest.mark.parametrize(
    "reason",
    ("unreachable", "not_weaviate", "not_ready", "incompatible_version"),
)
def test_preflight_failure_precedes_every_installer_effect(tmp_path: Path, reason: str) -> None:
    probe = RejectingPreflight(reason)
    config = InstallConfig(
        project_key="AG3",
        project_name="AgentKit",
        project_root=tmp_path,
        github_owner="acme",
        github_repo="agentkit",
        vectordb_http_endpoint="http://weaviate.invalid:8080",
        vectordb_grpc_endpoint="weaviate.invalid:50051",
        vectordb_preflight=probe,
    )

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(config)

    assert caught.value.detail["reason"] == reason
    assert probe.calls == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("mode", "reason"),
    (
        ("not_ready", "not_ready"),
        ("not_weaviate", "not_weaviate"),
        ("incompatible", "incompatible_version"),
    ),
)
def test_real_preflight_names_http_identity_readiness_and_version_failures(
    weaviate_boundaries: tuple[ThreadingHTTPServer, _TcpBoundary],
    mode: str,
    reason: str,
) -> None:
    http, grpc = weaviate_boundaries
    http.mode = mode  # type: ignore[attr-defined]
    config = _preflight_config(
        int(http.server_address[1]),
        int(grpc.server_address[1]),
    )

    with pytest.raises(ProjectError) as caught:
        HttpVectorDbPreflight(
            timeout_seconds=1,
            readiness=_boundary_readiness(http),
        ).check(config)

    assert caught.value.detail["reason"] == reason


def test_real_preflight_proves_http_identity_and_grpc_connectivity(
    weaviate_boundaries: tuple[ThreadingHTTPServer, _TcpBoundary],
) -> None:
    http, grpc = weaviate_boundaries
    receipt = HttpVectorDbPreflight(
        timeout_seconds=1,
        readiness=_boundary_readiness(http),
    ).check(
        _preflight_config(
            int(http.server_address[1]),
            int(grpc.server_address[1]),
        )
    )
    assert receipt.server_version == "1.25.9"


def test_productive_preflight_reuses_canonical_wait_with_exact_grpc_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.installer import vectordb_preflight

    calls: list[tuple[str, int, str | None, int]] = []

    class _ReadyAdapter:
        def is_ready(self) -> bool:
            return True

        def close(self) -> None:
            return

    def _connect(
        _cls: type[object],
        *,
        host: str,
        port: int,
        http_secure: bool = False,
        grpc_host: str | None = None,
        grpc_port: int = 50051,
        grpc_secure: bool = False,
    ) -> _ReadyAdapter:
        assert not http_secure
        assert not grpc_secure
        calls.append((host, port, grpc_host, grpc_port))
        return _ReadyAdapter()

    monkeypatch.setattr(
        vectordb_preflight.WeaviateStoryAdapter,
        "connect",
        classmethod(_connect),
    )

    assert _wait_for_explicit_endpoints(
        "weaviate.example",
        9903,
        False,
        "grpc.weaviate.example",
        55051,
        False,
        0,
    )
    assert calls == [("weaviate.example", 9903, "grpc.weaviate.example", 55051)]


def test_real_preflight_names_unreachable_without_starting_any_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = ThreadingHTTPServer(("127.0.0.1", 0), _WeaviateHandler)
    closed_port = int(http.server_address[1])
    http.server_close()
    process_calls: list[list[str]] = []

    def _forbid_process(command: list[str], **_kwargs: object) -> object:
        process_calls.append(command)
        raise AssertionError("preflight must not start container/process paths")

    monkeypatch.setattr(subprocess, "run", _forbid_process)
    config = InstallConfig(
        project_key="AG3",
        project_name="AgentKit",
        project_root=tmp_path,
        github_owner="acme",
        github_repo="agentkit",
        vectordb_http_endpoint=f"http://127.0.0.1:{closed_port}",
        vectordb_grpc_endpoint="127.0.0.1:65534",
        vectordb_preflight=HttpVectorDbPreflight(
            timeout_seconds=0.1,
            readiness=lambda *_args: False,
        ),
    )

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(config)

    assert caught.value.detail["reason"] == "unreachable"
    assert process_calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", (False, "true", 1, None))
def test_vectordb_flag_rejects_every_non_true_value_without_effect(tmp_path: Path, value: object) -> None:
    config = InstallConfig(
        project_key="AG3",
        project_name="AgentKit",
        project_root=tmp_path,
        github_owner="acme",
        github_repo="agentkit",
        features_vectordb=value,  # type: ignore[arg-type]
        vectordb_http_endpoint="http://weaviate.invalid:8080",
        vectordb_grpc_endpoint="weaviate.invalid:50051",
    )
    with pytest.raises(ProjectError, match="must be true") as caught:
        run_checkpoint_install(config)
    assert caught.value.detail["reason"] == (
        "vectordb_required" if value is False else "configuration_invalid"
    )
    assert list(tmp_path.iterdir()) == []


def _write_existing_config(tmp_path: Path, *, features_yaml: str) -> None:
    path = tmp_path / ".agentkit" / "config" / "project.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"""
project_key: AG3
project_name: AgentKit
repositories: [{{name: main, path: .}}]
story_types: [concept]
concepts_dir: architecture
wiki_stories_dir: work-items
pipeline:
  config_version: "3.0"
{features_yaml}
  vectordb:
    weaviate_http_endpoint: http://weaviate.invalid:8080
    weaviate_grpc_endpoint: weaviate.invalid:50051
""".lstrip(),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("features_yaml", "expected_reason", "preflight_calls"),
    (
        ("  features: {multi_llm: false}", "boundary_reached", 1),
        (
            "  features: {multi_llm: false, vectordb: true}",
            "boundary_reached",
            1,
        ),
        (
            "  features: {multi_llm: false, vectordb: false}",
            "vectordb_required",
            0,
        ),
        (
            '  features: {multi_llm: false, vectordb: "true"}',
            "configuration_invalid",
            0,
        ),
        (
            "  features: {multi_llm: false, vectordb: 1}",
            "configuration_invalid",
            0,
        ),
        (
            "  features: {multi_llm: false, vectordb: null}",
            "configuration_invalid",
            0,
        ),
    ),
)
def test_existing_config_flag_contract_is_strict_before_preflight_or_effects(
    tmp_path: Path,
    features_yaml: str,
    expected_reason: str,
    preflight_calls: int,
) -> None:
    _write_existing_config(tmp_path, features_yaml=features_yaml)
    probe = RejectingPreflight("boundary_reached")
    config = InstallConfig(
        project_key="ignored-for-existing",
        project_name="ignored-for-existing",
        project_root=tmp_path,
        vectordb_preflight=probe,
    )

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(config)

    assert caught.value.detail["reason"] == expected_reason
    assert probe.calls == preflight_calls
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".agentkit" / "receipts").exists()
    assert not (tmp_path / "tools" / "hooks").exists()


@pytest.mark.parametrize(
    "ambiguous_yaml",
    (
        "  features: {multi_llm: false}\n  features: {vectordb: true}",
        "  features: {multi_llm: false, vectordb: true, vectordb: false}",
    ),
)
def test_duplicate_feature_keys_are_named_configuration_errors_before_preflight(
    tmp_path: Path,
    ambiguous_yaml: str,
) -> None:
    _write_existing_config(tmp_path, features_yaml=ambiguous_yaml)
    probe = RejectingPreflight("must_not_run")

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(
            InstallConfig(
                project_key="AG3",
                project_name="AgentKit",
                project_root=tmp_path,
                vectordb_preflight=probe,
            )
        )

    assert caught.value.detail["reason"] == "configuration_invalid"
    assert "duplicate key" in str(caught.value)
    assert probe.calls == 0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("valid_change", "configuration_changed"),
        ("duplicate_key", "configuration_invalid"),
    ),
)
def test_config_is_strictly_reread_before_first_effect(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    _write_existing_config(
        tmp_path,
        features_yaml="  features: {multi_llm: false}",
    )
    path = tmp_path / ".agentkit" / "config" / "project.yaml"
    original = path.read_text(encoding="utf-8")
    if mutation == "valid_change":
        replacement = original.replace("project_name: AgentKit", "project_name: Changed")
    else:
        replacement = original.replace(
            "project_name: AgentKit",
            "project_name: AgentKit\nproject_name: Changed",
        )
    before_paths = {
        item.relative_to(tmp_path)
        for item in tmp_path.rglob("*")
    }

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(
            InstallConfig(
                project_key="AG3",
                project_name="AgentKit",
                project_root=tmp_path,
                github_owner="acme",
                github_repo="agentkit",
                vectordb_preflight=MutatingSuccessfulPreflight(
                    path,
                    replacement,
                ),
            )
        )

    assert caught.value.detail["reason"] == reason
    assert {
        item.relative_to(tmp_path)
        for item in tmp_path.rglob("*")
    } == before_paths
    assert path.read_text(encoding="utf-8") == replacement
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / "architecture").exists()
    assert not (tmp_path / "work-items").exists()
    assert not (tmp_path / ".githooks").exists()


def test_project_yaml_duplicate_endpoint_is_rejected_without_last_wins(
    tmp_path: Path,
) -> None:
    _write_existing_config(tmp_path, features_yaml="  features: {multi_llm: false}")
    path = tmp_path / ".agentkit" / "config" / "project.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    weaviate_grpc_endpoint:",
            "    weaviate_http_endpoint: http://second.invalid:8080\n    weaviate_grpc_endpoint:",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate key"):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    "invalid_fragment",
    (
        '  features: {multi_llm: false}\n  marker: "\\ud800"',
        "  features: {multi_llm: false}\n  marker: !!python/object:builtins.str {}",
        "  features: {multi_llm: false}\n  marker: " + ("[" * 70) + "0" + ("]" * 70),
    ),
)
def test_yaml_scalar_tag_and_depth_hazards_fail_closed(
    tmp_path: Path,
    invalid_fragment: str,
) -> None:
    _write_existing_config(tmp_path, features_yaml=invalid_fragment)
    probe = RejectingPreflight("must_not_run")
    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(
            InstallConfig(
                project_key="AG3",
                project_name="AgentKit",
                project_root=tmp_path,
                vectordb_preflight=probe,
            )
        )
    assert caught.value.detail["reason"] == "configuration_invalid"
    assert probe.calls == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_block",
        "missing_grpc",
        "malformed_http",
        "invalid_http_port",
        "invalid_grpc_port",
    ),
)
def test_missing_or_malformed_endpoint_config_stops_before_preflight(
    tmp_path: Path,
    mutation: str,
) -> None:
    _write_existing_config(tmp_path, features_yaml="  features: {multi_llm: false}")
    path = tmp_path / ".agentkit" / "config" / "project.yaml"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "missing_block": (
            "  vectordb:\n"
            "    weaviate_http_endpoint: http://weaviate.invalid:8080\n"
            "    weaviate_grpc_endpoint: weaviate.invalid:50051\n",
            "",
        ),
        "missing_grpc": (
            "    weaviate_grpc_endpoint: weaviate.invalid:50051\n",
            "",
        ),
        "malformed_http": (
            "http://weaviate.invalid:8080",
            "weaviate.invalid:8080",
        ),
        "invalid_http_port": (
            "http://weaviate.invalid:8080",
            "http://weaviate.invalid:70000",
        ),
        "invalid_grpc_port": (
            "weaviate.invalid:50051",
            "weaviate.invalid:70000",
        ),
    }
    old, new = replacements[mutation]
    path.write_text(text.replace(old, new), encoding="utf-8")
    probe = RejectingPreflight("must_not_run")

    with pytest.raises(ProjectError) as caught:
        run_checkpoint_install(
            InstallConfig(
                project_key="AG3",
                project_name="AgentKit",
                project_root=tmp_path,
                vectordb_preflight=probe,
            )
        )

    assert caught.value.detail["reason"] == "configuration_invalid"
    assert probe.calls == 0
    assert not (tmp_path / ".mcp.json").exists()


def test_empty_corpora_publish_typed_zero_receipts(tmp_path: Path) -> None:
    config = _project_config()
    outcome = run_initial_sync(
        tmp_path,
        config,
        client=RecordingWeaviateClient(),
    )
    assert outcome.changed
    for receipt in outcome.receipts:
        assert isinstance(receipt, InitialSyncReceipt)
        assert receipt.status == "success"
        assert receipt.empty_corpus is True
        assert (
            receipt.discovered,
            receipt.unchanged,
            receipt.upserted,
            receipt.deleted,
            receipt.failed,
        ) == (0, 0, 0, 0, 0)


def test_cp10a_indexes_populated_story_and_concept_corpora_without_manual_sync(
    tmp_path: Path,
) -> None:
    story = tmp_path / "work-items" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text(
        dedent(
            """\
            ---
            story_id: AG3-1
            title: Installer integration
            status: Done
            story_type: implementation
            ---

            # Installer integration

            Mandatory initial indexing.
            """
        ),
        encoding="utf-8",
    )
    concept = tmp_path / "architecture" / "13_vectordb.md"
    concept.parent.mkdir(parents=True)
    concept.write_text(
        dedent(
            """\
            ---
            concept_id: FK-13
            title: VectorDB
            module: vectordb
            status: active
            doc_kind: core
            authority_over:
              - scope: vectordb
            ---

            # VectorDB

            ## Installer

            The corpus is mandatory.
            """
        ),
        encoding="utf-8",
    )
    client = RecordingWeaviateClient()

    first = run_initial_sync(tmp_path, _project_config(), client=client)
    object_types = {str(props["source_type"]) for props in client.objects.values()}

    assert {"story", "concept"} <= object_types
    assert first.receipts[0].discovered == 1
    assert first.receipts[1].discovered == 1
    assert all(receipt.upserted > 0 for receipt in first.receipts)

    object_ids = set(client.objects)
    second = run_initial_sync(tmp_path, _project_config(), client=client)
    assert set(client.objects) == object_ids
    assert all(receipt.failed == 0 for receipt in second.receipts)


def _write_sync_corpora(root: Path, *, story_count: int = 1, suffix: str = "") -> None:
    for index in range(story_count):
        story = root / "work-items" / f"AG3-{index + 1}" / "story.md"
        story.parent.mkdir(parents=True, exist_ok=True)
        story.write_text(
            dedent(
                f"""\
                ---
                story_id: AG3-{index + 1}
                title: Run boundary {index + 1}
                status: Done
                story_type: implementation
                ---

                # Run boundary {index + 1}

                Content {suffix}.
                """
            ),
            encoding="utf-8",
        )
    concept = root / "architecture" / "13_vectordb.md"
    concept.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text(
        dedent(
            f"""\
            ---
            concept_id: FK-13
            title: VectorDB
            module: vectordb
            status: active
            doc_kind: core
            authority_over:
              - scope: vectordb
            ---

            # VectorDB

            ## Run boundary

            Concept content {suffix}.
            """
        ),
        encoding="utf-8",
    )


def _runtime(
    root: Path,
    config: ProjectConfig,
    client: RecordingWeaviateClient,
) -> McpToolService:
    vectordb = config.pipeline.vectordb
    assert vectordb is not None
    service = compose_runtime(
        {
            "PROJECT_ID": config.project_prefix,
            "WEAVIATE_HTTP_ENDPOINT": str(vectordb.weaviate_http_endpoint),
            "WEAVIATE_GRPC_ENDPOINT": str(vectordb.weaviate_grpc_endpoint),
        },
        concepts_dir=root / config.concepts_dir,
        stories_dir=root / config.wiki_stories_dir,
        client=client,
        cwd=str(root),
    )
    assert isinstance(service, McpToolService)
    return service


def _completion_snapshot(
    client: RecordingWeaviateClient,
) -> tuple[object, ...]:
    receipts = WeaviateCorpusStore(
        client=client,
        recovery_journal=client.recovery_journal,
    ).list_receipts(project_id="AG3")
    return tuple(
        sorted(
            receipts,
            key=lambda receipt: (
                receipt.source_type,
                receipt.source_file,
                receipt.generation,
            ),
        )
    )


def _freshness_snapshot(
    root: Path,
    config: ProjectConfig,
    client: RecordingWeaviateClient,
) -> tuple[tuple[str, str], ...]:
    sources = _runtime(root, config, client).story_list_sources({})["sources"]
    assert isinstance(sources, list)
    return tuple(
        sorted(
            (str(source["source_type"]), str(source["last_revision"]))
            for source in sources
        )
    )


def _local_receipt_bytes(root: Path) -> tuple[bytes, bytes]:
    receipt_dir = root / ".agentkit" / "receipts" / "vectordb"
    return (
        (receipt_dir / "story_sync.json").read_bytes(),
        (receipt_dir / "concept_sync.json").read_bytes(),
    )


def test_cp10a_second_source_failure_preserves_real_completion_before_image(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, story_count=2, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    before = (
        _completion_snapshot(client),
        _freshness_snapshot(tmp_path, config, client),
        _local_receipt_bytes(tmp_path),
    )
    _write_sync_corpora(tmp_path, story_count=2, suffix="after")
    client.fail_upsert_call = len(client.upsert_calls) + 2

    with pytest.raises(InstallationError, match="without publishing freshness"):
        run_initial_sync(tmp_path, config, client=client)

    assert _completion_snapshot(client) == before[0]
    assert _freshness_snapshot(tmp_path, config, client) == before[1]
    assert _local_receipt_bytes(tmp_path) == before[2]


def test_cp10a_second_producer_failure_preserves_real_completion_before_image(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    before = (
        _completion_snapshot(client),
        _freshness_snapshot(tmp_path, config, client),
        _local_receipt_bytes(tmp_path),
    )
    _write_sync_corpora(tmp_path, suffix="after")
    client.fail_upsert_call = len(client.upsert_calls) + 2

    with pytest.raises(InstallationError, match="without publishing freshness"):
        run_initial_sync(tmp_path, config, client=client)

    assert _completion_snapshot(client) == before[0]
    assert _freshness_snapshot(tmp_path, config, client) == before[1]
    assert _local_receipt_bytes(tmp_path) == before[2]


class _PreparedCounterResult:
    story_result = {
        "project_id": "AG3",
        "corpus_revision": "story-revision",
        "synced_sources": 1,
        "written": 1,
        "deleted": 0,
        "unchanged": 0,
        "failed": 0,
    }
    concept_result = {
        **story_result,
        "corpus_revision": "concept-revision",
        "synced_sources": "1",
    }

    def commit(self) -> None:
        raise AssertionError("invalid counters must stop before commit")

    def abort(self) -> None:
        return


class _CoercingCounterService:
    def prepare_initial_sync(self) -> _PreparedCounterResult:
        return _PreparedCounterResult()


def test_cp10a_rejects_string_counters_without_coercion(tmp_path: Path) -> None:
    with pytest.raises(InstallationError, match="counter is not a non-negative int"):
        run_initial_sync(
            tmp_path,
            _project_config(),
            service=_CoercingCounterService(),
        )
    assert not (tmp_path / ".agentkit" / "receipts" / "vectordb").exists()


def _valid_receipt_payload(tool: str) -> dict[str, object]:
    """One receipt exactly as the FK-13 §13.9.9 contract allows it."""
    return {
        "project_id": "demo",
        "tool": tool,
        "source_types": ["story", "research"] if tool == "story_sync" else ["concept"],
        "discovered": 1,
        "unchanged": 0,
        "upserted": 1,
        "deleted": 0,
        "failed": 0,
        "empty_corpus": False,
        "start_revision": "",
        "end_revision": "rev-1",
        "status": "success",
    }


def test_valid_receipt_payload_is_actually_accepted() -> None:
    """Guards every negative case below: the baseline must fail for no reason."""
    for tool in ("story_sync", "concept_sync"):
        assert InitialSyncReceipt.model_validate_json(json.dumps(_valid_receipt_payload(tool))).tool == tool


@pytest.mark.parametrize(
    ("field", "value", "locus"),
    [
        ("project_id", "", "project_id"),
        ("end_revision", "", "end_revision"),
        ("discovered", -1, "discovered"),
        ("deleted", -5, "deleted"),
        ("failed", 1, "failed"),
        ("source_types", ["concept"], "source_types"),
        ("empty_corpus", True, "empty_corpus"),
    ],
)
def test_receipt_contract_rejects_out_of_range_evidence(field: str, value: object, locus: str) -> None:
    """FK-13 §13.9.9 constraints, each proven by the error it actually raises."""
    payload = _valid_receipt_payload("story_sync")
    payload[field] = value
    with pytest.raises(ValidationError) as raised:
        InitialSyncReceipt.model_validate_json(json.dumps(payload))
    # Assert the reported locus, so a removed constraint cannot stay green
    # because some *other* field happened to fail.
    assert locus in str(raised.value)


def test_receipt_contract_accepts_an_emptied_corpus_that_deleted_its_old_chunks() -> None:
    """FK-13 §13.9.9: empty_corpus=true with deleted>0 is the nonempty -> empty case."""
    payload = _valid_receipt_payload("concept_sync")
    payload.update(discovered=0, unchanged=0, upserted=0, deleted=7, empty_corpus=True)
    receipt = InitialSyncReceipt.model_validate_json(json.dumps(payload))
    assert (receipt.empty_corpus, receipt.deleted) == (True, 7)


def test_receipt_contract_rejects_an_empty_corpus_that_still_claims_work() -> None:
    payload = _valid_receipt_payload("concept_sync")
    payload.update(discovered=0, unchanged=3, upserted=0, empty_corpus=True)
    with pytest.raises(ValidationError, match="unchanged"):
        InitialSyncReceipt.model_validate_json(json.dumps(payload))


def test_verify_rejects_a_receipt_stored_under_the_wrong_producer_name(tmp_path: Path) -> None:
    """The file name is part of the evidence: a swapped pair must not verify."""
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    receipt_dir.mkdir(parents=True)
    # Both files carry a *valid* receipt — only the pairing is swapped.
    (receipt_dir / "story_sync.json").write_text(
        json.dumps(_valid_receipt_payload("concept_sync")), encoding="utf-8"
    )
    (receipt_dir / "concept_sync.json").write_text(
        json.dumps(_valid_receipt_payload("story_sync")), encoding="utf-8"
    )
    with pytest.raises(InstallationError, match="wrong producer"):
        verify_initial_sync(tmp_path)


def test_verify_accepts_the_contract_conform_receipt_pair(tmp_path: Path) -> None:
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    receipt_dir.mkdir(parents=True)
    for tool in ("story_sync", "concept_sync"):
        (receipt_dir / f"{tool}.json").write_text(json.dumps(_valid_receipt_payload(tool)), encoding="utf-8")
    story, concept = verify_initial_sync(tmp_path)
    assert (story.tool, concept.tool) == ("story_sync", "concept_sync")


def test_verify_rejects_a_pair_spliced_from_two_projects(tmp_path: Path) -> None:
    """The pair is evidence for ONE run; two project ids prove neither run."""
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    receipt_dir.mkdir(parents=True)
    story = _valid_receipt_payload("story_sync")
    concept = _valid_receipt_payload("concept_sync")
    concept["project_id"] = "a-different-project"
    (receipt_dir / "story_sync.json").write_text(json.dumps(story), encoding="utf-8")
    (receipt_dir / "concept_sync.json").write_text(json.dumps(concept), encoding="utf-8")
    with pytest.raises(InstallationError, match="different projects"):
        verify_initial_sync(tmp_path)


def test_existing_swapped_receipt_is_rejected_before_it_becomes_a_before_image(tmp_path: Path) -> None:
    """A swapped pair must not survive as a before-image on the register path."""
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "story_sync.json").write_text(
        json.dumps(_valid_receipt_payload("concept_sync")), encoding="utf-8"
    )
    (receipt_dir / "concept_sync.json").write_text(
        json.dumps(_valid_receipt_payload("story_sync")), encoding="utf-8"
    )
    with pytest.raises(InstallationError, match="wrong producer"):
        run_initial_sync(tmp_path, _project_config(), service=_CoercingCounterService())


def test_second_receipt_write_failure_restores_both_old_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agentkit.backend.installer.cp10a_initial_sync as module

    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    paths = (receipt_dir / "story_sync.json", receipt_dir / "concept_sync.json")
    before = tuple(path.read_bytes() for path in paths)
    before_completions = _completion_snapshot(client)
    before_freshness = _freshness_snapshot(tmp_path, config, client)
    _write_sync_corpora(tmp_path, suffix="after")
    real_write = module.atomic_write_text
    calls = 0

    def fail_second(path: Path, content: str, *, newline: str | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second receipt write failure")
        real_write(path, content, newline=newline)

    monkeypatch.setattr(module, "atomic_write_text", fail_second)
    with pytest.raises(InstallationError, match="restored exactly"):
        run_initial_sync(
            tmp_path,
            config,
            client=client,
        )
    # Both local files are back to their exact previous bytes — never a half pair.
    assert tuple(path.read_bytes() for path in paths) == before
    # The corpus state, by contrast, HAS advanced: the completion is committed
    # before any receipt is published, precisely so that a receipt can never
    # describe a state that was not reached. The residual — a committed corpus
    # whose local evidence is one generation behind — fails closed at the next
    # verify and is republished by the next run. That is the safe direction of
    # the trade; the reverse order produced `status="success"` files for
    # completions that never landed.
    assert _completion_snapshot(client) != before_completions
    assert _freshness_snapshot(tmp_path, config, client) != before_freshness
    # ...and the norm's promise is actually kept: the next verify fails closed
    # instead of certifying the stale pair as current evidence.
    with pytest.raises(InstallationError, match="publication did not complete"):
        verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)


def test_a_crash_right_after_the_commit_is_not_verifiable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: the window must be open BEFORE the commit, not after it.

    A marker written after the commit cannot cover the gap it exists for — a
    crash in between would leave an advanced corpus, stale receipts, no marker
    and no pending journal entry, which is indistinguishable from a clean run.
    """
    import agentkit.backend.installer.cp10a_initial_sync as module

    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    proven = _local_receipt_bytes(tmp_path)
    verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    _write_sync_corpora(tmp_path, suffix="after")
    real_publish = module._publish_receipts  # noqa: SLF001 - crash injection point

    def die_right_after_commit(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt("simulated crash between commit and publication")

    monkeypatch.setattr(module, "_publish_receipts", die_right_after_commit)
    with pytest.raises(KeyboardInterrupt):
        run_initial_sync(tmp_path, config, client=client)
    monkeypatch.setattr(module, "_publish_receipts", real_publish)

    # The corpus moved, the receipts did not — and that is now detectable.
    assert _local_receipt_bytes(tmp_path) == proven
    with pytest.raises(InstallationError, match="publication did not complete"):
        verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    run_initial_sync(tmp_path, config, client=client)
    verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)


def test_a_crash_between_the_two_receipt_writes_is_not_verifiable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6: ``atomic_write_text`` is per-file atomic, the PAIR is not.

    A process that dies after the first receipt landed would otherwise leave a
    mixed pair from two different runs that reads exactly like a proven one.
    """
    import agentkit.backend.installer.cp10a_initial_sync as module

    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)  # proven baseline

    _write_sync_corpora(tmp_path, suffix="after")
    real_write = module.atomic_write_text
    calls = 0

    def die_after_first_receipt(path: Path, content: str, *, newline: str | None = None) -> None:
        nonlocal calls
        # The marker write is the first call; the two receipts follow.
        calls += 1
        real_write(path, content, newline=newline)
        if calls == 2:  # first receipt landed, process "dies" here
            raise KeyboardInterrupt("simulated crash between the paired writes")

    monkeypatch.setattr(module, "atomic_write_text", die_after_first_receipt)
    with pytest.raises(KeyboardInterrupt):
        run_initial_sync(tmp_path, config, client=client)
    monkeypatch.undo()

    # A mixed pair is on disk and each file is individually well-formed — but the
    # open publication window makes it unusable as evidence.
    with pytest.raises(InstallationError, match="publication did not complete"):
        verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    # The next run republishes and closes the window.
    run_initial_sync(tmp_path, config, client=client)
    verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)


def test_atomic_engine_completion_failure_restores_local_and_store_before_image(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    before = (
        _completion_snapshot(client),
        _freshness_snapshot(tmp_path, config, client),
        _local_receipt_bytes(tmp_path),
    )
    _write_sync_corpora(tmp_path, suffix="after")
    client.fail_run_receipt_insert = True

    with pytest.raises(InstallationError, match="restored exactly"):
        run_initial_sync(tmp_path, config, client=client)

    assert _completion_snapshot(client) == before[0]
    assert _freshness_snapshot(tmp_path, config, client) == before[1]
    assert _local_receipt_bytes(tmp_path) == before[2]


def test_cp10a_ack_loss_after_committed_insert_is_idempotent_success(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    _write_sync_corpora(tmp_path, suffix="after")
    client.lose_run_receipt_ack_after_insert = True

    outcome = run_initial_sync(tmp_path, config, client=client)

    revisions = dict(_freshness_snapshot(tmp_path, config, client))
    story, concept = outcome.receipts
    assert revisions["story"] == story.end_revision
    assert revisions["research"] == story.end_revision
    assert revisions["concept"] == concept.end_revision
    assert not (
        tmp_path
        / ".agentkit"
        / "receipts"
        / "vectordb"
        / "pending-commits"
    ).exists()


def test_cp10a_unknown_ack_outcome_is_durable_and_resolved_before_retry(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    old_bytes = _local_receipt_bytes(tmp_path)
    _write_sync_corpora(tmp_path, suffix="after")
    client.lose_run_receipt_ack_after_insert = True
    client.fail_run_receipt_readback_after_lost_ack = True

    with pytest.raises(InstallationError, match="commit_outcome_unknown"):
        run_initial_sync(tmp_path, config, client=client)

    pending = (
        tmp_path
        / ".agentkit"
        / "receipts"
        / "vectordb"
        / "pending-commits"
    )
    # Nothing was published: receipts are written only AFTER a resolved commit,
    # so the files still carry the last PROVEN state, not a candidate.
    assert _local_receipt_bytes(tmp_path) == old_bytes
    assert len(tuple(pending.glob("*.json"))) == 1

    # Those older receipts are genuine evidence for an older state — but while
    # this project has an unresolved completion, no reader may treat the local
    # evidence as current. A mandatory checkpoint must not attest freshness
    # while an outcome nobody observed is still open.
    with pytest.raises(InstallationError, match="outcome is still unknown"):
        verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    client.fail_run_receipt_reads = False
    recovered = run_initial_sync(tmp_path, config, client=client)

    revisions = dict(_freshness_snapshot(tmp_path, config, client))
    assert revisions["story"] == recovered.receipts[0].end_revision
    assert revisions["research"] == recovered.receipts[0].end_revision
    assert revisions["concept"] == recovered.receipts[1].end_revision
    assert not pending.exists()
    # Once the outcome is resolved, the very same receipts become real evidence.
    verified = verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)
    assert verified[0].end_revision == recovered.receipts[0].end_revision


def test_unknown_outcome_resolved_to_not_committed_leaves_no_false_evidence(
    tmp_path: Path,
) -> None:
    """R5 blocker: the journal moves OUTCOME_UNKNOWN -> NOT_COMMITTED.

    ``list_pending`` reports only genuinely unknown outcomes, so the verify
    guard stops firing once the outcome is resolved. That is correct — and it
    is only safe because no candidate was ever published under the final
    receipt names: what remains on disk is the last PROVEN pair, not a success
    claim for the completion that did not land.
    """
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    proven = _local_receipt_bytes(tmp_path)
    proven_receipts = verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    _write_sync_corpora(tmp_path, suffix="after")
    client.lose_run_receipt_ack_after_insert = True
    client.fail_run_receipt_readback_after_lost_ack = True
    with pytest.raises(InstallationError, match="commit_outcome_unknown"):
        run_initial_sync(tmp_path, config, client=client)

    # Resolve the outcome definitively to "not committed".
    journal = project_commit_recovery_journal(tmp_path)
    pending = journal.list_pending(config.project_prefix)
    assert len(pending) == 1
    journal.finish_not_committed(pending[0])
    assert journal.list_pending(config.project_prefix) == ()

    # The receipts on disk are still the proven ones from the first run, byte
    # for byte — no false evidence was created.
    assert _local_receipt_bytes(tmp_path) == proven

    # The publication fence nevertheless stays OPEN until a run re-proves the
    # pair against the resolved state. Resolving the journal by hand does not
    # re-certify the receipts, so verify stays fail-closed: conservative, and
    # the next run clears it.
    with pytest.raises(InstallationError, match="publication did not complete"):
        verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)

    client.lose_run_receipt_ack_after_insert = False
    client.fail_run_receipt_readback_after_lost_ack = False
    client.fail_run_receipt_reads = False
    run_initial_sync(tmp_path, config, client=client)
    verified = verify_initial_sync(tmp_path, expected_project_id=config.project_prefix)
    assert verified[0].project_id == proven_receipts[0].project_id


def test_verify_rejects_receipts_carried_over_from_another_project(tmp_path: Path) -> None:
    """Receipts copied from a foreign project are not this project's evidence."""
    receipt_dir = tmp_path / ".agentkit" / "receipts" / "vectordb"
    receipt_dir.mkdir(parents=True)
    for tool in ("story_sync", "concept_sync"):
        (receipt_dir / f"{tool}.json").write_text(json.dumps(_valid_receipt_payload(tool)), encoding="utf-8")
    # The pair is internally consistent — it just belongs to someone else.
    verify_initial_sync(tmp_path, expected_project_id="demo")
    with pytest.raises(InstallationError, match="not 'a-different-project'"):
        verify_initial_sync(tmp_path, expected_project_id="a-different-project")


def test_cp10a_real_query_transport_failure_restores_exact_before_image(
    tmp_path: Path,
) -> None:
    """A concrete Weaviate query fault takes CP10a's rollback-safe typed branch."""
    config = _project_config()
    client = RealQueryBoundaryWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="before")
    run_initial_sync(tmp_path, config, client=client)
    before = (
        _completion_snapshot(client),
        _freshness_snapshot(tmp_path, config, client),
        _local_receipt_bytes(tmp_path),
    )
    _write_sync_corpora(tmp_path, suffix="after")
    client.reject_next_run_insert = True

    with pytest.raises(
        InstallationError,
        match="freshness were restored exactly",
    ):
        run_initial_sync(tmp_path, config, client=client)

    client.fail_real_run_reads = False
    assert _completion_snapshot(client) == before[0]
    assert _freshness_snapshot(tmp_path, config, client) == before[1]
    assert _local_receipt_bytes(tmp_path) == before[2]
    journal = project_commit_recovery_journal(tmp_path)
    assert journal.list_pending("AG3") == ()
    attempts = client.run_insert_attempts
    restarted = WeaviateCorpusStore(
        client=client,
        recovery_journal=project_commit_recovery_journal(tmp_path),
    )
    restarted.resolve_pending_commits(project_id="AG3")
    assert client.run_insert_attempts == attempts


def test_cp10a_nonempty_to_empty_publishes_authoritative_producer_revisions(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="present")
    run_initial_sync(tmp_path, config, client=client)
    (tmp_path / "work-items" / "AG3-1" / "story.md").unlink()
    (tmp_path / "architecture" / "13_vectordb.md").unlink()

    outcome = run_initial_sync(tmp_path, config, client=client)

    story, concept = outcome.receipts
    assert story.empty_corpus and story.discovered == 0
    assert concept.empty_corpus and concept.discovered == 0
    rows = {
        str(row["source_type"]): row
        for row in _runtime(tmp_path, config, client).story_list_sources({})["sources"]
    }
    assert rows["story"]["last_revision"] == story.end_revision
    assert rows["research"]["last_revision"] == story.end_revision
    assert rows["concept"]["last_revision"] == concept.end_revision
    assert all(row["source_count"] == 0 for row in rows.values())
    assert all(row["chunk_count"] == 0 for row in rows.values())


def test_post_commit_incremental_concept_sync_nonempty_to_empty_advances_freshness(
    tmp_path: Path,
) -> None:
    config = _project_config()
    client = RecordingWeaviateClient()
    _write_sync_corpora(tmp_path, suffix="present")
    service = _runtime(tmp_path, config, client)
    first = service.concept_sync({"full_reindex": True})
    assert first["synced_sources"] == 1
    (tmp_path / "architecture" / "13_vectordb.md").unlink()

    empty = service.concept_sync({"full_reindex": False})

    assert empty["synced_sources"] == 0
    concept = next(
        row
        for row in service.story_list_sources({})["sources"]
        if row["source_type"] == "concept"
    )
    assert concept["last_revision"] == empty["corpus_revision"]
    assert concept["source_count"] == 0
    assert concept["chunk_count"] == 0


def test_two_store_race_reserves_unique_global_completion_ranges(
    tmp_path: Path,
) -> None:
    client = RecordingWeaviateClient()
    client.run_insert_barrier = threading.Barrier(2, timeout=10)
    stores = (
        WeaviateCorpusStore(
            client=client,
            recovery_journal=client.recovery_journal,
        ),
        WeaviateCorpusStore(
            client=client,
            recovery_journal=client.recovery_journal,
        ),
    )
    revisions = ("revision-a", "revision-b")
    outcomes: list[tuple[str, tuple[SyncReceipt, ...]]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def publish(index: int) -> None:
        revision = revisions[index]
        receipts = tuple(
            SyncReceipt.for_completion(
                "AG3",
                f"architecture/{index}-{offset}.md",
                "concept",
                revision,
                generation=1,
            )
            for offset in range(2)
        )
        producer = (
            ProducerCompletion(
                project_id="AG3",
                producer="concept_sync",
                source_types=("concept",),
                corpus_revision=revision,
            ),
        )
        try:
            sealed = tuple(
                stores[index].set_receipts(
                    run_id=completion_run_id("AG3", receipts, producer),
                    receipts=receipts,
                    producer_completions=producer,
                )
            )
            with lock:
                outcomes.append((revision, sealed))
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=publish, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    sequences = sorted(
        receipt.sequence
        for _revision, receipts in outcomes
        for receipt in receipts
    )
    assert sequences == [1, 2, 3, 4]
    producer_completions = stores[0].list_producer_completions(project_id="AG3")
    latest = max(producer_completions, key=lambda item: item.sequence)
    freshness = dict(_freshness_snapshot(tmp_path, _project_config(), client))
    assert freshness["concept"] == latest.corpus_revision


def test_hook_owner_materialises_both_phases_and_git_discovery_fails_closed(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    outcome = migrate_git_hook_dispatch(tmp_path)
    assert outcome.migrated
    verify_git_hook_dispatch(tmp_path)

    non_repo = tmp_path.parent / f"{tmp_path.name}-not-a-repository"
    non_repo.mkdir()
    with pytest.raises(RuntimeError, match="changed-path discovery failed"):
        _changed_paths(non_repo, staged=True)


def _git_hooks_path(project_root: Path) -> str | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "config",
            "--local",
            "--get",
            "core.hooksPath",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def test_real_hook_pair_replaces_legacy_secret_owner_and_chains_foreign_commands_once(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    hooks = tmp_path / "tools" / "hooks"
    hooks.mkdir(parents=True)
    pre = hooks / "pre-commit"
    post = hooks / "post-commit"
    foreign_log = tmp_path / "foreign.log"
    python_log = tmp_path / "python.log"
    pre.write_text(
        "#!/bin/sh\n"
        "# agentkit secret-detection (global)\n"
        "python -m agentkit.backend.governance.guard_system.secret_scan --staged\n"
        f'printf "%s\\n" pre >> "{foreign_log.as_posix()}"\n',
        encoding="utf-8",
    )
    post.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" post >> "{foreign_log.as_posix()}"\n',
        encoding="utf-8",
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{python_log.as_posix()}"\n',
        encoding="utf-8",
    )
    os.chmod(fake_python, 0o755)

    migrate_git_hook_dispatch(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    subprocess.run(
        ["sh", str(pre)],
        cwd=tmp_path,
        env=env,
        check=True,
    )
    subprocess.run(
        ["sh", str(post)],
        cwd=tmp_path,
        env=env,
        check=True,
    )

    calls = python_log.read_text(encoding="utf-8").splitlines()
    assert sum("--phase pre-commit" in call for call in calls) == 1
    assert sum("--phase post-commit" in call for call in calls) == 1
    assert all("guard_system.secret_scan" not in call for call in calls)
    assert foreign_log.read_text(encoding="utf-8").splitlines() == [
        "pre",
        "post",
    ]
    verify_git_hook_dispatch(tmp_path)


@pytest.mark.parametrize(
    ("interpreter", "pre_body", "post_body"),
    [
        (
            "#!/bin/sh",
            'printf "%s\\n" pre >> "{log}"',
            'printf "%s\\n" post >> "{log}"',
        ),
        (
            "#!/usr/bin/env bash",
            'items=(pre); printf "%s\\n" "${{items[0]}}" >> "{log}"',
            'items=(post); printf "%s\\n" "${{items[0]}}" >> "{log}"',
        ),
        (
            "#!/usr/bin/env python3",
            'from pathlib import Path\nPath(r"{log}").open("a", encoding="utf-8").write("pre\\n")',
            'from pathlib import Path\nPath(r"{log}").open("a", encoding="utf-8").write("post\\n")',
        ),
    ],
)
def test_foreign_pre_and_post_hooks_keep_their_real_interpreter(
    tmp_path: Path,
    interpreter: str,
    pre_body: str,
    post_body: str,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    hooks = tmp_path / "tools" / "hooks"
    hooks.mkdir(parents=True)
    log = (tmp_path / "foreign-interpreter.log").as_posix()
    pre = hooks / "pre-commit"
    post = hooks / "post-commit"
    pre.write_text(
        interpreter + "\n" + pre_body.format(log=log) + "\n",
        encoding="utf-8",
    )
    post.write_text(
        interpreter + "\n" + post_body.format(log=log) + "\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(fake_python, 0o755)

    migrate_git_hook_dispatch(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    subprocess.run(["sh", str(pre)], cwd=tmp_path, env=env, check=True)
    subprocess.run(["sh", str(post)], cwd=tmp_path, env=env, check=True)

    assert (hooks / "pre-commit.bak").read_text(encoding="utf-8").startswith(
        interpreter + "\n"
    )
    assert (hooks / "post-commit.bak").read_text(encoding="utf-8").startswith(
        interpreter + "\n"
    )
    assert os.access(hooks / "pre-commit.bak", os.X_OK)
    assert os.access(hooks / "post-commit.bak", os.X_OK)
    assert (tmp_path / "foreign-interpreter.log").read_text(
        encoding="utf-8"
    ).splitlines() == ["pre", "post"]


def test_unknown_secret_marker_structure_is_not_partially_rewritten(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    hooks = tmp_path / "tools" / "hooks"
    hooks.mkdir(parents=True)
    pre = hooks / "pre-commit"
    post = hooks / "post-commit"
    pre.write_text(
        "#!/bin/sh\n"
        "# agentkit secret-detection customized\n"
        "python -m agentkit.backend.governance.guard_system.secret_scan --staged\n",
        encoding="utf-8",
    )
    post.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    before = (pre.read_bytes(), post.read_bytes())

    with pytest.raises(ValueError, match="unrecognised AgentKit secret marker"):
        migrate_git_hook_dispatch(tmp_path)

    assert (pre.read_bytes(), post.read_bytes()) == before
    assert _git_hooks_path(tmp_path) is None
    assert not (hooks / "pre-commit.bak").exists()
    assert not (hooks / "post-commit.bak").exists()


def test_hook_pair_second_write_fault_restores_files_and_activation_before_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.installer import git_hook_dispatch

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "foreign-hooks"],
        cwd=tmp_path,
        check=True,
    )
    hooks = tmp_path / "tools" / "hooks"
    hooks.mkdir(parents=True)
    pre = hooks / "pre-commit"
    post = hooks / "post-commit"
    pre.write_bytes(b"#!/bin/sh\nprintf pre\n")
    post.write_bytes(b"#!/bin/sh\nprintf post\n")
    before = (pre.read_bytes(), post.read_bytes(), _git_hooks_path(tmp_path))
    publish = git_hook_dispatch._publish_hook
    calls = 0

    def _fail_second(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second hook write failed")
        publish(path, content)

    monkeypatch.setattr(git_hook_dispatch, "_publish_hook", _fail_second)
    with pytest.raises(OSError, match="second hook write failed"):
        migrate_git_hook_dispatch(tmp_path)

    assert (pre.read_bytes(), post.read_bytes(), _git_hooks_path(tmp_path)) == before
    assert not pre.with_name("pre-commit.bak").exists()
    assert not post.with_name("post-commit.bak").exists()


def test_hook_activation_fault_restores_pair_and_core_hooks_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.installer import git_hook_dispatch

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "foreign-hooks"],
        cwd=tmp_path,
        check=True,
    )
    hooks = tmp_path / "tools" / "hooks"
    hooks.mkdir(parents=True)
    pre = hooks / "pre-commit"
    post = hooks / "post-commit"
    pre.write_bytes(b"#!/bin/sh\nprintf pre\n")
    post.write_bytes(b"#!/bin/sh\nprintf post\n")
    before = (pre.read_bytes(), post.read_bytes(), _git_hooks_path(tmp_path))
    write_hooks_path = git_hook_dispatch._write_hooks_path

    def _fail_after_activation(project_root: Path, value: str | None) -> None:
        write_hooks_path(project_root, value)
        if value == "tools/hooks/":
            raise OSError("activation failed after mutation")

    monkeypatch.setattr(
        git_hook_dispatch,
        "_write_hooks_path",
        _fail_after_activation,
    )
    with pytest.raises(OSError, match="activation failed after mutation"):
        migrate_git_hook_dispatch(tmp_path)

    assert (pre.read_bytes(), post.read_bytes(), _git_hooks_path(tmp_path)) == before
    assert not pre.with_name("pre-commit.bak").exists()
    assert not post.with_name("post-commit.bak").exists()


def _commit_concept_change(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "agentkit@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AgentKit"],
        cwd=tmp_path,
        check=True,
    )
    concept = tmp_path / "architecture" / "changed.md"
    concept.parent.mkdir(parents=True)
    concept.write_text("# changed\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", "architecture/changed.md"],
        cwd=tmp_path,
        check=True,
    )


def test_pre_commit_dispatch_runs_secret_scan_then_staged_concept_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.vectordb import hook_dispatch

    _write_existing_config(tmp_path, features_yaml="  features: {multi_llm: false}")
    _commit_concept_change(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def _record(
        command: list[str],
        *,
        project_root: Path,
        env: dict[str, str] | None = None,
    ) -> int:
        assert project_root == tmp_path
        calls.append((command, env))
        return 0

    monkeypatch.setattr(hook_dispatch, "_run", _record)

    assert hook_dispatch.dispatch(tmp_path, phase="pre-commit") == 0
    assert "secret_scan" in " ".join(calls[0][0])
    assert "--staged" in calls[0][0]
    assert "validate" in calls[1][0]
    assert "--staged" in calls[1][0]
    assert str(tmp_path / "architecture") in calls[1][0]


@pytest.mark.parametrize(
    ("statuses", "expected", "expected_calls"),
    (([7], 7, 1), ([0, 9], 9, 2), ([0, 0], 0, 2)),
)
def test_post_commit_dispatch_builds_before_sync_and_stops_on_each_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    expected: int,
    expected_calls: int,
) -> None:
    from agentkit.backend.vectordb import hook_dispatch

    _write_existing_config(tmp_path, features_yaml="  features: {multi_llm: false}")
    _commit_concept_change(tmp_path)
    subprocess.run(["git", "commit", "-m", "concept"], cwd=tmp_path, check=True, capture_output=True)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def _record(
        command: list[str],
        *,
        project_root: Path,
        env: dict[str, str] | None = None,
    ) -> int:
        assert project_root == tmp_path
        calls.append((command, env))
        return statuses[len(calls) - 1]

    monkeypatch.setattr(hook_dispatch, "_run", _record)

    assert hook_dispatch.dispatch(tmp_path, phase="post-commit") == expected
    assert len(calls) == expected_calls
    assert "build" in calls[0][0]
    if expected_calls == 2:
        assert calls[1][0][-1] == "sync"
        assert "--full" not in calls[1][0]
        assert calls[1][1] is not None
        assert calls[1][1]["PROJECT_ID"] == "AG3"
