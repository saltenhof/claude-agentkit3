"""Typed models for the Layer-3 adversarial runtime (FK-48 §48.1.7 / §48.2.4).

Two schemas live here:

* :class:`SandboxResult` — what the Harness-Sub-Agent writes into the sandbox
  (``_temp/adversarial/{story_id}/{epoch}/result.json``, FK-48 §48.1.7). It is
  the ONLY artefact the sub-agent produces; the deterministic Zone-2 runtime
  reads it (the sub-agent NEVER writes ``_temp/qa/``, FK-31 §31.3).
* :class:`AdversarialResultArtifact` — the materialised ``adversarial.json``
  payload (schema_version ``3.1``, FK-48 §48.2.4) the pipeline script stamps via
  the ``ArtifactManager`` with the canonical producer/stage. It is the durable,
  ownership-clear record consumed by the integrity gate (Dim 6) and the
  remediation feedback (Layer 3 -> Layer 2).

All models are frozen Pydantic v2 (ARCH-29). Wire keys are English (ARCH-55).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Canonical schema version of the materialised ``adversarial.json`` payload.
#: FK-48 §48.2.4 bumps 3.0 -> 3.1 (additive ``mandatory_target_results``).
ADVERSARIAL_RESULT_SCHEMA_VERSION: str = "3.1"

#: Filename the Harness-Sub-Agent writes its result into, under the protected
#: sandbox ``_temp/adversarial/{story_id}/{epoch}/`` (FK-48 §48.1.7).
ADVERSARIAL_SANDBOX_RESULT_FILENAME: str = "result.json"


class SandboxTest(BaseModel):
    """A single adversarial test the sub-agent created in the sandbox (FK-48 §48.1.5).

    Attributes:
        sandbox_relpath: POSIX-relative path of the test file INSIDE the sandbox
            (e.g. ``test_wrong_phase_inv6.py``). The promotion script reads the
            file from ``{sandbox}/{sandbox_relpath}``.
        qualified_name: FULL module-qualified test name used for dedup against
            the existing ``tests/`` suite (FK-48 §48.1.5 / AC4). It is the test
            module's dotted path RELATIVE to the project ``tests/`` root plus the
            test function (``pkg.sub.test_module::test_fn``), NOT the bare file
            stem — so two same-stem tests in different packages are NOT collapsed.
            For a root-level test ``tests/test_x.py::test_a`` it is
            ``test_x::test_a``.
        outcome: Execution outcome of the test in the sandbox: ``"PASS"`` or
            ``"FAIL"`` (a FAIL is a proven finding -> quarantine, FK-48 §48.1.5).
        schema_valid: Whether the sub-agent reports the file as schema-valid
            (correct test structure / imports). The promotion script re-checks
            this deterministically; this is the sub-agent's self-report.
        target_id: Optional mandatory-target id this test addresses (``layer.check``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sandbox_relpath: str
    qualified_name: str
    outcome: str
    schema_valid: bool = True
    target_id: str | None = None


class MandatoryTargetResult(BaseModel):
    """The sub-agent's verdict on one mandatory adversarial target (FK-48 §48.2.4).

    Attributes:
        target_id: The mandatory-target id (``AdversarialTarget.finding_id`` ==
            ``layer.check``, FK-48 §48.2.5).
        status: ``"TESTED"`` (a test was written) or ``"UNRESOLVABLE"`` (the
            negative case is not testable, with a reason).
        test_file: Sandbox path of the test (when ``TESTED``), else ``None``.
        reason: Justification (mandatory when ``UNRESOLVABLE``), else ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    status: str
    test_file: str | None = None
    reason: str | None = None


class SparringProof(BaseModel):
    """Proof that the mandatory sparring call ran (FK-48 §48.1.6 / FK-11 §11.8.2).

    Recorded by the deterministic runtime from the AG3-065 transport call. It is
    mirrored into ``adversarial.json`` so the integrity gate can verify the
    sparring telemetry deterministically against the same single source of truth
    (no second telemetry-read port on the gate).

    Attributes:
        pool: The sparring pool name (FK-48 §48.1.6 ``pool`` field).
        adversarial_sparring_events: Count of emitted ``adversarial_sparring``
            domain events (FK-48 §48.1.6; >= 1 required).
        llm_call_sparring_events: Count of emitted ``llm_call`` events with
            ``role=adversarial_sparring`` (FK-11 §11.8.2; >= 1 required).
        edge_cases_received: Number of edge-case ideas the sparring LLM returned.
        edge_cases_implemented: Number of those ideas turned into tests.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pool: str
    adversarial_sparring_events: int = Field(ge=0)
    llm_call_sparring_events: int = Field(ge=0)
    edge_cases_received: int = Field(default=0, ge=0)
    edge_cases_implemented: int = Field(default=0, ge=0)


class AdversarialTelemetryCounts(BaseModel):
    """The emitted §48.1.8 adversarial-lifecycle event counts (FK-48 §48.1.8).

    Recorded by the deterministic runtime from what it ACTUALLY emitted, and
    mirrored into ``adversarial.json`` so the integrity gate (Dim 6) can verify
    the FULL FK-48 §48.1.8 expectation table against the single source of truth
    (no second telemetry-read port). The §48.1.8 expectations are:

    * ``adversarial_start`` — EXACTLY 1
    * ``adversarial_end`` — EXACTLY 1
    * ``adversarial_sparring`` — >= 1
    * ``adversarial_test_created`` — >= 0
    * ``adversarial_test_executed`` — >= 1

    Attributes:
        adversarial_start: Count of emitted ``adversarial_start`` events
            (exactly 1 expected).
        adversarial_end: Count of emitted ``adversarial_end`` events (exactly 1
            expected).
        adversarial_sparring: Count of emitted ``adversarial_sparring`` events
            (>= 1 expected).
        adversarial_test_created: Count of emitted ``adversarial_test_created``
            events (>= 0; trivially satisfied, kept for completeness/consistency).
        adversarial_test_executed: Count of emitted ``adversarial_test_executed``
            events (>= 1 expected).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    adversarial_start: int = Field(ge=0)
    adversarial_end: int = Field(ge=0)
    adversarial_sparring: int = Field(ge=0)
    adversarial_test_created: int = Field(default=0, ge=0)
    adversarial_test_executed: int = Field(ge=0)


class PromotionSummary(BaseModel):
    """Deterministic test-promotion outcome counts (FK-48 §48.1.5).

    Attributes:
        promoted_to_suite: Tests promoted into ``tests/`` (schema-valid +
            dry-run-executable + non-duplicate + test PASS).
        promoted_to_quarantine: Tests promoted into ``tests/adversarial_quarantine/``
            (same gatekeepers + test FAIL = proven finding).
        not_promoted: Tests that stayed ephemeral in the sandbox (schema-invalid
            OR dry-run-error OR duplicate).
        not_promoted_reasons: Per-test reason for staying ephemeral (ordered).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    promoted_to_suite: int = Field(default=0, ge=0)
    promoted_to_quarantine: int = Field(default=0, ge=0)
    not_promoted: int = Field(default=0, ge=0)
    not_promoted_reasons: tuple[str, ...] = ()


class SandboxResult(BaseModel):
    """The Harness-Sub-Agent's sandbox result (FK-48 §48.1.7).

    Written by the adversarial sub-agent into
    ``_temp/adversarial/{story_id}/{epoch}/result.json`` — the ONLY artefact the
    sub-agent produces (it cannot write ``_temp/qa/``, FK-31 §31.3). The
    deterministic runtime validates it against this schema and refuses to PASS
    without real evidence (>= 1 executed test, FK-48 §48.1.8).

    Attributes:
        story_id: Story display id.
        status: The sub-agent's self-reported status (``"PASS"`` /
            ``"FAIL"``). NOTE: the runtime does NOT trust this as the layer
            verdict; the verdict is derived from real evidence.
        tests_executed: Number of tests actually executed (>= 1 required, FK-48
            §48.1.8). The runtime FAILs Layer 3 when this is 0.
        tests: The created sandbox tests (may be empty when the sub-agent only
            ran the EXISTING suite).
        mandatory_target_results: Per mandatory-target verdicts (FK-48 §48.2.4).
        findings: Free-form defect descriptions (proven findings).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str
    status: str = "PASS"
    tests_executed: int = Field(default=0, ge=0)
    tests: tuple[SandboxTest, ...] = ()
    mandatory_target_results: tuple[MandatoryTargetResult, ...] = ()
    findings: tuple[str, ...] = ()


class AdversarialResultArtifact(BaseModel):
    """The materialised ``adversarial.json`` payload (schema 3.1, FK-48 §48.2.4).

    The deterministic pipeline script builds this from the validated
    :class:`SandboxResult` + the deterministic promotion/sparring outcome and
    stamps it via the ``ArtifactManager`` under the canonical producer/stage.

    Attributes:
        schema_version: Always :data:`ADVERSARIAL_RESULT_SCHEMA_VERSION` (3.1).
        story_id: Story display id.
        run_id: Run-correlation id.
        status: The DERIVED Layer-3 verdict (``"PASS"`` / ``"FAIL"``): PASS only
            with real evidence (>= 1 executed test) and no proven finding.
        tests_created: Number of sandbox tests created.
        tests_executed: Number of tests executed (>= 1 for a PASS).
        tests_passed: Number of executed tests that passed.
        tests_failed: Number of executed tests that failed (proven findings).
        sparring: The mandatory-sparring proof (FK-48 §48.1.6 / FK-11 §11.8.2).
        promotion: The deterministic promotion outcome (FK-48 §48.1.5).
        telemetry: The emitted §48.1.8 adversarial-lifecycle event counts
            (FK-48 §48.1.8). Mirrored from what the runtime actually emitted so
            the integrity gate (Dim 6) verifies the FULL §48.1.8 expectation
            table (exactly-1 start/end, >= 1 sparring/test_executed) against the
            single source of truth.
        tests: The created sandbox tests with their outcomes / target ids (the
            per-target correlation the Layer-3 -> Layer-2 feedback uses).
        mandatory_target_results: Per mandatory-target verdicts (FK-48 §48.2.4).
        findings: Proven-finding descriptions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = ADVERSARIAL_RESULT_SCHEMA_VERSION
    story_id: str
    run_id: str
    status: str
    tests_created: int = Field(ge=0)
    tests_executed: int = Field(ge=0)
    tests_passed: int = Field(ge=0)
    tests_failed: int = Field(ge=0)
    sparring: SparringProof
    promotion: PromotionSummary
    telemetry: AdversarialTelemetryCounts
    tests: tuple[SandboxTest, ...] = ()
    mandatory_target_results: tuple[MandatoryTargetResult, ...] = ()
    findings: tuple[str, ...] = ()
