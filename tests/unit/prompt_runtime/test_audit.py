"""Tests for PromptAuditHash determinism and ArtifactManager persistence.

AG3-015 AK5 (PromptAuditHash typed + deterministic) and AK2/AK5b
(audit persistence via ArtifactManager, artifact_class=PROMPT_AUDIT).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import (
    ArtifactManager,
    EnvelopeValidator,
    ProducerRegistry,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.prompt_runtime.audit import (
    PROMPT_AUDIT_PRODUCER_NAME,
    PromptAuditHash,
    build_prompt_audit_envelope,
    compute_prompt_audit_hash,
    persist_prompt_audit,
)
from agentkit.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def artifact_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ArtifactManager:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    registry = ProducerRegistry()
    register_prompt_runtime_producers(registry)
    repository = StateBackendArtifactRepository(store_dir=tmp_path)
    validator = EnvelopeValidator(registry)
    return ArtifactManager(repository=repository, validator=validator)


class TestPromptAuditHashDeterminism:
    def test_same_input_same_hash(self) -> None:
        a = compute_prompt_audit_hash(
            template_text="# T {x}",
            render_inputs={"x": "1", "y": "2"},
            output_text="# T 1",
        )
        b = compute_prompt_audit_hash(
            template_text="# T {x}",
            render_inputs={"y": "2", "x": "1"},  # different key order
            output_text="# T 1",
        )
        assert a == b
        assert len(a.template_sha256) == 64
        assert len(a.render_input_digest) == 64
        assert len(a.output_sha256) == 64

    def test_different_output_different_hash(self) -> None:
        a = compute_prompt_audit_hash(
            template_text="# T",
            render_inputs={},
            output_text="one",
        )
        b = compute_prompt_audit_hash(
            template_text="# T",
            render_inputs={},
            output_text="two",
        )
        assert a.output_sha256 != b.output_sha256

    def test_model_is_frozen(self) -> None:
        h = PromptAuditHash(
            template_sha256="a" * 64,
            render_input_digest="b" * 64,
            output_sha256="c" * 64,
        )
        with pytest.raises(Exception):  # noqa: B017,PT011 (pydantic ValidationError)
            h.template_sha256 = "x"  # type: ignore[misc]


class TestPromptAuditPersistence:
    def _hash(self) -> PromptAuditHash:
        return compute_prompt_audit_hash(
            template_text="# Template {story_id}",
            render_inputs={"story_id": "AG3-015"},
            output_text="# Template AG3-015",
        )

    def test_persist_via_manager_roundtrip(
        self, artifact_manager: ArtifactManager
    ) -> None:
        audit_hash = self._hash()
        envelope = build_prompt_audit_envelope(
            story_id="AG3-015",
            run_id="run-audit-1",
            invocation_id="inv-1",
            attempt=1,
            logical_prompt_id="prompt.worker-implementation",
            template_relpath="internal/prompts/worker-implementation.md",
            prompt_bundle_version="2",
            prompt_bundle_manifest_digest="d" * 64,
            render_mode="rendered",
            audit_hash=audit_hash,
            artifact_path=".agentkit/prompts/run-audit-1/inv-1/prompt.md",
        )
        assert envelope.artifact_class is ArtifactClass.PROMPT_AUDIT
        assert envelope.producer.name == PROMPT_AUDIT_PRODUCER_NAME
        assert envelope.status is EnvelopeStatus.PASS

        reference = persist_prompt_audit(artifact_manager, envelope)
        assert reference.artifact_class is ArtifactClass.PROMPT_AUDIT

        loaded = artifact_manager.read(reference)
        assert loaded.payload is not None
        assert loaded.payload["template_sha256"] == audit_hash.template_sha256
        assert loaded.payload["output_sha256"] == audit_hash.output_sha256
        assert loaded.payload["render_mode"] == "rendered"
        assert loaded.payload["artifact_path"] == (
            ".agentkit/prompts/run-audit-1/inv-1/prompt.md"
        )

    def test_unregistered_producer_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A prompt-audit envelope without the registered producer fails closed."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        empty_registry = ProducerRegistry()  # producer NOT registered
        repository = StateBackendArtifactRepository(store_dir=tmp_path)
        manager = ArtifactManager(
            repository=repository,
            validator=EnvelopeValidator(empty_registry),
        )
        envelope = build_prompt_audit_envelope(
            story_id="AG3-015",
            run_id="run-audit-2",
            invocation_id="inv-1",
            attempt=1,
            logical_prompt_id="prompt.worker-implementation",
            template_relpath="internal/prompts/worker-implementation.md",
            prompt_bundle_version="2",
            prompt_bundle_manifest_digest="d" * 64,
            render_mode="rendered",
            audit_hash=self._hash(),
            artifact_path=".agentkit/prompts/run-audit-2/inv-1/prompt.md",
        )
        from agentkit.artifacts import ProducerNotRegisteredError

        with pytest.raises(ProducerNotRegisteredError):
            persist_prompt_audit(manager, envelope)
