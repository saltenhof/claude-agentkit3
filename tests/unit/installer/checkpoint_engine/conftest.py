"""Shared fixtures for the installer checkpoint-engine unit tests (AG3-088).

Builds an :class:`InstallConfig` wired with an in-memory registration repo and a
provisioned skill-bundle store + binding repo, so the engine can run a full
``register`` mode end-to-end against ``tmp_path`` WITHOUT a live state backend
(unit-level isolation; the integration suite exercises the real Postgres path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.backend.installer.runner import MANDATORY_SKILLS, InstallConfig
from agentkit.backend.skills import Skills
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.backend.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


class InMemoryRegistrationRepo:
    """In-memory ``ProjectRegistrationRepository`` for unit isolation."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}
        self.save_calls = 0
        self.upgrade_calls = 0

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration
        self.save_calls += 1

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(update={"last_verified_at": verified_at})

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(
            update={"last_upgraded_at": upgraded_at, "config_digest": new_digest}
        )
        self.upgrade_calls += 1

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[k] for k in sorted(self.rows)]


def _provisioned_skills(bundle_store_root: Path) -> tuple[Skills, SkillBundleStore]:
    import json

    from agentkit.backend.skills.manifest_digest import compute_manifest_digest

    store = SkillBundleStore(store_root=bundle_store_root)
    for skill_name in MANDATORY_SKILLS:
        bundle_root = bundle_store_root / f"{skill_name}-core" / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(f"# {skill_name}\n", encoding="utf-8")
        # Real manifest so CP8 VERIFY can pin id/version/digest (AG3-176 R8).
        payload: dict[str, object] = {
            "bundle_id": f"{skill_name}-core",
            "bundle_version": "4.0.0",
            "profile": "CORE",
            "skill_name": skill_name,
            "variants": {"CORE": skill_name},
        }
        digest = compute_manifest_digest(payload)
        payload["manifest_digest"] = digest
        (bundle_root / "manifest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        store.register_bundle(
            SkillBundle(
                bundle_id=f"{skill_name}-core",
                bundle_version="4.0.0",
                bundle_root=bundle_root,
                manifest_digest=digest,
            )
        )
    skills = Skills(bundle_store=store, binding_repo=InMemorySkillBindingRepository())
    return skills, store


def make_config(
    root: Path,
    *,
    bundle_store_root: Path,
    registration_repo: InMemoryRegistrationRepo,
    repo_existence_probe: object | None = None,
    features_vectordb: bool = False,
    features_are: bool = False,
    are_module_scope_map: dict[str, str] | None = None,
    repositories: list[dict[str, str]] | None = None,
    github_owner: str | None = "acme",
    github_repo: str | None = "demo",
    weaviate_host: str | None = None,
    weaviate_http_port: int | None = None,
    weaviate_grpc_port: int | None = None,
) -> InstallConfig:
    """Build an :class:`InstallConfig` for the engine unit tests."""
    # CP 11 (FK-50 §50.3) configures core.hooksPath on the target project; real
    # AK3 targets ARE git repos, so the unit setup must provision one (else CP 11
    # fails on a clean CI agent where tmp_path is not inside any repo).
    ensure_git_repo(root)
    skills, store = _provisioned_skills(bundle_store_root)
    # AG3-176 AC6: VectorDB is mandatory — always supply a deterministic
    # non-default endpoint in unit fixtures (no silent localhost). Callers may
    # still pin host/ports explicitly for dual-harness / preflight tests.
    if weaviate_host is None:
        weaviate_host = "weaviate.test.local"
    if weaviate_http_port is None:
        weaviate_http_port = 19903
    if weaviate_grpc_port is None:
        weaviate_grpc_port = 50051
    return InstallConfig(
        project_key=root.stem,
        project_name=root.stem,
        project_root=root,
        github_owner=github_owner,
        github_repo=github_repo,
        repositories=repositories,
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids=_BUNDLE_IDS,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        runtime_profile=RuntimeProfile.CORE,
        repo_existence_probe=repo_existence_probe,  # type: ignore[arg-type]
        features_vectordb=features_vectordb,
        features_are=features_are,
        are_module_scope_map=are_module_scope_map,
        sonarqube_available=False,
        ci_available=False,
        weaviate_host=weaviate_host,
        weaviate_http_port=weaviate_http_port,
        weaviate_grpc_port=weaviate_grpc_port,
    )


@pytest.fixture
def registration_repo() -> InMemoryRegistrationRepo:
    """A fresh in-memory registration repo."""
    return InMemoryRegistrationRepo()


@pytest.fixture(autouse=True)
def _stub_vectordb_endpoint_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """AG3-176: unit tests do not hit a real Weaviate (fake at the external port).

    Shape resolution still runs; only the live meta/ready probes are stubbed
    so full-flow installer unit tests can pass CP10 without network.
    """
    import agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp as cp10_mcp
    import agentkit.backend.installer.bootstrap_checkpoints.cp10a_first_index as cp10a
    from agentkit.backend.vectordb.first_index import FirstIndexResult
    from agentkit.backend.vectordb.indexing_receipt import (
        IndexingReceipt,
        IndexingStatus,
    )

    monkeypatch.setattr(
        cp10_mcp,
        "_PREFLIGHT_META_FETCHER",
        lambda host, port, timeout: {"version": "1.24.0", "hostname": str(host)},
    )
    monkeypatch.setattr(
        cp10_mcp,
        "_PREFLIGHT_READY_PROBE",
        lambda host, port: True,
    )

    def _fake_first_index(context: object) -> FirstIndexResult:
        from pathlib import Path

        root = getattr(context, "project_root", Path("."))
        receipt = IndexingReceipt(
            project_id="unit",
            producer_tool="story_sync",
            owned_source_types=("story", "research"),
            discovered=0,
            unchanged=0,
            upserted=0,
            deleted=0,
            failed=0,
            empty_corpus=True,
            start_revision="",
            end_revision="rev0",
            status=IndexingStatus.EMPTY_CORPUS,
            generation_id="gen0",
            published_at="2026-07-21T00:00:00Z",
            digest="0" * 64,
        )
        concept = IndexingReceipt(
            project_id="unit",
            producer_tool="concept_sync",
            owned_source_types=("concept",),
            discovered=0,
            unchanged=0,
            upserted=0,
            deleted=0,
            failed=0,
            empty_corpus=True,
            start_revision="",
            end_revision="rev0",
            status=IndexingStatus.EMPTY_CORPUS,
            generation_id="gen0",
            published_at="2026-07-21T00:00:00Z",
            digest="0" * 64,
        )
        return FirstIndexResult(
            story_receipt=receipt,
            concept_receipt=concept,
            story_receipt_path=Path(root)
            / ".agentkit"
            / "vectordb"
            / "receipts"
            / "s.json",
            concept_receipt_path=Path(root)
            / ".agentkit"
            / "vectordb"
            / "receipts"
            / "c.json",
        )

    monkeypatch.setattr(cp10a, "_execute_first_index", _fake_first_index)

    # Full-flow installs always hit dual-harness MCP probe. Default stub keeps
    # unit tests offline. Tests that need real fail-closed conformance rebind
    # ``check_mcp_conformance`` to the production function themselves.
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    monkeypatch.setattr(
        cp10_mcp,
        "check_mcp_conformance",
        lambda cmd, **kwargs: McpConformanceResult(
            ok=True,
            reason=None,
            detail="stubbed ok for unit tests",
            tool_names=("story_search", "concept_search"),
        ),
    )
