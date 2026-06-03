"""Drift-Schutz: Legacy-Enum-Token-Reste in ``src/`` sind verboten.

AG3-021 §AC15 fordert, dass keine alten Token-Reste (weder als Code-
Identifier noch als Kommentar/Docstring/SQL-Kommentar) in ``src/``
wieder auftauchen. Dieser Test sichert die Norm gegen Code-Drift.

Geltungsbereich:
- ``src/agentkit/`` rekursiv, ``.py`` und ``.sql``.
- Tests, Konzepte, Story-Markdowns und ``concept/_meta/`` sind bewusst
  ausgenommen — dort sind historische Erwaehnungen (Migration,
  GAP-Analyse, Konzept-Diff) zulaessig und dokumentarisch sinnvoll.

Falls dieser Test rot wird, ist die Loesung: den Begriff im
Quellcode-Kontext durch eine Formulierung ersetzen, die das Token
nicht literal enthaelt — nicht den Test weichkochen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Tokens, die aus dem v2-Vokabular oder aus Story-internen Erst-Schnitten
# stammen und in v3 ausdruecklich nicht mehr Bestandteil der jeweiligen
# Werteliste sind. Pro Eintrag: das Token plus die normative Quelle, die
# es ersetzt.
LEGACY_TOKENS: tuple[tuple[str, str], ...] = (
    # PolicyVerdict (FK-27 §27.7.2): nur PASS und FAIL.
    ("PASS_WITH_WARNINGS", "FK-27 §27.7.2 PolicyVerdict"),
    # FailureCategory (FK-41 §41.4.1): die 12 normativen Werte sind in
    # core_types.failure_corpus.FailureCategory aufgezaehlt. Aeltere,
    # repo-historisch kursierende Werte sind raus.
    ("INSTRUCTION_NEGLECT", "FK-41 §41.4.1 FailureCategory"),
    ("BAR_RAISING_FAILURE", "FK-41 §41.4.1 FailureCategory"),
    ("TEST_FRAMEWORK_GAP", "FK-41 §41.4.1 FailureCategory"),
)

# The bare StoryMode sentinel ``NOT_APPLICABLE`` (FK-24 §24.3.2 + AG3-018) is
# forbidden in src/: non-implementing stories carry NULL/None, not a sentinel.
# FK-33 §33.6.5 / AG3-052 §2.1.4 introduce EXACTLY two normatively-named
# applicability identifiers built on the ``NOT_APPLICABLE`` stem; they are the
# ONLY allowed occurrences. Everything else carrying ``NOT_APPLICABLE`` (the
# bare sentinel AND any prefixed/suffixed variant such as ``X_NOT_APPLICABLE``
# or ``NOT_APPLICABLE_FOO``) stays blocked.
_NOT_APPLICABLE_STEM = "NOT_APPLICABLE"
_NOT_APPLICABLE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "NOT_APPLICABLE_UNAVAILABLE",  # FK-33 §33.6.5 applicability
        "NOT_APPLICABLE_FAST",  # FK-33 §33.6.5 applicability
    }
)
#: Maximal identifier runs; we then keep only those carrying the stem.
_IDENTIFIER_RUN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "agentkit"

_SCAN_SUFFIXES: frozenset[str] = frozenset({".py", ".sql"})


def _iter_source_files() -> list[Path]:
    """Yield .py and .sql files unter ``src/agentkit/``."""
    return [
        path
        for path in _SRC_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in _SCAN_SUFFIXES
        and "__pycache__" not in path.parts
    ]


@pytest.mark.parametrize(("token", "source"), LEGACY_TOKENS)
def test_legacy_token_absent_from_src(token: str, source: str) -> None:
    """Kein Legacy-Token darf als eigenstaendiges Token in ``src/`` vorkommen.

    Match auf Identifier-Grenze (``\\b...(?![\\w])``): das verbotene
    Legacy-Token wird nur dann erkannt, wenn es ein *eigenstaendiges* Token
    ist — nicht, wenn es Praefix eines laengeren, fachlich eigenstaendigen
    Identifiers ist. Beispiel: das StoryMode-Sentinel ``NOT_APPLICABLE`` bleibt
    verboten, aber die FK-33 §33.6.5 Applicability-Zustaende
    ``NOT_APPLICABLE_UNAVAILABLE`` / ``NOT_APPLICABLE_FAST`` (eine andere,
    normativ benannte Werteliste, AG3-052) sind erlaubt. Das schwaecht den
    Drift-Schutz fuer das Sentinel nicht ab.

    Falls dieser Test rot wird, formuliere die betroffene Stelle so um,
    dass das Token nicht als eigenstaendiges Token auftaucht. Normative Quelle
    fuer die zulaessigen Werte siehe ``source``-Eintrag.
    """
    # Identifier-boundary: a leading word boundary plus a negative lookahead
    # for a trailing identifier char, so a longer ``TOKEN_SUFFIX`` does not match.
    pattern = re.compile(rf"\b{re.escape(token)}(?![\w])")
    hits: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        if not pattern.search(text):
            continue
        rel = path.relative_to(_REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")

    assert not hits, (
        f"Legacy-Token {token!r} (Quelle: {source}) darf nicht als "
        f"eigenstaendiges Token in src/agentkit/ vorkommen. Treffer:\n  "
        + "\n  ".join(hits)
    )


def test_not_applicable_stem_only_via_allowlisted_applicability_identifiers() -> None:
    """``NOT_APPLICABLE`` is blocked except for the two FK-33 §33.6.5 names.

    Tightened guard (AG3-052 E7): the previous ``\\bNOT_APPLICABLE(?![\\w])``
    pattern let a prefixed identifier (e.g. ``X_NOT_APPLICABLE``) slip through
    (the leading ``_`` is a word char, so there was no ``\\b`` before ``NOT``).
    This guard instead scans every identifier carrying the ``NOT_APPLICABLE``
    stem and BLOCKS all of them — the bare StoryMode sentinel
    ``NOT_APPLICABLE`` (FK-24 §24.3.2) AND any prefixed/suffixed variant —
    EXCEPT the two normatively-named applicability identifiers
    ``NOT_APPLICABLE_UNAVAILABLE`` / ``NOT_APPLICABLE_FAST`` (FK-33 §33.6.5,
    AG3-052 §2.1.4). That keeps the sentinel drift-protected without a blanket
    loosening.

    Falls dieser Test rot wird: entweder benenne die Stelle so um, dass das
    ``NOT_APPLICABLE``-Stem nicht auftaucht, oder — nur fuer eine NEUE
    normative Applicability-Werteliste — ergaenze sie bewusst in
    ``_NOT_APPLICABLE_ALLOWLIST`` mit Konzept-Quelle.
    """
    hits: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        if _NOT_APPLICABLE_STEM not in text:
            continue
        rel = path.relative_to(_REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for ident in _IDENTIFIER_RUN.findall(line):
                if _NOT_APPLICABLE_STEM not in ident:
                    continue
                if ident in _NOT_APPLICABLE_ALLOWLIST:
                    continue
                hits.append(f"{rel}:{lineno}: {line.strip()}")
                break

    assert not hits, (
        "The NOT_APPLICABLE stem (FK-24 §24.3.2 StoryMode sentinel) is "
        "forbidden in src/agentkit/ except for the two FK-33 §33.6.5 "
        f"applicability identifiers {sorted(_NOT_APPLICABLE_ALLOWLIST)}. "
        "Disallowed occurrences (bare sentinel or prefixed/suffixed "
        "variants):\n  " + "\n  ".join(hits)
    )
