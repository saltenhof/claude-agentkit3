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
# ONLY *globally* allowed occurrences. Everything else carrying
# ``NOT_APPLICABLE`` (the bare sentinel AND any prefixed/suffixed variant such
# as ``X_NOT_APPLICABLE`` or ``NOT_APPLICABLE_FOO``) stays blocked.
#
# AG3-044 (FK-26 §26.7.3) adds the ``ACStatus.NOT_APPLICABLE`` member (per-AC
# handover applicability). Its bare identifier collides with the FK-24 §24.3.2
# StoryMode sentinel, so it is NOT globally allowlisted (that would re-open the
# AG3-052 sentinel hole: a future bare ``NOT_APPLICABLE`` sentinel ANYWHERE in
# ``src/`` would silently pass). Instead it is admitted in exactly two narrow,
# auditable shapes:
#   1. the QUALIFIED dotted form ``ACStatus.NOT_APPLICABLE`` (call sites), and
#   2. the bare member inside the enum's defining module ONLY
#      (``implementation/handover/packager.py``), where an enum member must be
#      declared bare and cannot be qualified.
# A bare ``NOT_APPLICABLE`` ANYWHERE else still trips the guard.
_NOT_APPLICABLE_STEM = "NOT_APPLICABLE"
#: Prefixed/suffixed applicability names allowed in ANY source file.
_NOT_APPLICABLE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "NOT_APPLICABLE_UNAVAILABLE",  # FK-33 §33.6.5 applicability
        "NOT_APPLICABLE_FAST",  # FK-33 §33.6.5 applicability
    }
)
#: The qualified ACStatus access form (FK-26 §26.7.3); allowed at any call site.
_QUALIFIED_ACSTATUS = re.compile(r"\bACStatus\.NOT_APPLICABLE\b")
#: The ONE module that DEFINES ``ACStatus``; a bare member declaration is only
#: legitimate here (an enum member cannot be written in qualified form).
_ACSTATUS_HOME = Path("src") / "agentkit" / "implementation" / "handover" / "packager.py"
#: The EXACT ``ACStatus`` enum-member declaration line -- the ONLY legitimate
#: bare occurrence inside the enum home. A whole-file home skip would let an
#: unrelated bare sentinel hide in packager.py; this pins the exemption to the
#: member declaration so a stray bare sentinel in that file still trips.
_ACSTATUS_MEMBER_DECL_RE = re.compile(r'^NOT_APPLICABLE\s*=\s*"NOT_APPLICABLE"$')
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


def _bare_not_applicable_hits_in_line(line: str) -> int:
    """Count BARE ``NOT_APPLICABLE`` occurrences (sentinel-shaped) in a line.

    "Bare" means the exact stem ``NOT_APPLICABLE`` as a standalone identifier
    that is NOT one of the prefixed/suffixed applicability names AND NOT the
    qualified ``ACStatus.NOT_APPLICABLE`` access form. Each such occurrence
    re-opens the AG3-052 sentinel hole, so each is counted as a hit.
    """
    qualified = len(_QUALIFIED_ACSTATUS.findall(line))
    stem_idents = 0
    for ident in _IDENTIFIER_RUN.findall(line):
        if _NOT_APPLICABLE_STEM not in ident:
            continue
        if ident in _NOT_APPLICABLE_ALLOWLIST:
            continue  # prefixed FK-33 applicability name — globally allowed
        if ident != _NOT_APPLICABLE_STEM:
            # A different stem-carrying identifier (e.g. ``X_NOT_APPLICABLE``):
            # never legitimate, count it.
            stem_idents += 1
            continue
        stem_idents += 1
    # Subtract the qualified ``ACStatus.NOT_APPLICABLE`` occurrences: those are
    # admitted call sites. Any remaining bare ``NOT_APPLICABLE`` is a hit.
    return max(stem_idents - qualified, 0)


def _disallowed_bare_in_line(line: str, *, is_acstatus_home: bool) -> bool:
    """True if ``line`` carries a bare ``NOT_APPLICABLE`` sentinel that is NOT allowed.

    The ONLY bare occurrence admitted inside the enum home is the exact
    ``ACStatus`` member-declaration line; every other bare sentinel (in the home
    file or anywhere else) is disallowed. This replaces the previous whole-file
    home skip, which let an unrelated bare sentinel hide in ``packager.py``.
    """
    if _bare_not_applicable_hits_in_line(line) == 0:
        return False
    # The ONLY admitted bare occurrence is the exact ACStatus member declaration
    # inside the enum home; everything else is a disallowed bare sentinel.
    return not (is_acstatus_home and bool(_ACSTATUS_MEMBER_DECL_RE.match(line.strip())))


def test_not_applicable_stem_only_via_allowlisted_applicability_identifiers() -> None:
    """A BARE ``NOT_APPLICABLE`` sentinel is blocked everywhere but its enum home.

    Tightened guard (AG3-052 E7 + AG3-044 confirmation FIX-1): the bare
    StoryMode sentinel ``NOT_APPLICABLE`` (FK-24 §24.3.2) is forbidden in
    ``src/agentkit/``. Allowed stem-carrying shapes are EXACTLY:

    * the two prefixed FK-33 §33.6.5 applicability names
      ``NOT_APPLICABLE_UNAVAILABLE`` / ``NOT_APPLICABLE_FAST`` (any file);
    * the QUALIFIED ``ACStatus.NOT_APPLICABLE`` access form (any call site);
    * the BARE ``ACStatus.NOT_APPLICABLE`` member declaration ONLY inside its
      defining module ``implementation/handover/packager.py`` (an enum member
      cannot be written qualified).

    The previous revision globally allowlisted the BARE identifier
    ``NOT_APPLICABLE``; that re-opened the AG3-052 hole — a future bare
    StoryMode sentinel ``NOT_APPLICABLE`` ANYWHERE in ``src/`` would silently
    pass. This guard removes the global bare allowance and admits the AG3-044
    ``ACStatus`` member only via the qualified form / its enum home, so a stray
    bare sentinel still trips.

    Falls dieser Test rot wird: entweder benenne die Stelle so um, dass das
    BARE ``NOT_APPLICABLE`` nicht auftaucht (qualifiziere zu
    ``ACStatus.NOT_APPLICABLE`` oder formuliere die Prosa um), oder — nur fuer
    eine NEUE normative Applicability-Werteliste — ergaenze sie bewusst in
    ``_NOT_APPLICABLE_ALLOWLIST`` mit Konzept-Quelle.
    """
    hits: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        if _NOT_APPLICABLE_STEM not in text:
            continue
        rel = path.relative_to(_REPO_ROOT)
        is_acstatus_home = rel == _ACSTATUS_HOME
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _disallowed_bare_in_line(line, is_acstatus_home=is_acstatus_home):
                hits.append(f"{rel}:{lineno}: {line.strip()}")

    # The home exemption is shape-based, so pin that the bare member declaration
    # appears EXACTLY once in packager.py: a second identical line must not hide a
    # bare sentinel behind the exemption (AG3-044 round-4 hardening).
    _home_lines = (_REPO_ROOT / _ACSTATUS_HOME).read_text(encoding="utf-8").splitlines()
    _member_decls = sum(
        1 for _ln in _home_lines if _ACSTATUS_MEMBER_DECL_RE.match(_ln.strip())
    )
    assert _member_decls == 1, (
        "The bare ACStatus.NOT_APPLICABLE member declaration must appear EXACTLY "
        f"once in {_ACSTATUS_HOME}; found {_member_decls} -- a duplicate "
        "same-shaped line would be silently exempted by the home-file guard."
    )

    assert not hits, (
        "The BARE NOT_APPLICABLE stem (FK-24 §24.3.2 StoryMode sentinel) is "
        "forbidden in src/agentkit/. Allowed: the prefixed applicability names "
        f"{sorted(_NOT_APPLICABLE_ALLOWLIST)}, the qualified "
        "ACStatus.NOT_APPLICABLE form, and the bare member only in its enum "
        "home (implementation/handover/packager.py). "
        "Disallowed bare occurrences:\n  " + "\n  ".join(hits)
    )


def test_acstatus_member_is_only_referenced_qualified_outside_its_home() -> None:
    """Outside packager.py, ACStatus.NOT_APPLICABLE is referenced only qualified.

    Pins the AG3-052 FIX-1 scoping invariant against drift: every
    src/agentkit/ line carrying the bare ``NOT_APPLICABLE`` stem (outside the
    enum home) MUST be a qualified ``ACStatus.NOT_APPLICABLE`` access or a
    prefixed FK-33 applicability name — never a bare sentinel. This is the
    machine-checkable form of "the only legitimate use is
    ACStatus.NOT_APPLICABLE in implementation/handover/packager.py".
    """
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        if _NOT_APPLICABLE_STEM not in text:
            continue
        rel = path.relative_to(_REPO_ROOT)
        if rel == _ACSTATUS_HOME:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _bare_not_applicable_hits_in_line(line) > 0:
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "Outside its enum home, NOT_APPLICABLE must appear only as the "
        f"qualified ACStatus.NOT_APPLICABLE form. Bare offenders: {offenders}"
    )


def test_home_file_exemption_covers_only_the_enum_member_declaration() -> None:
    """The packager.py home exemption admits ONLY the exact ACStatus member decl.

    Regression for the AG3-044 round-3 finding: the previous whole-file skip let
    any bare ``NOT_APPLICABLE`` (e.g. a StoryMode sentinel) hide in the enum home
    module. The exemption now pins to the member-declaration line, so a stray
    bare sentinel in that file still trips the guard.
    """
    # The exact enum-member declaration is admitted inside the home file.
    assert not _disallowed_bare_in_line(
        'NOT_APPLICABLE = "NOT_APPLICABLE"', is_acstatus_home=True
    )
    # ANY OTHER bare sentinel in the home file is STILL disallowed (the hole).
    assert _disallowed_bare_in_line("    mode = NOT_APPLICABLE", is_acstatus_home=True)
    assert _disallowed_bare_in_line(
        '    sentinel = "NOT_APPLICABLE"', is_acstatus_home=True
    )
    # The qualified access form is allowed everywhere, incl. the home file.
    assert not _disallowed_bare_in_line(
        "    ACStatus.NOT_APPLICABLE: per-AC applicability", is_acstatus_home=True
    )


def test_bare_not_applicable_sentinel_simulated_trips_the_guard() -> None:
    """A simulated BARE NOT_APPLICABLE sentinel STILL trips the guard (AG3-052).

    Regression pin for the FIX-1 confirmation finding: the previous global
    allowlist of the bare identifier ``NOT_APPLICABLE`` let a future bare
    StoryMode sentinel pass silently. These simulated lines stand in for such a
    sentinel reappearing in src/ and MUST be detected as hits.
    """
    # A bare assignment/use of the sentinel (NOT qualified, NOT a prefixed name).
    assert _bare_not_applicable_hits_in_line(
        "story_mode = NOT_APPLICABLE"
    ) == 1
    assert _bare_not_applicable_hits_in_line(
        'DEFAULT = "x"  # falls back to NOT_APPLICABLE'
    ) == 1
    # A prefixed/suffixed variant is never legitimate either.
    assert _bare_not_applicable_hits_in_line("X_NOT_APPLICABLE = 1") == 1
    # A line mixing a qualified access AND a stray bare sentinel still trips on
    # the bare one (the qualified one is subtracted, the bare one remains).
    assert _bare_not_applicable_hits_in_line(
        "value = ACStatus.NOT_APPLICABLE if flag else NOT_APPLICABLE"
    ) == 1


def test_qualified_acstatus_not_applicable_is_allowed() -> None:
    """The qualified ACStatus.NOT_APPLICABLE access form does NOT trip the guard.

    Confirms FIX-1 keeps the legitimate AG3-044 ACStatus member usable at call
    sites: a qualified ``ACStatus.NOT_APPLICABLE`` reference is admitted while
    the bare sentinel is not.
    """
    assert _bare_not_applicable_hits_in_line(
        "status[ac] = ACStatus.NOT_APPLICABLE"
    ) == 0
    # The prefixed FK-33 applicability names remain globally allowed.
    assert _bare_not_applicable_hits_in_line(
        "applicability = SonarApplicability.NOT_APPLICABLE_FAST"
    ) == 0
    assert _bare_not_applicable_hits_in_line(
        "applicability = SonarApplicability.NOT_APPLICABLE_UNAVAILABLE"
    ) == 0
