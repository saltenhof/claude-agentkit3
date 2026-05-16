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

from pathlib import Path

import pytest

# Tokens, die aus dem v2-Vokabular oder aus Story-internen Erst-Schnitten
# stammen und in v3 ausdruecklich nicht mehr Bestandteil der jeweiligen
# Werteliste sind. Pro Eintrag: das Token plus die normative Quelle, die
# es ersetzt.
LEGACY_TOKENS: tuple[tuple[str, str], ...] = (
    # PolicyVerdict (FK-27 §27.7.2): nur PASS und FAIL.
    ("PASS_WITH_WARNINGS", "FK-27 §27.7.2 PolicyVerdict"),
    # StoryMode (FK-24 §24.3.2 + AG3-018): nicht-implementierende Storys
    # tragen NULL/None statt eines Sentinel-Enum-Werts.
    ("NOT_APPLICABLE", "FK-24 §24.3.2 StoryMode"),
    # FailureCategory (FK-41 §41.4.1): die 12 normativen Werte sind in
    # core_types.failure_corpus.FailureCategory aufgezaehlt. Aeltere,
    # repo-historisch kursierende Werte sind raus.
    ("INSTRUCTION_NEGLECT", "FK-41 §41.4.1 FailureCategory"),
    ("BAR_RAISING_FAILURE", "FK-41 §41.4.1 FailureCategory"),
    ("TEST_FRAMEWORK_GAP", "FK-41 §41.4.1 FailureCategory"),
)

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
    """Kein Legacy-Token darf literal in ``src/agentkit/`` vorkommen.

    Falls dieser Test rot wird, formuliere die betroffene Stelle so um,
    dass das Token nicht als Buchstabenfolge auftaucht. Normative Quelle
    fuer die zulaessigen Werte siehe ``source``-Eintrag.
    """
    hits: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        if token in text:
            rel = path.relative_to(_REPO_ROOT)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if token in line:
                    hits.append(f"{rel}:{lineno}: {line.strip()}")

    assert not hits, (
        f"Legacy-Token {token!r} (Quelle: {source}) darf nicht in "
        f"src/agentkit/ vorkommen. Treffer:\n  " + "\n  ".join(hits)
    )
