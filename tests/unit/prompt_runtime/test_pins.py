"""Tests for prompt run pin persistence."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import ProjectError
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV, prompt_bundle_store_dir
from agentkit.prompt_runtime.pins import (
    ensure_prompt_run_pin,
    ensure_run_prompt_pin_present,
    initialize_prompt_run_pin,
    load_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_runtime.resources import PROJECT_LOCK_RELPATH

if TYPE_CHECKING:
    from pathlib import Path

def _write_binding_lock(project_root: Path) -> None:
    bundle_dir = prompt_bundle_store_dir(
        "project-bound",
        "99",
        store_root=project_root / "prompt-bundles",
    )
    (bundle_dir / "internal" / "prompts").mkdir(parents=True)
    template_content = (
        "# Project Bound Prompt {story_id}\n"
        "[SENTINEL:worker-implementation-v1:{story_id}]\n"
    )
    (bundle_dir / "internal" / "prompts" / "worker-implementation.md").write_text(
        template_content,
        encoding="utf-8",
    )
    manifest_text = json.dumps(
        {
            "bundle_id": "project-bound",
            "bundle_version": "99",
            "templates": {
                "worker-implementation": {
                    "relpath": "internal/prompts/worker-implementation.md",
                    "sha256": sha256(
                        template_content.encode("utf-8"),
                    ).hexdigest(),
                },
            },
        },
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True)
    (project_root / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(
                    manifest_text.encode("utf-8"),
                ).hexdigest(),
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": sha256(
                            template_content.encode("utf-8"),
                        ).hexdigest(),
                    },
                },
            },
        ),
        encoding="utf-8",
    )


def test_ensure_prompt_run_pin_writes_pin_file(tmp_path: Path) -> None:
    path = ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    assert path.is_file()
    loaded = load_prompt_run_pin(tmp_path, "run-1")
    assert loaded is not None
    assert loaded.prompt_bundle_id == "bundle-a"
    assert loaded.prompt_bundle_version == "1"
    assert loaded.prompt_manifest_sha256 == "abc123"


def test_ensure_prompt_run_pin_is_idempotent(tmp_path: Path) -> None:
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    loaded = load_prompt_run_pin(tmp_path, "run-1")
    assert loaded is not None
    assert loaded.prompt_bundle_id == "bundle-a"


def test_ensure_prompt_run_pin_rejects_mid_run_drift(tmp_path: Path) -> None:
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    with pytest.raises(ProjectError, match="Prompt run pin mismatch"):
        ensure_prompt_run_pin(
            tmp_path,
            run_id="run-1",
            prompt_bundle_id="bundle-a",
            prompt_bundle_version="2",
            prompt_manifest_sha256="def456",
        )


def test_initialize_prompt_run_pin_uses_project_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))

    pin = initialize_prompt_run_pin(tmp_path, run_id="run-1")

    assert pin.prompt_bundle_id == "project-bound"
    assert pin.prompt_bundle_version == "99"
    assert len(pin.prompt_manifest_sha256) == 64


def test_resolve_run_prompt_binding_requires_existing_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))

    with pytest.raises(ProjectError, match="Prompt run pin is missing"):
        resolve_run_prompt_binding(tmp_path, "run-1")


def test_mid_run_rebind_does_not_mutate_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2 (FK-44 §44.3, invariant binding_changes_affect_only_future_runs).

    Was previously ``test_resolve_run_prompt_binding_rejects_binding_drift``
    which froze the *buggy* semantics (expected a mismatch after a lock
    version bump). Inverted per AG3-015 Entscheidung 2: after a legitimate
    rebind of the project lock to a new version, an already pinned active
    run keeps resolving its pinned bundle from the central store and does
    NOT raise PROMPT_RUN_PIN_MISMATCH (scenario
    ``mid_run_rebind_does_not_mutate_active_run``).
    """
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    pin = initialize_prompt_run_pin(tmp_path, run_id="run-1")
    assert pin.prompt_bundle_version == "99"

    # Legitimate mid-run rebind: project lock now points at a new version.
    lock = json.loads((tmp_path / PROJECT_LOCK_RELPATH).read_text(encoding="utf-8"))
    lock["bundle_version"] = "100"
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(lock),
        encoding="utf-8",
    )

    # The active run still resolves the PINNED bundle (99), no mismatch.
    binding = resolve_run_prompt_binding(tmp_path, "run-1")
    assert binding.bundle_id == "project-bound"
    assert binding.bundle_version == "99"
    assert binding.manifest_sha256 == pin.prompt_manifest_sha256


def test_ensure_run_prompt_pin_present_creates_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create-if-absent: with no pin yet, the current binding is pinned."""
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))

    assert load_prompt_run_pin(tmp_path, "run-1") is None
    pin = ensure_run_prompt_pin_present(tmp_path, run_id="run-1")

    assert pin.prompt_bundle_id == "project-bound"
    assert pin.prompt_bundle_version == "99"


def test_ensure_run_prompt_pin_present_does_not_revalidate_after_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N1 (AG3-015 R2): an existing pin is returned without lock re-validation.

    Reproduces the regression at the pin layer: after a legitimate mid-run
    ``update_binding`` (project lock points at a new version), the
    consumer-side ``ensure_run_prompt_pin_present`` must return the existing
    pin untouched -- it must NOT compare it against the current lock and trip a
    spurious ``PROMPT_RUN_PIN_MISMATCH`` (C2
    ``binding_changes_affect_only_future_runs``, FK-44 §44.3).
    """
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    first = ensure_run_prompt_pin_present(tmp_path, run_id="run-1")

    # Legitimate mid-run rebind: project lock now points at a new version.
    lock = json.loads((tmp_path / PROJECT_LOCK_RELPATH).read_text(encoding="utf-8"))
    lock["bundle_version"] = "100"
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(json.dumps(lock), encoding="utf-8")

    # No ProjectError; the existing v99 pin is returned unchanged.
    second = ensure_run_prompt_pin_present(tmp_path, run_id="run-1")
    assert second.prompt_bundle_version == "99"
    assert second.prompt_manifest_sha256 == first.prompt_manifest_sha256


def test_resolve_run_prompt_binding_rejects_pin_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Genuine pin corruption stays fail-closed (AG3-015 Entscheidung 2).

    If the run pin points at a bundle/version that no longer exists in the
    central store, resolution must fail fail-closed rather than silently
    fall back to a different bundle.
    """
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    initialize_prompt_run_pin(tmp_path, run_id="run-1")

    # Corrupt the pin: point it at a non-existent bundle version.
    pin_path = tmp_path / ".agentkit" / "manifests" / "prompt-pins" / "run-1.json"
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["prompt_bundle_version"] = "does-not-exist"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ProjectError, match="Pinned prompt bundle manifest is missing"):
        resolve_run_prompt_binding(tmp_path, "run-1")


def test_run_pin_carries_project_key_when_config_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AK7 (Review R1): PromptRunPin carries project_key from the project config.

    The formal entity ``run-prompt-pin`` includes ``project_key``; it is
    resolved from the canonical project config (no second project-key truth)
    and round-trips through write/read.
    """
    from agentkit.installer import InstallConfig, install_agentkit

    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles-store"))
    install_agentkit(
        InstallConfig(
            project_key="acme-key",
            project_name="acme",
            project_root=project_root,
            # AG3-052: scaffold default is available:true (FK-03 §3); no live
            # Sonar here => conscious opt-out so the completing CP 10d SKIPs.
            sonarqube_available=False,
        ),
    )

    pin = initialize_prompt_run_pin(project_root, run_id="run-pk")
    assert pin.project_key == "acme-key"
    reloaded = load_prompt_run_pin(project_root, "run-pk")
    assert reloaded is not None
    assert reloaded.project_key == "acme-key"


def test_run_pin_project_key_none_without_config(tmp_path: Path) -> None:
    """AK7: bare fixtures without a project config keep project_key None (fail-soft)."""
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-no-cfg",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )
    loaded = load_prompt_run_pin(tmp_path, "run-no-cfg")
    assert loaded is not None
    assert loaded.project_key is None


def test_resolve_run_prompt_binding_rejects_pin_digest_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned digest that diverges from the stored manifest is fail-closed."""
    _write_binding_lock(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    initialize_prompt_run_pin(tmp_path, run_id="run-1")

    pin_path = tmp_path / ".agentkit" / "manifests" / "prompt-pins" / "run-1.json"
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["prompt_manifest_sha256"] = "0" * 64
    pin_path.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ProjectError, match="manifest digest mismatch"):
        resolve_run_prompt_binding(tmp_path, "run-1")
