"""Contract tests for shipped FK-43 skill bundles (all SemVer directories)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.skills.bundle_store import SkillBundleStore, shipped_skill_bundles_root
from agentkit.backend.skills.manifest_digest import compute_manifest_digest

if TYPE_CHECKING:
    from pathlib import Path


def _all_manifest_paths() -> list[Path]:
    """Every shipped ``{bundle_id}/{version}/manifest.json`` (version-independent)."""
    root = shipped_skill_bundles_root()
    return sorted(root.glob("*/*/manifest.json"))


def _read_manifest(path: Path) -> dict[str, object]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_shipped_bundle_manifest_digest_and_directory_consistency() -> None:
    """Every shipped manifest digests with the product helper; store highest is consistent."""
    store = SkillBundleStore()
    paths = _all_manifest_paths()
    assert paths, "expected at least one shipped skill bundle manifest"

    by_bundle_id: dict[str, list[Path]] = {}
    for manifest_path in paths:
        # layout: .../skill_bundles/{bundle_id}/{version}/manifest.json
        version_dir = manifest_path.parent
        bundle_dir = version_dir.parent
        bundle_id = bundle_dir.name
        version = version_dir.name
        payload = _read_manifest(manifest_path)

        assert payload["bundle_id"] == bundle_id
        assert payload["bundle_version"] == version
        declared = payload.get("manifest_digest")
        assert isinstance(declared, str) and declared
        assert declared == compute_manifest_digest(payload)

        by_bundle_id.setdefault(bundle_id, []).append(manifest_path)

    # Store resolution picks highest SemVer; its root must be one of the shipped dirs.
    for bundle_id, version_manifests in by_bundle_id.items():
        bundle = store.get_bundle(bundle_id)
        assert bundle.bundle_id == bundle_id
        shipped_roots = {p.parent for p in version_manifests}
        assert bundle.bundle_root in shipped_roots
        # Digest of the selected version must match product helper.
        selected_manifest = _read_manifest(bundle.bundle_root / "manifest.json")
        assert selected_manifest["manifest_digest"] == compute_manifest_digest(
            selected_manifest
        )
        assert selected_manifest["bundle_version"] == bundle.bundle_version


def test_skill_catalog_complete_by_skill_name_and_profile_bundle() -> None:
    manifests = [_read_manifest(path) for path in _all_manifest_paths()]
    # Deduplicate by bundle_id using highest version present in the list order
    # is not required for set membership of skill names.
    by_skill_name: dict[str, set[str]] = {}
    by_bundle_id_profiles: dict[str, set[str]] = {}
    for manifest in manifests:
        skill = str(manifest["skill_name"])
        bid = str(manifest["bundle_id"])
        by_skill_name.setdefault(skill, set()).add(bid)
        by_bundle_id_profiles.setdefault(bid, set()).add(str(manifest["profile"]))

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

    assert "CORE" in by_bundle_id_profiles["create-userstory-core"]
    assert "ARE" in by_bundle_id_profiles["create-userstory-are"]
    assert "CORE" in by_bundle_id_profiles["execute-userstory-core"]
    assert "ARE" in by_bundle_id_profiles["execute-userstory-are"]
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
