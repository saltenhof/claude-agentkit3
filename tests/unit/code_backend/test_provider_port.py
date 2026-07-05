"""Unit tests for the AG3-146 code-backend capability port and result types.

Exercises the Protocol/capability model/result-form shapes over ports and
fakes only (no adapter, no subprocess) -- the A-core stays AT-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CodeBackendPort,
    CompareEvidenceResult,
    RefReadResult,
    RepoProbeResult,
)


def test_capability_codes_are_english_stable_wire_identifiers() -> None:
    """ARCH-55: capability codes are English, stable wire identifiers."""
    assert CodeBackendCapability.REPO_PROBE == "repo_probe"
    assert CodeBackendCapability.REF_READ == "ref_read"
    assert CodeBackendCapability.COMPARE_EVIDENCE == "compare_evidence"
    assert (
        CodeBackendCapability.REF_PROTECTION_ADMINISTRATION
        == "ref_protection_administration"
    )


def test_capability_set_is_minimal_and_exhaustive() -> None:
    """AC1: exactly the four minimal declared capabilities -- no more, no fewer."""
    assert {c.value for c in CodeBackendCapability} == {
        "repo_probe",
        "ref_read",
        "compare_evidence",
        "ref_protection_administration",
    }


def test_repo_probe_result_is_frozen_and_typed() -> None:
    result = RepoProbeResult(reachable=True, detail="ok")
    assert result.reachable is True
    assert result.detail == "ok"


def test_ref_read_result_typed_failure_carries_no_head_sha() -> None:
    """AC2: a non-resolvable ref is a typed result, never a fabricated success."""
    result = RefReadResult(ref="main", resolved=False, head_sha=None, detail="not found")
    assert result.resolved is False
    assert result.head_sha is None
    assert result.ref == "main"


def test_ref_read_result_typed_success_carries_head_sha() -> None:
    result = RefReadResult(ref="main", resolved=True, head_sha="deadbeef", detail="ok")
    assert result.resolved is True
    assert result.head_sha == "deadbeef"


def test_compare_evidence_result_defaults_are_declared_only() -> None:
    result = CompareEvidenceResult(base_ref="main", head_ref="story/x", available=False)
    assert result.changed_paths == ()
    assert result.detail == ""
    assert result.available is False


@dataclass(frozen=True)
class _FakeCodeBackendPort:
    """A minimal, fully in-memory ``CodeBackendPort`` fake for A-core unit tests."""

    reachable: bool = True
    head_shas: dict[str, str] = field(default_factory=dict)
    supported: frozenset[CodeBackendCapability] = field(
        default_factory=lambda: frozenset(
            {CodeBackendCapability.REPO_PROBE, CodeBackendCapability.REF_READ}
        )
    )

    def repo_probe(self) -> RepoProbeResult:
        return RepoProbeResult(reachable=self.reachable, detail="fake probe")

    def ref_read(self, ref: str) -> RefReadResult:
        sha = self.head_shas.get(ref)
        if sha is None:
            return RefReadResult(
                ref=ref, resolved=False, head_sha=None, detail="unresolvable"
            )
        return RefReadResult(ref=ref, resolved=True, head_sha=sha, detail="resolved")

    def read_compare_evidence(
        self, base_ref: str, head_ref: str
    ) -> CompareEvidenceResult:
        return CompareEvidenceResult(base_ref=base_ref, head_ref=head_ref, available=False)

    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        return capability in self.supported


def test_fake_port_satisfies_runtime_checkable_protocol() -> None:
    fake = _FakeCodeBackendPort()
    assert isinstance(fake, CodeBackendPort)


def test_fake_port_ref_read_roundtrip() -> None:
    fake = _FakeCodeBackendPort(head_shas={"main": "deadbeef"})
    assert fake.ref_read("main").head_sha == "deadbeef"
    assert fake.ref_read("missing").resolved is False


def test_fake_port_capability_supported_reflects_wiring() -> None:
    fake = _FakeCodeBackendPort(supported=frozenset({CodeBackendCapability.REF_READ}))
    assert fake.capability_supported(CodeBackendCapability.REF_READ) is True
    assert fake.capability_supported(CodeBackendCapability.REPO_PROBE) is False
    assert (
        fake.capability_supported(CodeBackendCapability.REF_PROTECTION_ADMINISTRATION)
        is False
    )
