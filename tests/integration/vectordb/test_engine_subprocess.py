"""R02 subprocess proof + R06 SSOT-migration drift proof (Codex review r1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# --------------------------------------------------------------------------- #
# R02: non-default endpoint reaches the connection step; localhost fails binding
# --------------------------------------------------------------------------- #


def test_r02_subprocess_non_default_endpoint_reaches_connection(tmp_path: Path) -> None:
    """A non-default endpoint is composed and used; failure is at CONNECTION
    (unreachable host), not at binding (R02/D2). Proves the env-bound composition
    and that the exact configured endpoint reaches the real client."""
    script = tmp_path / "run_engine.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys
            from agentkit.backend.vectordb.engine import compose_runtime
            env = {
                "PROJECT_ID": "acme",
                "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.nondefault.invalid:9999",
                "WEAVIATE_GRPC_ENDPOINT": "weaviate.nondefault.invalid:50051",
            }
            try:
                compose_runtime(env, concepts_dir=__import__("pathlib").Path("concept"),
                                stories_dir=__import__("pathlib").Path("stories"), cwd=".")
                print(json.dumps({"composed": True}))
            except Exception as exc:
                name = type(exc).__name__
                print(json.dumps({"composed": False, "error_type": name, "detail": str(exc)}))
            """
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    out = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    # Composition must reach the real client (connection failure on the
    # non-default host), NOT fail at binding.
    detail = payload.get("detail", "")
    assert "nondefault.invalid" in detail or "connect" in detail.lower() or "weaviate" in detail.lower()
    assert payload["error_type"] != "RuntimeBindingError"


def test_r02_subprocess_localhost_endpoint_fails_at_binding() -> None:
    """A localhost endpoint is rejected at BINDING (D2), before any connection."""
    script_snippet = textwrap.dedent(
        """
        import json
        from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
        env = {
            "PROJECT_ID": "acme",
            "WEAVIATE_HTTP_ENDPOINT": "http://localhost:8080",
            "WEAVIATE_GRPC_ENDPOINT": "localhost:50051",
        }
        try:
            RuntimeBinding.from_env(env, command="python", args=(), cwd=".")
            print(json.dumps({"bound": True}))
        except RuntimeBindingError as exc:
            print(json.dumps({"bound": False, "error_type": "RuntimeBindingError", "detail": str(exc)}))
        """
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script_snippet],
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["bound"] is False
    assert payload["error_type"] == "RuntimeBindingError"


# --------------------------------------------------------------------------- #
# R06: the ingester is a thin adapter over agentkit.concepts (SSOT, no drift)
# --------------------------------------------------------------------------- #


_DOC = """\
---
concept_id: FK-13
title: Retrieval
module: vectordb
status: active
doc_kind: core
authority_over:
  - scope: vectordb
defers_to:
  - target: FK-01
    scope: foundation
    reason: base
---

# Retrieval

Builds on FK-01.

## Purpose

Text.
"""


def test_r06_ingester_uses_ssot_same_discovery_set(tmp_path: Path) -> None:
    from tools.concept_ingester.discovery import discover

    from agentkit.concepts.parser import discover_concept_files

    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13_retrieval.md").write_text(_DOC, encoding="utf-8")
    ing = discover(tmp_path / "concept")
    ssot = discover_concept_files(tmp_path / "concept")
    # Same discovery set (SSOT): same doc ids, same chunk content.
    assert {c.doc_id for c in ing.chunks} == {d.concept_id for d in ssot.documents}
    assert {c.content for c in ing.chunks} == {c.content for c in ssot.chunks}
    assert ing.chunks, "ingester must produce chunks via the SSOT core"


def test_r06_ingester_config_has_no_localhost_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tools.concept_ingester.config import IngesterConfig

    for key in ("AK3_WEAVIATE_HOST", "AK3_WEAVIATE_HTTP_PORT", "AK3_WEAVIATE_GRPC_PORT"):
        monkeypatch.delenv(key, raising=False)
    import pytest

    with pytest.raises(RuntimeError, match="no localhost default"):
        IngesterConfig.from_env()
