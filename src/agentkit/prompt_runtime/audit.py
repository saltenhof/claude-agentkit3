"""Prompt-audit schema and audit-record persistence (FK-44 §44.6).

Owner: ``materialization`` sub of the prompt-runtime BC (bc-cut-decisions
§BC 10). Defines the typed ``PromptAuditHash`` schema and builds the
``ArtifactEnvelope`` that is persisted via ``artifacts.ArtifactManager``
(the only admissible audit persistence layer; loose JSON files are not
the audit truth, FK-44 §44.6, FK-71).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.artifacts import (
    ArtifactEnvelope,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from agentkit.artifacts import ArtifactManager, ArtifactReference

#: Canonical producer name for prompt-runtime audit records (registered in
#: ``agentkit.prompt_runtime.register``).
PROMPT_AUDIT_PRODUCER_NAME = "prompt-runtime.materialization"

#: Stage id used for prompt-audit envelopes (matches the envelope
#: ``_STAGE_ID_PATTERN`` -- lowercase kebab).
PROMPT_AUDIT_STAGE = "prompt-materialization"


class PromptAuditHash(BaseModel):
    """Digest triple proving exact template and output bytes (FK-44 §44.6).

    Maps to the digest attributes of the formal entity
    ``prompt-runtime.entity.prompt-instance``.

    Attributes:
        template_sha256: Digest of the canonical template bytes.
        render_input_digest: Digest of the render inputs (placeholder map);
            for static prompts this equals the template digest path's empty
            render-input digest computed by the caller.
        output_sha256: Digest of the final materialized prompt bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    template_sha256: str
    render_input_digest: str
    output_sha256: str


def empty_render_input_digest() -> str:
    """Return the digest of an empty render-input map (static prompts).

    Static projections do no rendering; their ``render_input_digest`` is the
    canonical digest of an empty placeholder map. Kept here as the single
    source of truth so static and dynamic paths agree on the empty-map digest.
    """
    return hashlib.sha256(
        json.dumps({}, sort_keys=True).encode("utf-8"),
    ).hexdigest()


def compute_prompt_audit_hash(
    *,
    template_text: str,
    render_inputs: dict[str, str],
    output_text: str,
) -> PromptAuditHash:
    """Compute the deterministic ``PromptAuditHash`` for a prompt usage.

    Determinism: identical ``template_text`` / ``render_inputs`` /
    ``output_text`` always yield identical digests. ``render_inputs`` is
    serialized with sorted keys so ordering does not affect the digest.

    Args:
        template_text: Canonical template bytes (as text).
        render_inputs: Render input map (placeholders); empty for static.
        output_text: Final materialized prompt bytes (as text).

    Returns:
        A frozen ``PromptAuditHash``.
    """
    template_sha256 = hashlib.sha256(template_text.encode("utf-8")).hexdigest()
    render_input_digest = hashlib.sha256(
        json.dumps(render_inputs, sort_keys=True).encode("utf-8"),
    ).hexdigest()
    output_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    return PromptAuditHash(
        template_sha256=template_sha256,
        render_input_digest=render_input_digest,
        output_sha256=output_sha256,
    )


def build_prompt_audit_envelope(
    *,
    story_id: str,
    run_id: str,
    invocation_id: str,
    attempt: int,
    logical_prompt_id: str,
    template_relpath: str,
    prompt_bundle_version: str,
    prompt_bundle_manifest_digest: str,
    render_mode: str,
    audit_hash: PromptAuditHash,
    artifact_path: str,
    occurred_at: datetime | None = None,
) -> ArtifactEnvelope:
    """Build the typed prompt-audit ``ArtifactEnvelope`` (FK-44 §44.6).

    The envelope carries the full minimal audit proof from FK-44 §44.6 in
    its payload, plus the ``PromptAuditHash`` digests. ``artifact_class``
    is ``PROMPT_AUDIT`` and the producer is the deterministic
    materialization producer.

    Args:
        story_id: Story display id.
        run_id: Run correlation id.
        invocation_id: Spawn/invocation id.
        attempt: Attempt counter (>= 1).
        logical_prompt_id: Logical prompt id (``prompt.<template>``).
        template_relpath: Bundle-relative template path.
        prompt_bundle_version: Pinned bundle version.
        prompt_bundle_manifest_digest: Pinned manifest digest.
        render_mode: ``"static"`` or ``"rendered"``.
        audit_hash: The computed digest triple.
        artifact_path: Project-relative path of the materialized file.
        occurred_at: Optional timestamp; defaults to ``now(UTC)``.

    Returns:
        A validated ``ArtifactEnvelope`` ready for ``ArtifactManager.write``.
    """
    timestamp = occurred_at or datetime.now(tz=UTC)
    payload: dict[str, object] = {
        "run_id": run_id,
        "invocation_id": invocation_id,
        "prompt_instance_id": invocation_id,
        "logical_prompt_id": logical_prompt_id,
        "template_relpath": template_relpath,
        "prompt_bundle_version": prompt_bundle_version,
        "prompt_bundle_manifest_digest": prompt_bundle_manifest_digest,
        "render_mode": render_mode,
        "template_sha256": audit_hash.template_sha256,
        "render_input_digest": audit_hash.render_input_digest,
        "output_sha256": audit_hash.output_sha256,
        "artifact_path": artifact_path,
    }
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=PROMPT_AUDIT_STAGE,
        attempt=attempt,
        producer=Producer(
            type=ProducerType.DETERMINISTIC,
            name=PROMPT_AUDIT_PRODUCER_NAME,
            id=ProducerId(f"{run_id}:{invocation_id}"),
            version=prompt_bundle_version,
        ),
        started_at=timestamp,
        finished_at=timestamp,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.PROMPT_AUDIT,
        payload=payload,
    )


def persist_prompt_audit(
    manager: ArtifactManager,
    envelope: ArtifactEnvelope,
) -> ArtifactReference:
    """Persist a prompt-audit envelope via the ArtifactManager.

    FK-44 §44.6: the ``ArtifactManager`` is the only admissible audit
    persistence layer; it assigns the authoritative artifact id.

    Args:
        manager: Injected ``ArtifactManager``.
        envelope: The prompt-audit envelope.

    Returns:
        The opaque ``ArtifactReference`` for the persisted record.
    """
    return manager.write(envelope)


__all__ = [
    "PROMPT_AUDIT_PRODUCER_NAME",
    "PROMPT_AUDIT_STAGE",
    "PromptAuditHash",
    "build_prompt_audit_envelope",
    "compute_prompt_audit_hash",
    "empty_render_input_digest",
    "persist_prompt_audit",
]
