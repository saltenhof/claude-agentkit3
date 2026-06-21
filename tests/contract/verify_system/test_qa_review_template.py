"""Contract test pinning the Layer-2 check-lists against the CONCEPT SSOT.

AG3-043 AK3 / W7: the ``qa-review.md`` template AND the evaluator whitelist must
match the canonical FK-27 §27.5.2 12-check list (and the single semantic /
doc-fidelity checks from FK-34 §34.2.3/§34.2.4). The expected ids are pinned
against a literal transcription of the CONCEPT source (FK-27 §27.5.2), NOT the
implementation constant -- so a drift in EITHER the template OR the impl
constant ``QA_REVIEW_CHECK_IDS`` is caught (rubric §7: pin against the SSOT
quelle, not an impl-constant duplicate). The concept literal is the single point
of truth in this test; both the template and the constant are asserted equal to
it.
"""

from __future__ import annotations

import re

import pytest

from agentkit.backend.prompt_runtime.resources import load_prompt_template
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    DOC_FIDELITY_CHECK_IDS,
    QA_REVIEW_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
)

# --- CONCEPT SSOT (transcribed verbatim from the concept docs) --------------
# FK-27 §27.5.2 "QA-Bewertung (12 Checks)" -- the canonical 12 qa_review
# check-ids (FK-05-168 bis FK-05-179), in concept order.
_FK27_QA_REVIEW_CHECK_IDS: frozenset[str] = frozenset({
    "ac_fulfilled",
    "impl_fidelity",
    "scope_compliance",
    "impact_violation",
    "arch_conformity",
    "proportionality",
    "error_handling",
    "authz_logic",
    "silent_data_loss",
    "backward_compat",
    "observability",
    "doc_impact",
})
# FK-27 §27.5.3 / FK-34 §34.2.3 -- the single semantic_review check.
_FK34_SEMANTIC_REVIEW_CHECK_ID = "systemic_adequacy"
# FK-34 §34.2.4 -- the single doc_fidelity check.
_FK34_DOC_FIDELITY_CHECK_ID = "impl_fidelity"


@pytest.mark.contract
def test_impl_qa_check_ids_match_concept_ssot() -> None:
    """The evaluator whitelist matches the FK-27 §27.5.2 concept list exactly."""
    assert QA_REVIEW_CHECK_IDS == _FK27_QA_REVIEW_CHECK_IDS
    assert sorted(SEMANTIC_REVIEW_CHECK_IDS) == [_FK34_SEMANTIC_REVIEW_CHECK_ID]
    assert sorted(DOC_FIDELITY_CHECK_IDS) == [_FK34_DOC_FIDELITY_CHECK_ID]


@pytest.mark.contract
def test_qa_review_template_check_ids_match_concept_ssot() -> None:
    """The qa-review.md template enumerates exactly the FK-27 §27.5.2 ids."""
    template = load_prompt_template("qa-review")
    expected_count = 12
    assert len(_FK27_QA_REVIEW_CHECK_IDS) == expected_count
    for check_id in _FK27_QA_REVIEW_CHECK_IDS:
        assert check_id in template, (
            f"qa-review.md is missing canonical check_id {check_id!r} "
            "(FK-27 §27.5.2)"
        )
    # No check-id outside the concept list may appear as a literal JSON check_id.
    found = set(re.findall(r'"check_id":\s*"([a-z_]+)"', template))
    assert found == _FK27_QA_REVIEW_CHECK_IDS, (
        f"qa-review.md check_ids {sorted(found)} drift from FK-27 §27.5.2 SSOT "
        f"{sorted(_FK27_QA_REVIEW_CHECK_IDS)}"
    )


@pytest.mark.contract
def test_semantic_review_template_pins_single_concept_check() -> None:
    template = load_prompt_template("qa-semantic-review")
    found = set(re.findall(r'"check_id":\s*"([a-z_]+)"', template))
    assert found == {_FK34_SEMANTIC_REVIEW_CHECK_ID}
    assert _FK34_SEMANTIC_REVIEW_CHECK_ID in template


@pytest.mark.contract
def test_doc_fidelity_template_pins_single_concept_check() -> None:
    template = load_prompt_template("qa-doc-fidelity")
    found = set(re.findall(r'"check_id":\s*"([a-z_]+)"', template))
    assert found == {_FK34_DOC_FIDELITY_CHECK_ID}
    assert _FK34_DOC_FIDELITY_CHECK_ID in template
