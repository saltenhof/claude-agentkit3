"""Prove that AG3-239 AC 1 is total: one answer per measured crossing.

The check is a set comparison in both directions, so neither a forgotten
crossing nor an invented one can pass:

* every unique ordered module pair reported by ``measure_boundary_violations``
  for the bounded context appears exactly once in ``crossing_answers.yaml``;
* every entry of ``crossing_answers.yaml`` corresponds to a measured pair;
* every entry carries exactly one answer out of ``a`` / ``b`` / ``c``, a
  non-empty reason and a remedy owner;
* the symbol list of an entry matches the measured symbols of its pair.

Usage::

    .venv\\Scripts\\python stories/AG3-239-governance-endpunkte-fuer-den-edge/\\
        check_crossing_answers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_boundary_violations import (  # noqa: E402 -- path set above
    collect_modules,
    iter_crossings,
    load_distribution_rules,
)

BC_PREFIX = "agentkit.backend.governance"
ANSWERS = Path(__file__).resolve().parent / "crossing_answers.yaml"
VALID_ANSWERS = frozenset({"a", "b", "c"})


def _touches_bc(module: str) -> bool:
    """Return whether a module belongs to the bounded context."""
    return module == BC_PREFIX or module.startswith(BC_PREFIX + ".")


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


def index_answers(
    entries: list[dict[str, object]], problems: list[str]
) -> dict[tuple[str, str], dict[str, object]]:
    """Index the answer entries by pair, recording per-entry defects."""
    answered: dict[tuple[str, str], dict[str, object]] = {}
    for entry in entries:
        key = (str(entry["importer"]), str(entry["imported"]))
        if key in answered:
            problems.append(f"answered twice: {key[0]} -> {key[1]}")
        answered[key] = entry
        answer = entry.get("answer")
        if answer not in VALID_ANSWERS:
            problems.append(f"{key[0]} -> {key[1]}: answer {answer!r} is not a/b/c")
        if not str(entry.get("reason", "")).strip():
            problems.append(f"{key[0]} -> {key[1]}: empty reason")
        if not str(entry.get("remedy_owner", "")).strip():
            problems.append(f"{key[0]} -> {key[1]}: no remedy owner")
    return answered


def main() -> int:
    """Run the totality check and report every discrepancy."""
    measured = measure()
    document = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    entries = document["crossings"]
    problems: list[str] = []
    answered = index_answers(entries, problems)

    for key in sorted(set(measured) - set(answered)):
        problems.append(f"MEASURED BUT UNANSWERED: {key[0]} -> {key[1]}")
    for key in sorted(set(answered) - set(measured)):
        problems.append(f"ANSWERED BUT NOT MEASURED: {key[0]} -> {key[1]}")

    for key in sorted(set(measured) & set(answered)):
        declared = set(map(str, answered[key].get("symbols") or ()))
        if declared != measured[key]:
            problems.append(
                f"{key[0]} -> {key[1]}: symbols {sorted(declared)} "
                f"!= measured {sorted(measured[key])}"
            )

    declared_total = document["measurement"]["unique_ordered_pairs"]
    if declared_total != len(measured):
        problems.append(
            f"declared unique_ordered_pairs {declared_total} "
            f"!= measured {len(measured)}"
        )

    print(f"measured pairs : {len(measured)}")
    print(f"answered pairs : {len(answered)}")
    counts = {code: 0 for code in sorted(VALID_ANSWERS)}
    for entry in entries:
        answer = str(entry.get("answer"))
        if answer in counts:
            counts[answer] += 1
    print(f"answers        : {counts}")
    blocked = sum(1 for entry in entries if entry.get("blocked") is True)
    print(f"blocked (foreign owner): {blocked}")

    if problems:
        print()
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    print("OK -- AC 1 is total: one answer per measured crossing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
