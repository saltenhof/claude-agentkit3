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


def test_r02_subprocess_missing_endpoint_fails_at_binding() -> None:
    """A MISSING endpoint is rejected at BINDING (D2), before any connection.

    This is what D2 actually forbids: an endpoint AK3 would have to invent. The
    check is on provenance, not on spelling — see
    ``test_r02_subprocess_registered_loopback_endpoint_binds`` below and the
    decision record ``2026-08-02-port-9702-single-owner-und-endpunkt-herkunft``.
    """
    script_snippet = textwrap.dedent(
        """
        import json
        from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
        env = {
            "PROJECT_ID": "acme",
            "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
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


def test_r02_subprocess_registered_loopback_endpoint_binds() -> None:
    """A REGISTERED loopback endpoint binds — it is the normal AK3 topology.

    Regression for the removed endpoint block list: it rejected exactly this env
    and thereby made a local Weaviate (FK-15 localhost-only) unusable, while
    proving nothing about provenance.
    """
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
            binding = RuntimeBinding.from_env(env, command="python", args=(), cwd=".")
            print(json.dumps({"bound": True, "http": binding.weaviate_http_endpoint}))
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
    assert payload["bound"] is True
    assert payload["http"] == "http://localhost:8080"


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
    # R06: the ingester uses the SSOT chunk_hash + chunk_id VERBATIM -- it does
    # NOT re-hash (document_hash) or re-derive chunk ids locally.
    assert {c.content_hash for c in ing.chunks} == {c.content_hash for c in ssot.chunks}
    assert {c.chunk_id for c in ing.chunks} == {c.chunk_id for c in ssot.chunks}
    assert ing.chunks, "ingester must produce chunks via the SSOT core"


_INVALID_DOC = """\
---
concept_id: FK-99
title: Broken
module: vectordb
status: bogus-status
doc_kind: core
---

# Broken

## Purpose

Text.
"""


def test_r06_ingester_fails_closed_on_a_discovery_error(tmp_path: Path) -> None:
    """R06: ANY parse error blocks the ingest -- no partial corpus is published."""
    import pytest
    from tools.concept_ingester.discovery import ConceptDiscoveryError, discover

    from agentkit.concepts.parser import discover_concept_files

    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13_retrieval.md").write_text(_DOC, encoding="utf-8")
    (root / "99_broken.md").write_text(_INVALID_DOC, encoding="utf-8")
    # The SSOT core reports the parse error AND the valid subset...
    ssot = discover_concept_files(tmp_path / "concept")
    assert ssot.errors and ssot.chunks
    # ...but the ingester refuses to ingest that subset.
    with pytest.raises(ConceptDiscoveryError, match="99_broken.md"):
        discover(tmp_path / "concept")


def test_r06_ingester_accepts_a_fully_valid_corpus(tmp_path: Path) -> None:
    from tools.concept_ingester.discovery import discover

    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13_retrieval.md").write_text(_DOC, encoding="utf-8")
    assert discover(tmp_path / "concept").chunks


def test_r06_ingester_config_has_no_localhost_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tools.concept_ingester.config import IngesterConfig

    for key in ("AK3_WEAVIATE_HOST", "AK3_WEAVIATE_HTTP_PORT", "AK3_WEAVIATE_GRPC_PORT"):
        monkeypatch.delenv(key, raising=False)
    import pytest

    with pytest.raises(RuntimeError, match="no localhost default"):
        IngesterConfig.from_env()


_QUALIFIED_DOC = """\
---
concept_id: FK-14
title: Helper
module: vectordb
status: active
doc_kind: core
authority_over:
  - scope: helper.scope
defers_to:
  - target: FK-13
    scope: vectordb
    reason: base
  - target: FK-01
supersedes:
  - target: FK-00
    scope: old-helper
    reason: helper replacement
---

# Helper

## Rule

Text.
"""


def test_r06_ingester_projects_the_scope_qualified_authority_metadata(tmp_path: Path) -> None:
    """The SSOT projection must keep the QUALIFIED authority/deferral entries.

    The VectorDB stores flat ID lists (FK-13 §13.9.3), but the W2/W3 governance
    consumers decide authorization from the SCOPE-QUALIFIED form. Flattening it
    away made every asserted scope look unauthorized.
    """
    import json

    from concept_governance.chunks import authorization_scopes
    from tools.concept_ingester.discovery import discover

    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "14_helper.md").write_text(_QUALIFIED_DOC, encoding="utf-8")
    chunk = discover(tmp_path / "concept").chunks[0]

    assert json.loads(chunk.metadata["authority_over_full"]) == [{"scope": "helper.scope"}]
    assert json.loads(chunk.metadata["defers_to_full"]) == [
        {"reason": "base", "scope": "vectordb", "target": "FK-13"},
        {"reason": "", "scope": "", "target": "FK-01"},
    ]
    assert json.loads(chunk.metadata["supersedes_full"]) == [
        {"reason": "helper replacement", "scope": "old-helper", "target": "FK-00"}
    ]
    # The governance consumer reads owned + scope-qualified delegated scopes; an
    # UNQUALIFIED deferral (FK-01, no scope) authorizes nothing.
    assert authorization_scopes(chunk) == frozenset({"helper.scope", "vectordb"})


_CONTRACT_DOC = """\
---
concept_id: FK-20
title: Contract doc
module: vectordb
status: active
doc_kind: core
contract_state: ratified
applies_policies: [policy-a, policy-b]
formal_refs: [formal.state-storage]
authority_over:
  - scope: contracts
glossary:
  exported_terms:
    - id: Bounded Window
      definition: The switch window of a generation replace.
    - id: Sync Receipt
      definition: The digest-bound completion marker.
---

# Contract doc

## Glossar

Terms.
"""


def test_n20_ingester_projects_the_contract_and_glossary_fields(tmp_path: Path) -> None:
    """N20: the SSOT migration must not drop the BC/contract projections.

    ``contract_state``, ``applies_policies``, formal references, the glossary
    linkage and the exported term ids were hardcoded empty after the migration,
    silently losing the replaced ingester's behaviour. They are not part of the
    typed FK-13 §13.9.6 model, so they come from the raw frontmatter.
    """
    from tools.concept_ingester.discovery import discover

    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "20_contract.md").write_text(_CONTRACT_DOC, encoding="utf-8")
    result = discover(tmp_path / "concept")
    chunk = result.chunks[0]

    assert chunk.contract_state == "ratified"
    assert chunk.applies_policies == ("policy-a", "policy-b")
    assert chunk.formal_ref_ids == ("formal.state-storage",)
    assert chunk.has_glossary is True
    assert chunk.exported_term_ids == ("bounded-window", "sync-receipt")
    # The glossary terms themselves are still projected (unchanged behaviour).
    assert {term.term for term in result.glossary_terms} == {"Bounded Window", "Sync Receipt"}
