"""Unit tests for the SMY subset parser."""

# ruff: noqa: E501 -- the FK-78 frontmatter fixture below is a verbatim copy of the
# real corpus document; its long reason lines must stay byte-identical.

from __future__ import annotations

import pytest
from concept_toolchain.smy import SmyError, parse_smy

#: Verbatim frontmatter payload of concept/technical-design/78_concept_incubation_process.md.
FK78_FRONTMATTER = """\
concept_id: FK-78
title: Concept-Incubation — Blueprint, Inkubator-Prozess, Promotion und Toolchain
module: concept-incubation
domain: concept-incubation
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: concept-incubation-technical
  - scope: incubator-artifact-schemas
  - scope: promotion-closure
  - scope: projection-manifest-format
  - scope: concept-toolchain
defers_to:
  - target: DK-16
    scope: conception-process
    reason: Fachliche Prozessidee, Rollenmodell und Blueprint-Motivation liegen im Domaenenkonzept; FK-78 normiert die technische Realisierung
  - target: FK-23
    scope: exploration-mode
    reason: Storylokale Modusermittlung und Change-Frames bleiben bei exploration-and-design; FK-78 besitzt nur die corpus-weite Konzept-Evolution
  - target: FK-25
    scope: fine-design
    reason: Storylokales Feindesign bleibt bei exploration-and-design
  - target: FK-43
    scope: skills
    reason: Skill-Format, Bundles, Versionierung und Bindung liegen bei agent-skills; FK-78 definiert nur den Skill-INHALT der Konzeptions-Skills
  - target: FK-76
    scope: harness-integration
    reason: Harness-Adapter, Settings und Spawn-Mechanik liegen bei harness-integration; FK-78 referenziert sie nur
  - target: FK-30
    scope: hook-definition-and-enforcement
    reason: FK-78 definiert die Inkubator-Principal-/Pfadklassen-REGELN; Guard-Definition und Enforcement-Verhalten bleiben bei governance-and-guards
  - target: FK-50
    scope: installer-orchestration
    reason: Installation und Bindung der Toolchain-/Skill-Assets orchestriert der Installer
supersedes: []
superseded_by:
tags: [concept-incubation, conception, council, promotion, blueprint, toolchain, skills]
applies_policies: [policy.concept-consistency-governance, policy.assertion-authority, policy.fail-closed, policy.zero-debt]
prose_anchor_policy: strict
formal_refs:
  - formal.concept-incubation.entities
  - formal.concept-incubation.state-machine
  - formal.concept-incubation.commands
  - formal.concept-incubation.events
  - formal.concept-incubation.invariants
  - formal.concept-incubation.scenarios
glossary:
  exported_terms:
    - id: incubation-run
      definition: >
        Ein abgeschlossener Arbeitsvorgang im Concept-Incubator mit
        stabiler run_id, eigenem Zustandsdokument (RUN.json), Baseline,
        Teilnehmern, Runden, Synthese- und Promotionsakten. Der Lauf ist
        die Einheit von Nachvollziehbarkeit, Locking und Closure.
    - id: concept-toolchain
      definition: >
        Deploybares, stdlib-only Zielprojekt-Tooling
        (tools/agentkit/concept_toolchain/) mit den generischen
        Konzept-Gates, Inkubator-/Promotions-Checks und
        Semantik-Gate-Mechanik. Single Source of Truth der generischen
        Gate-Implementierung.
  internal_terms:
    - id: smy-parser
      reason: >
        Implementierungsdetail der Toolchain (YAML-Subset-Parser);
        Konsumenten nutzen die CLI, nicht den Parser.
"""


class TestRealFrontmatter:
    def test_parses_fk78_frontmatter(self) -> None:
        parsed = parse_smy(FK78_FRONTMATTER)
        assert parsed["concept_id"] == "FK-78"
        assert parsed["parent_concept_id"] is None
        assert parsed["superseded_by"] is None
        assert parsed["supersedes"] == []
        assert parsed["status"] == "active"

    def test_block_sequences_of_mappings(self) -> None:
        parsed = parse_smy(FK78_FRONTMATTER)
        defers = parsed["defers_to"]
        assert isinstance(defers, list)
        assert len(defers) == 7
        first = defers[0]
        assert isinstance(first, dict)
        assert first["target"] == "DK-16"
        assert first["scope"] == "conception-process"
        assert isinstance(first["reason"], str) and "Blueprint-Motivation" in first["reason"]

    def test_flow_lists(self) -> None:
        parsed = parse_smy(FK78_FRONTMATTER)
        assert parsed["tags"] == [
            "concept-incubation",
            "conception",
            "council",
            "promotion",
            "blueprint",
            "toolchain",
            "skills",
        ]
        authority = parsed["authority_over"]
        assert isinstance(authority, list)
        assert {"scope": "concept-toolchain"} in authority

    def test_folded_scalars_in_nested_glossary(self) -> None:
        parsed = parse_smy(FK78_FRONTMATTER)
        glossary = parsed["glossary"]
        assert isinstance(glossary, dict)
        exported = glossary["exported_terms"]
        assert isinstance(exported, list)
        toolchain_term = next(term for term in exported if isinstance(term, dict) and term["id"] == "concept-toolchain")
        definition = toolchain_term["definition"]
        assert isinstance(definition, str)
        assert definition.startswith("Deploybares, stdlib-only Zielprojekt-Tooling")
        assert definition.endswith("Gate-Implementierung.\n")


class TestScalars:
    def test_folded_clip_keeps_trailing_newline(self) -> None:
        parsed = parse_smy("text: >\n  first line\n  second line\n")
        assert parsed["text"] == "first line second line\n"

    def test_folded_strip_removes_trailing_newline(self) -> None:
        parsed = parse_smy("text: >-\n  first line\n  second line\n")
        assert parsed["text"] == "first line second line"

    def test_folded_blank_line_becomes_paragraph_break(self) -> None:
        parsed = parse_smy("text: >-\n  one\n\n  two\n")
        assert parsed["text"] == "one\ntwo"

    def test_quoted_scalars(self) -> None:
        parsed = parse_smy("single: 'a: b'\ndouble: \"x \\\" y\"\n")
        assert parsed["single"] == "a: b"
        assert parsed["double"] == 'x " y'

    def test_type_conversion_is_limited_to_bool_and_int(self) -> None:
        parsed = parse_smy("flag: true\nother: false\ncount: 42\nnegative: -7\nversion: 1.0.0\nword: null\n")
        assert parsed["flag"] is True
        assert parsed["other"] is False
        assert parsed["count"] == 42
        assert parsed["negative"] == -7
        assert parsed["version"] == "1.0.0"
        assert parsed["word"] == "null"

    def test_comments_and_empty_values(self) -> None:
        parsed = parse_smy("# leading comment\nkey: value # trailing comment\nempty:\n")
        assert parsed == {"key": "value", "empty": None}

    def test_multiline_plain_scalar_folds(self) -> None:
        parsed = parse_smy("reason: first part\n  second part\nnext: 1\n")
        assert parsed["reason"] == "first part second part"
        assert parsed["next"] == 1

    def test_multiline_flow_list(self) -> None:
        parsed = parse_smy("values: [a, b,\n         c]\n")
        assert parsed["values"] == ["a", "b", "c"]

    def test_sequence_scalar_items_with_continuation(self) -> None:
        parsed = parse_smy("notes:\n  - first item continues\n    on the next line\n  - second\n")
        assert parsed["notes"] == ["first item continues on the next line", "second"]


class TestUnsupportedConstructs:
    @pytest.mark.parametrize(
        ("text", "line", "fragment"),
        [
            ("key: &anchor value\n", 1, "anchors"),
            ("first: ok\nkey: *alias\n", 2, "aliases"),
            ("key: !!str value\n", 1, "tags"),
            ("key: ok\n---\nsecond: doc\n", 2, "multi-document"),
            ("key: {a: 1}\n", 1, "flow mappings"),
            ("key: [a, [b, c]]\n", 1, "nested flow"),
            ("key: |\n  literal\n", 1, "literal"),
            ("key:\n\tvalue\n", 2, "tab"),
            ("key: 1\nkey: 2\n", 2, "duplicate"),
        ],
    )
    def test_rejected_with_line_number(self, text: str, line: int, fragment: str) -> None:
        with pytest.raises(SmyError) as excinfo:
            parse_smy(text)
        assert excinfo.value.line == line
        assert fragment in excinfo.value.message

    def test_top_level_sequence_is_rejected(self) -> None:
        with pytest.raises(SmyError) as excinfo:
            parse_smy("- item\n")
        assert excinfo.value.line == 1

    def test_unterminated_quote_is_rejected(self) -> None:
        with pytest.raises(SmyError) as excinfo:
            parse_smy("key: 'unterminated\n")
        assert excinfo.value.line == 1
