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
  non-empty reason and a remedy owner;
* the symbol list of an entry matches the measured symbols of its pair.

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


def check_endpoint_claims(document: dict[str, object], problems: list[str]) -> None:
    """Reject an (a) answer that names AG3-242 without an endpoint to show.

    AC 3 forbids an endpoint without a call site, and this story ships none. An
    entry that answers (a) and keeps the remedy for itself would therefore be a
    promise nothing in the diff keeps.
    """
    built = document.get("endpoints") or []
    for entry in document["crossings"]:  # type: ignore[index]
        if entry.get("answer") == "a" and entry.get("remedy_owner") == "AG3-242":
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

    print(f"measured pairs : {len(measured)}")
    print(f"answered pairs : {len(answered)}")
    counts = {code: 0 for code in sorted(VALID_ANSWERS)}
    for entry in entries:
        answer = str(entry.get("answer"))
        if answer in counts:
            counts[answer] += 1
    print(f"answers        : {counts}")
    owners: dict[str, int] = {}
    for entry in entries:
        owner = str(entry.get("remedy_owner", ""))
        owners[owner] = owners.get(owner, 0) + 1
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
