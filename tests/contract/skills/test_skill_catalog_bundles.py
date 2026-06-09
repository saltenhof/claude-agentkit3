"""Contract tests for shipped FK-43 skill bundles."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from agentkit.skills.bundle_store import SkillBundleStore, shipped_skill_bundles_root

if TYPE_CHECKING:
    from pathlib import Path


def _manifest_paths() -> list[Path]:
    return sorted(shipped_skill_bundles_root().glob("*/4.0.0/manifest.json"))


def _read_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _expected_manifest_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "manifest_digest"},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_shipped_bundle_manifest_digest_and_directory_consistency() -> None:
    store = SkillBundleStore()

    for manifest_path in _manifest_paths():
        bundle_dir = manifest_path.parents[1]
        payload = _read_manifest(manifest_path)

        assert payload["bundle_id"] == bundle_dir.name
        assert payload["manifest_digest"] == _expected_manifest_digest(payload)

        bundle = store.get_bundle(bundle_dir.name)
        assert bundle.bundle_id == bundle_dir.name
        assert bundle.bundle_root == manifest_path.parent


def test_skill_catalog_complete_by_skill_name_and_profile_bundle() -> None:
    manifests = [_read_manifest(path) for path in _manifest_paths()]
    by_bundle_id = {str(manifest["bundle_id"]): manifest for manifest in manifests}
    by_skill_name: dict[str, set[str]] = {}
    for manifest in manifests:
        by_skill_name.setdefault(str(manifest["skill_name"]), set()).add(
            str(manifest["bundle_id"])
        )

    assert by_skill_name["create-userstory"] == {
        "create-userstory-core",
        "create-userstory-are",
    }
    assert by_skill_name["execute-userstory"] == {
        "execute-userstory-core",
        "execute-userstory-are",
    }
    assert by_skill_name["lookup-userstory"] == {"lookup-userstory-core"}
    assert by_skill_name["llm-discussion"] == {"llm-discussion-core"}
    assert by_skill_name["manage-requirements"] == {"manage-requirements-core"}
    assert by_skill_name["semantic-review"] == {"semantic-review-core"}

    assert by_bundle_id["create-userstory-core"]["profile"] == "CORE"
    assert by_bundle_id["create-userstory-are"]["profile"] == "ARE"
    assert by_bundle_id["execute-userstory-core"]["profile"] == "CORE"
    assert by_bundle_id["execute-userstory-are"]["profile"] == "ARE"
    assert "Research" not in by_skill_name
    assert "research" not in by_skill_name
    assert not (shipped_skill_bundles_root() / "research").exists()
    assert not (shipped_skill_bundles_root() / "research-core").exists()


def test_execute_userstory_core_documents_fk43_eight_steps() -> None:
    skill_md = (
        shipped_skill_bundles_root()
        / "execute-userstory-core"
        / "4.0.0"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    expected_steps = [
        "1. Liest freigegebene Story aus dem AK3-Story-Backend.",
        "2. Ruft `POST /phases/setup/start` auf.",
        "3. Liest Phase-State -> spawnt Worker (oder Exploration-Worker).",
        "4. Wartet auf Worker-Ende.",
        "5. Ruft `POST /phases/implementation/start` auf",
        "Capability `VerifySystem`",
        "6. Liest Phase-State -> bei `qa_cycle_status: awaiting_remediation`",
        "Subflow-Loop, kein Phasenwechsel",
        "7. Bei `qa_cycle_status: pass`",
        "`POST /phases/closure/start`",
        "8. Bei Eskalation: stoppt und informiert Mensch.",
        "There is explicitly no standalone `verify` top-phase.",
    ]
    for expected in expected_steps:
        assert expected in skill_md


def test_semantic_review_core_documents_dimensions_scores_reasons_and_artifact() -> None:
    skill_md = (
        shipped_skill_bundles_root()
        / "semantic-review-core"
        / "4.0.0"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    for dimension in [
        "Naming",
        "Error handling",
        "Cyclomatic complexity",
        "Test coverage",
        "Coupling",
        "Cohesion",
        "Documentation",
        "Security",
        "Backward compatibility",
        "Performance",
        "Project standard consistency",
        "Requirement fidelity",
    ]:
        assert dimension in skill_md

    assert "normalized score in the range `0.0..1.0`" in skill_md
    assert "score + reason" in skill_md
    assert '"artifact_type": "semantic_review_aggregate"' in skill_md
    assert '"qa_subflow_target": "implementation"' in skill_md
    assert '"verify_system_input": true' in skill_md
