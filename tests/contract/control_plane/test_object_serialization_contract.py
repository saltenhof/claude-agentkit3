"""Contract pins for AG3-141 object-mutation serialization.

Four contract concerns are pinned here (no database; pure wire-form / spec-text
/ source pins):

* AC9/AC10 -- run-phase and resume are "object-serialized" per
  ``formal.story-workflow.commands``; the exact serialization wording the
  runtime implements must not silently drift out of the formal spec.
* AC6 / K4 / IMPL-016 -- a busy-object rejection maps to HTTP ``409 CONFLICT``
  plus a ``Retry-After`` header carrying the pinned budget: the wire form of
  the deterministic wait contract (FK-91 §91.1a Rule 8 -- a stable
  ``error_code`` plus structured detail that only extends the contract).
* AC8 / SOLL-053/055 -- the single-transaction exception boundary: the
  ``project_mode_lock`` and story-number allocation paths stay
  ``pg_advisory_xact_lock`` / ``FOR UPDATE`` based and never migrate onto the
  durable ``object_mutation_claims`` acquire.
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane import object_claims as oc
from agentkit.backend.control_plane.runtime import _object_claim_busy_rejection
from agentkit.backend.control_plane_http.app import _mutation_result_response

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import ControlPlaneMutationResult

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMANDS = _REPO_ROOT / "concept" / "formal-spec" / "story-workflow" / "commands.md"
_STORE = _REPO_ROOT / "src" / "agentkit" / "backend" / "state_backend" / "store"


# ---------------------------------------------------------------------------
# AC9/AC10 -- formal.story-workflow.commands "object-serialized" wording
# ---------------------------------------------------------------------------


def test_run_phase_command_is_object_serialized_in_formal_spec() -> None:
    """The run-phase command's serialization clause is pinned verbatim.

    SOLL-056/057 (serialization part): mutations serialize per declared
    serialization object in ADDITION to op_id idempotency.
    """
    text = _COMMANDS.read_text(encoding="utf-8")
    assert "object-serialized" in text
    assert (
        "mutations additionally serialize per declared serialization object, "
        "default (project_key, story_id)"
    ) in text


def test_resume_command_is_object_serialized_in_formal_spec() -> None:
    text = _COMMANDS.read_text(encoding="utf-8")
    assert (
        "reserved by the SAME in-flight operation claim "
        "(instance-bound, object-serialized)"
    ) in text


# ---------------------------------------------------------------------------
# AC6 / K4 -- busy-object -> 409 + Retry-After wire form
# ---------------------------------------------------------------------------


def _busy_rejection() -> ControlPlaneMutationResult:
    """The productive busy-object rejection (the exact runtime helper output)."""
    conflict = oc.ObjectClaimConflict(key=oc.story_claim_key("tenant-a", "AG3-100"))
    return _object_claim_busy_rejection(
        op_id="op-1",
        operation_kind="phase_start",
        run_id="run-1",
        phase="setup",
        conflict=conflict,
    )


def test_busy_object_rejection_maps_to_409_with_retry_after_header() -> None:
    response = _mutation_result_response(_busy_rejection(), correlation_id="corr-1")

    assert response.status_code == int(HTTPStatus.CONFLICT)
    assert (
        "Retry-After",
        str(oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS),
    ) in response.headers
    body = json.loads(response.body)
    assert body["status"] == "rejected"
    assert body["error_code"] == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    assert body["retry_after_seconds"] == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS


def test_retry_after_budget_is_pinned_well_below_the_frontend_timeout() -> None:
    """K4: the pinned client retry hint must be a positive budget far under the
    12s frontend ``AbortController`` timeout (never a server-side blocking wait).
    """
    assert 0 < oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS < 12


def test_non_busy_rejection_carries_no_retry_after_header() -> None:
    """Every OTHER rejection cause still maps to 409 but must NOT grow a
    ``Retry-After`` header (unchanged behaviour; the header is exclusive to the
    busy-object wait contract).
    """
    plain = _busy_rejection().model_copy(
        update={"error_code": None, "retry_after_seconds": None}
    )
    response = _mutation_result_response(plain, correlation_id="corr-2")

    assert response.status_code == int(HTTPStatus.CONFLICT)
    assert all(name != "Retry-After" for name, _ in response.headers)


# ---------------------------------------------------------------------------
# AC8 / SOLL-053/055 -- single-transaction exception boundary pin
# ---------------------------------------------------------------------------


def test_mode_lock_stays_xact_based_and_never_acquires_an_object_claim() -> None:
    """The ``project_mode_lock`` path is a fully-in-one-transaction mutation, so
    it serialises with ``pg_advisory_xact_lock`` and must NEVER take the durable
    object-mutation claim (FK-10 §10.5.4 single-TX exception).
    """
    text = (_STORE / "mode_lock_repository.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in text
    assert "acquire_object_mutation_claim" not in text
    assert "import object_claims" not in text


def test_story_number_allocation_stays_for_update_based() -> None:
    text = (_STORE / "story_repository.py").read_text(encoding="utf-8")
    assert "FOR UPDATE" in text
    assert "acquire_object_mutation_claim" not in text
    assert "import object_claims" not in text


# ---------------------------------------------------------------------------
# ARCH-55 regression pin (Codex R2 MAJOR): the AG3-141 NEW .py files are
# English-only. ARCH-55 is as binding as the Sonar rules -- source
# comments/identifiers/wire-keys must be English. This greps the AG3-141 new
# source/tests for a German blocklist so German cannot silently re-enter.
# ---------------------------------------------------------------------------

_AG3_141_NEW_FILES = (
    "src/agentkit/backend/control_plane/object_claims.py",
    "tests/unit/control_plane/test_object_claims.py",
    "tests/unit/control_plane/test_object_claim_wiring.py",
    "tests/integration/control_plane/test_object_mutation_serialization_pg.py",
    "tests/contract/control_plane/test_object_serialization_contract.py",
)

#: German blocklist for the AG3-141 new files. Discrete German nouns use word
#: boundaries; lowercase participles/adjectives and any umlaut match directly.
_AG3_141_GERMAN_BLOCKLIST = re.compile(
    r"\b(?:Regel|Befund|Fehler|Vertrag|Auflage|Pflicht|Abweichung|Sperre"
    r"|Nachweis|Mutationen|Wahrheit|Serialisierung|Deklaration|Erwerbsordnung)\b"
    r"|projektweit|gemintet|beigestellt|[äöüß]"
)


def test_no_german_in_ag3141_new_source_and_tests() -> None:
    """ARCH-55: zero German blocklist words in the AG3-141 new .py files."""
    root = Path(__file__).resolve().parents[3]
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for rel in _AG3_141_NEW_FILES:
        path = root / rel
        if path.resolve() == this_file:
            #: This pin file legitimately DEFINES the German blocklist -- skip it.
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _AG3_141_GERMAN_BLOCKLIST.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:80]}")

    assert not offenders, (
        "German re-entered an AG3-141 new file (ARCH-55, English-only source):\n"
        + "\n".join(offenders)
    )
