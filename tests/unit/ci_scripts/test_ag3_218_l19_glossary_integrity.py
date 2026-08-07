"""Behavioural pin for the L19 glossary lint (AG3-218).

``lint_l19_glossary_integrity`` carried a cognitive complexity of 24 and was
split into a collection step plus three checks. The lint had no tests at all --
which is why the C901 could sit in it unnoticed. These tests exercise the four
checks through the public entry point and assert the exact findings AND their
order, because ``LintReport`` preserves the sequence in which findings arrive.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).parents[3]
GATE_PATH = REPO_ROOT / "scripts" / "ci" / "check_concept_frontmatter.py"


def _load_gate() -> ModuleType:
    """Import the gate script the way it is executed: as a top-level module."""
    tools_root = str(REPO_ROOT / "tools")
    if tools_root not in sys.path:
        sys.path.insert(0, tools_root)
    spec = importlib.util.spec_from_file_location(
        "ag3_218_check_concept_frontmatter", GATE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before executing: the gate defines dataclasses, and
    # ``dataclasses`` resolves annotations through ``sys.modules``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load_gate()


def _doc(cid: str, name: str, glossary: dict[str, Any] | None = None) -> Any:
    frontmatter: dict[str, Any] = {"concept_id": cid}
    if glossary is not None:
        frontmatter["glossary"] = glossary
    return GATE.Doc(layer="technical", path=Path(name), fm=frontmatter)


def _domains(contract: tuple[str, ...], member: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "bc-alpha": GATE.DomainEntry(
            id="bc-alpha", contract_docs=contract, member_docs=member
        )
    }


def _run(docs: list[Any], domains: dict[str, Any]) -> list[tuple[str, str]]:
    report = GATE.LintReport()
    GATE.lint_l19_glossary_integrity(docs, domains, report)
    return report.errors


def test_no_domain_registry_makes_the_lint_a_no_op() -> None:
    docs = [_doc("FK-01", "fk01.md", {"exported_terms": [{"id": "Term"}]})]
    assert _run(docs, {}) == []


def test_clean_corpus_produces_no_finding() -> None:
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {
                "exported_terms": [{"id": "Stage"}],
                "internal_terms": [{"id": "Scratch"}],
            },
        )
    ]
    assert _run(docs, _domains(contract=("FK-01",))) == []


def test_exported_term_without_id_is_reported() -> None:
    docs = [_doc("FK-01", "fk01.md", {"exported_terms": [{"name": "Stage"}]})]
    errors = _run(docs, _domains(contract=("FK-01",)))
    assert errors == [
        ("L19", "fk01.md: exported_terms entry without id: {'name': 'Stage'}")
    ]


def test_duplicate_exported_term_names_both_documents() -> None:
    docs = [
        _doc("FK-01", "fk01.md", {"exported_terms": [{"id": "Stage"}]}),
        _doc("FK-02", "fk02.md", {"exported_terms": [{"id": "Stage"}]}),
    ]
    errors = _run(docs, _domains(contract=("FK-01", "FK-02")))
    assert errors == [
        (
            "L19",
            "fk02.md: duplicate exported term 'Stage' in domain 'bc-alpha' "
            "(also in fk01.md)",
        )
    ]


def test_term_that_is_both_exported_and_internal_is_reported() -> None:
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {
                "exported_terms": [{"id": "Stage"}],
                "internal_terms": [{"id": "Stage"}],
            },
        )
    ]
    errors = _run(docs, _domains(contract=("FK-01",)))
    assert errors == [
        ("L19", "term 'Stage' in domain 'bc-alpha' is both exported and internal")
    ]


def test_glossary_in_a_non_contract_doc_is_reported() -> None:
    docs = [_doc("FK-02", "fk02.md", {"exported_terms": [{"id": "Stage"}]})]
    errors = _run(docs, _domains(contract=("FK-01",), member=("FK-02",)))
    assert errors == [
        (
            "L19",
            "fk02.md: glossary block lives in non-contract doc; "
            "glossaries belong in the contract doc of their domain",
        )
    ]


def test_see_also_must_be_a_mapping() -> None:
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {"exported_terms": [{"id": "Stage", "see_also": ["Worker"]}]},
        )
    ]
    errors = _run(docs, _domains(contract=("FK-01",)))
    assert errors == [("L19", "fk01.md: see_also entry must be a mapping: 'Worker'")]


def test_see_also_needs_term_and_domain() -> None:
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {"exported_terms": [{"id": "Stage", "see_also": [{"term": "Worker"}]}]},
        )
    ]
    errors = _run(docs, _domains(contract=("FK-01",)))
    assert errors == [
        (
            "L19",
            "fk01.md: see_also entry needs 'term' and 'domain' "
            "(got {'term': 'Worker'})",
        )
    ]


def test_unresolvable_cross_reference_is_reported() -> None:
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {
                "exported_terms": [
                    {
                        "id": "Stage",
                        "see_also": [{"term": "Worker", "domain": "bc-beta"}],
                    }
                ]
            },
        )
    ]
    errors = _run(docs, _domains(contract=("FK-01",)))
    assert errors == [
        (
            "L19",
            "fk01.md: glossary cross-ref bc-beta/Worker "
            "does not resolve to any exported term",
        )
    ]


def test_resolvable_cross_reference_produces_no_finding() -> None:
    domains = {
        "bc-alpha": GATE.DomainEntry(
            id="bc-alpha", contract_docs=("FK-01",), member_docs=()
        ),
        "bc-beta": GATE.DomainEntry(
            id="bc-beta", contract_docs=("FK-02",), member_docs=()
        ),
    }
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {
                "exported_terms": [
                    {
                        "id": "Stage",
                        "see_also": [{"term": "Worker", "domain": "bc-beta"}],
                    }
                ]
            },
        ),
        _doc("FK-02", "fk02.md", {"exported_terms": [{"id": "Worker"}]}),
    ]
    assert _run(docs, domains) == []


def test_findings_keep_the_collection_before_check_order() -> None:
    """Collection findings precede the checks that read the index it builds."""
    docs = [
        _doc(
            "FK-01",
            "fk01.md",
            {
                "exported_terms": [
                    {"name": "no-id"},
                    {"id": "Stage", "see_also": [{"term": "Gone", "domain": "bc-x"}]},
                ],
                "internal_terms": [{"id": "Stage"}],
            },
        ),
        _doc("FK-02", "fk02.md", {"exported_terms": [{"id": "Other"}]}),
    ]
    domains = _domains(contract=("FK-01",), member=("FK-02",))
    codes = [message for _code, message in _run(docs, domains)]
    assert codes[0].endswith("exported_terms entry without id: {'name': 'no-id'}")
    assert "both exported and internal" in codes[1]
    assert "glossary block lives in non-contract doc" in codes[2]
    assert "does not resolve to any exported term" in codes[3]
    assert len(codes) == 4


def test_policy_registry_only_keeps_string_ids() -> None:
    """The set comprehension that mypy flagged kept its filtering semantics."""
    registry = GATE.POLICY_REGISTRY_PATH
    if not registry.is_file():
        return
    ids = GATE.load_policy_registry()
    assert all(isinstance(item, str) for item in ids)
