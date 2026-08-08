"""Prove that AG3-242 AC 1 is total: one answer per measured crossing.

The measurement tool of AG3-239 is USED, not copied: a second copy of a
measurement script is a second measurement that drifts. This checker only adds
the set comparison against ``crossing_answers.yaml``, in both directions, so
neither a forgotten crossing nor an invented one can pass:

* every unique ordered module pair reported by ``measure_boundary_violations``
  for the bounded context appears exactly once in ``crossing_answers.yaml``;
* every entry of ``crossing_answers.yaml`` corresponds to a measured pair, or is
  marked ``resolved: true`` -- and that mark is verified, not trusted;
* every entry carries exactly one answer out of ``a`` / ``b`` / ``c``, a
  non-empty reason and a remedy owner -- or, where one pair genuinely carries
  two different answers, a ``symbol_answers`` split whose groups partition the
  entry's symbols exactly (no symbol answered twice, none left unanswered);
* the symbol list of an entry matches the measured symbols of its pair.

A pair whose symbols mix local edge work with a real core operation must NOT be
given a blanket answer: a uniform answer is wrong in both directions there. The
``symbol_answers`` split exists for exactly that case and is the reason the
tallies below are printed per DECISION as well as per entry.

Usage::

    .venv\\Scripts\\python stories/AG3-242-installer-endpunkte-fuer-den-edge/\\
        check_crossing_answers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_MEASURE_DIR = (
    Path(__file__).resolve().parents[1] / "AG3-239-governance-endpunkte-fuer-den-edge"
)
sys.path.insert(0, str(_MEASURE_DIR))

from measure_boundary_violations import (  # noqa: E402 -- path set above
    collect_modules,
    iter_crossings,
    load_distribution_rules,
)

#: Both module prefixes of the bounded context. ``process.language`` is measured
#: with the installer because the story card places it here; the answer file
#: records that the placement is refuted by the measurement.
BC_PREFIXES = (
    "agentkit.backend.installer",
    "agentkit.backend.process.language",
)
ANSWERS = Path(__file__).resolve().parent / "crossing_answers.yaml"
VALID_ANSWERS = frozenset({"a", "b", "c"})


def _touches_bc(module: str) -> bool:
    """Return whether a module belongs to the bounded context."""
    return any(
        module == prefix or module.startswith(prefix + ".") for prefix in BC_PREFIXES
    )


def measure() -> dict[tuple[str, str], set[str]]:
    """Return the measured crossings of the bounded context with their symbols."""
    prefixes, members = load_distribution_rules()
    modules = collect_modules()
    measured: dict[tuple[str, str], set[str]] = {}
    for crossing in iter_crossings(modules, prefixes, members, _touches_bc):
        if not (_touches_bc(crossing.importer) or _touches_bc(crossing.imported)):
            continue
        measured.setdefault((crossing.importer, crossing.imported), set()).add(
            crossing.symbol
        )
    return measured


def decisions(entry: dict[str, object]) -> list[dict[str, object]]:
    """Return the answer decisions of an entry: the entry itself, or its split."""
    split = entry.get("symbol_answers")
    if split is None:
        return [entry]
    return [group for group in split if isinstance(group, dict)]


def _check_decision(pair: str, decision: dict[str, object], problems: list[str]) -> None:
    """Record the defects of one answer decision."""
    answer = decision.get("answer")
    if answer not in VALID_ANSWERS:
        problems.append(f"{pair}: answer {answer!r} is not a/b/c")
    if not str(decision.get("reason", "")).strip():
        problems.append(f"{pair}: empty reason")
    if not str(decision.get("remedy_owner", "")).strip():
        problems.append(f"{pair}: no remedy owner")


def index_answers(
    entries: list[dict[str, object]], problems: list[str]
) -> dict[tuple[str, str], dict[str, object]]:
    """Index the answer entries by pair, recording per-entry defects."""
    answered: dict[tuple[str, str], dict[str, object]] = {}
    for entry in entries:
        key = (str(entry["importer"]), str(entry["imported"]))
        pair = f"{key[0]} -> {key[1]}"
        if key in answered:
            problems.append(f"answered twice: {pair}")
        answered[key] = entry
        split = entry.get("symbol_answers")
        if split is None:
            _check_decision(pair, entry, problems)
            continue
        if entry.get("answer") is not None:
            problems.append(f"{pair}: carries both `answer` and `symbol_answers`")
        covered: list[str] = []
        for group in decisions(entry):
            _check_decision(pair, group, problems)
            covered.extend(str(symbol) for symbol in group.get("symbols") or ())
        declared = [str(symbol) for symbol in entry.get("symbols") or ()]
        if sorted(covered) != sorted(declared):
            problems.append(
                f"{pair}: symbol_answers cover {sorted(covered)} != "
                f"entry symbols {sorted(declared)}"
            )
    return answered


def check_endpoint_claims(document: dict[str, object], problems: list[str]) -> None:
    """Reject an (a) answer that names AG3-242 without an endpoint to show.

    AC 3 forbids an endpoint without a call site, and this story ships none. An
    entry that answers (a) and keeps the remedy for itself would therefore be a
    promise nothing in the diff keeps.
    """
    built = document.get("endpoints") or []
    for entry in document["crossings"]:  # type: ignore[index]
        for decision in decisions(entry):
            if decision.get("answer") == "a" and decision.get("remedy_owner") == "AG3-242":
                if not built:
                    problems.append(
                        f"{entry['importer']} -> {entry['imported']}: answered (a) with "
                        "remedy_owner AG3-242, but `endpoints` is empty"
                    )


def main() -> int:
    """Run the totality check and report every discrepancy."""
    measured = measure()
    document = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    entries = document["crossings"]
    problems: list[str] = []
    answered = index_answers(entries, problems)
    check_endpoint_claims(document, problems)

    for key in sorted(set(measured) - set(answered)):
        problems.append(f"MEASURED BUT UNANSWERED: {key[0]} -> {key[1]}")
    for key in sorted(set(answered) - set(measured)):
        if answered[key].get("resolved") is not True:
            problems.append(f"ANSWERED BUT NOT MEASURED: {key[0]} -> {key[1]}")
    for key in sorted(set(answered) & set(measured)):
        if answered[key].get("resolved") is True:
            problems.append(
                f"CLAIMED RESOLVED BUT STILL MEASURED: {key[0]} -> {key[1]}"
            )

    for key in sorted(set(measured) & set(answered)):
        declared = set(map(str, answered[key].get("symbols") or ()))
        if declared != measured[key]:
            problems.append(
                f"{key[0]} -> {key[1]}: symbols {sorted(declared)} "
                f"!= measured {sorted(measured[key])}"
            )

    declared_end = document["measurement"]["end_value"]["unique_ordered_pairs"]
    if declared_end != len(measured):
        problems.append(
            f"declared end_value.unique_ordered_pairs {declared_end} "
            f"!= measured {len(measured)}"
        )
    declared_start = document["measurement"]["start_value"]["unique_ordered_pairs"]
    if declared_start != len(answered):
        problems.append(
            f"declared start_value.unique_ordered_pairs {declared_start} "
            f"!= answered {len(answered)}"
        )

    # Active and historical are counted SEPARATELY and never summed into one
    # figure. A `resolved: true` pair is a crossing this story already removed;
    # adding it to the live tally states a workload that no longer exists.
    active = {code: 0 for code in sorted(VALID_ANSWERS)}
    historical = {code: 0 for code in sorted(VALID_ANSWERS)}
    owners: dict[str, int] = {}
    active_entries = 0
    historical_entries = 0
    for entry in entries:
        is_historical = entry.get("resolved") is True
        if is_historical:
            historical_entries += 1
        else:
            active_entries += 1
        for decision in decisions(entry):
            bucket = historical if is_historical else active
            answer = str(decision.get("answer"))
            if answer in bucket:
                bucket[answer] += 1
            owner = str(decision.get("remedy_owner", ""))
            owners[owner] = owners.get(owner, 0) + 1

    print(f"measured pairs : {len(measured)}")
    print(f"entries        : {len(answered)} = {active_entries} active + {historical_entries} historical")
    print(f"active answers     : {active}")
    print(f"historical answers : {historical}")
    print("(answers are counted per DECISION -- a `symbol_answers` entry")
    print(" contributes one count per symbol group, so the answer totals may")
    print(" exceed the entry count.)")
    print(f"remedy owners  : {dict(sorted(owners.items()))}")

    if problems:
        print()
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    print("OK -- AC 1 is total: one answer per measured crossing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
