"""Contract tests freezing the prompt-runtime schemas (AG3-015 AK5, AK7).

Pins:
- ``PromptAuditHash`` field set (FK-44 §44.6 /
  formal.prompt-runtime.entities ``prompt-instance`` digest attributes).
- ``PromptRunPin`` field set incl. ``pinned_at`` (FK-44 §44.3 /
  formal.prompt-runtime.entities ``run-prompt-pin``).
- ``ArtifactClass.PROMPT_AUDIT`` wire value (Entscheidung 1).

Any drift in these schemas is a concept break and must be addressed
explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.prompt_runtime.audit import PromptAuditHash, compute_prompt_audit_hash
from agentkit.backend.prompt_runtime.pins import PromptRunPin


def test_prompt_audit_hash_field_set() -> None:
    """FK-44 §44.6: exactly template_sha256, render_input_digest, output_sha256."""
    assert set(PromptAuditHash.model_fields) == {
        "template_sha256",
        "render_input_digest",
        "output_sha256",
    }


def test_prompt_audit_hash_is_frozen_and_extra_forbid() -> None:
    config = PromptAuditHash.model_config
    assert config.get("frozen") is True
    assert config.get("extra") == "forbid"


def test_prompt_audit_hash_deterministic_same_input() -> None:
    a = compute_prompt_audit_hash(
        template_text="x", render_inputs={"k": "v"}, output_text="y"
    )
    b = compute_prompt_audit_hash(
        template_text="x", render_inputs={"k": "v"}, output_text="y"
    )
    assert a == b


def test_run_prompt_pin_field_set_includes_pinned_at() -> None:
    """formal.prompt-runtime.entities run-prompt-pin: incl. pinned_at."""
    fields = set(PromptRunPin.model_fields)
    assert "run_id" in fields
    assert "prompt_bundle_version" in fields
    assert "prompt_manifest_sha256" in fields
    assert "pinned_at" in fields


def test_run_prompt_pin_formal_aliases() -> None:
    pin = PromptRunPin(
        run_id="run-1",
        prompt_bundle_id="b",
        prompt_bundle_version="9",
        prompt_manifest_sha256="d" * 64,
        pinned_at=datetime.now(tz=UTC),
    )
    assert pin.resolved_prompt_bundle_version == "9"
    assert pin.resolved_prompt_bundle_manifest_digest == "d" * 64


def test_prompt_audit_artifact_class_wire_value() -> None:
    """Entscheidung 1: ArtifactClass.PROMPT_AUDIT wire value is 'prompt_audit'."""
    assert ArtifactClass.PROMPT_AUDIT.value == "prompt_audit"
    assert ArtifactClass("prompt_audit") is ArtifactClass.PROMPT_AUDIT
