"""Measure distribution boundary violations that touch one bounded context.

The counting unit is the one fixed by the formal spec
``formal.architecture-conformance.entities`` under
``distribution_boundary_violations.counting_unit``: unique ordered module pairs
``(importer -> imported)`` whose two modules belong to different distributions.

The distribution of a module is resolved exactly as the spec prescribes:
``longest-match-wins`` over ``module_prefixes``, with ``module_members`` as an
exact-match rule of maximal specificity.

The check is fail-closed in both directions that matter for this story:

* a module under ``src/agentkit`` that no prefix and no member entry claims is
  never silently skipped: it is listed in the report, and the measurement stops
  as soon as such a module takes part in an import that touches the bounded
  context under measurement;
* a star import stops the measurement, because the reached symbols are unknown.

Usage::

    .venv\\Scripts\\python stories/AG3-239-governance-endpunkte-fuer-den-edge/\\
        measure_boundary_violations.py --bc agentkit.backend.governance
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "agentkit"
ENTITIES = (
    REPO_ROOT
    / "concept"
    / "formal-spec"
    / "architecture-conformance"
    / "entities.md"
)
FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(?P<body>.*?)\n```", re.DOTALL
)


class MeasurementError(RuntimeError):
    """Raised when the measurement cannot be completed fail-closed."""


@dataclass(frozen=True)
class Crossing:
    """One import statement that crosses the distribution boundary."""

    importer: str
    imported: str
    symbol: str
    lineno: int
    importer_distribution: str
    imported_distribution: str

    @property
    def direction(self) -> str:
        """Return the crossing direction in spec notation."""
        return f"{self.importer_distribution}-to-{self.imported_distribution}"


def load_distribution_rules() -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(prefix -> distribution, module -> distribution)`` from the spec."""
    match = FORMAL_BLOCK.search(ENTITIES.read_text(encoding="utf-8"))
    if match is None:
        raise MeasurementError(f"no formal-spec block in {ENTITIES}")
    document = yaml.safe_load(match.group("body"))
    prefixes: dict[str, str] = {}
    members: dict[str, str] = {}
    for distribution in document["distributions"]:
        code = str(distribution["code"])
        for prefix in distribution.get("module_prefixes") or ():
            if prefix in prefixes and prefixes[prefix] != code:
                raise MeasurementError(f"prefix {prefix} claimed twice")
            prefixes[str(prefix)] = code
        for member in distribution.get("module_members") or ():
            members[str(member)] = code
    if not prefixes:
        raise MeasurementError("no module prefixes in the classification")
    return prefixes, members


def module_name_of(path: Path) -> str:
    """Return the dotted module name of a file below ``src/``."""
    relative = path.relative_to(SRC_ROOT)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


def collect_modules() -> dict[str, Path]:
    """Return every importable module of the ``agentkit`` package."""
    modules: dict[str, Path] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        modules[module_name_of(path)] = path
    return modules


def resolve_distribution(
    module: str, prefixes: dict[str, str], members: dict[str, str]
) -> str | None:
    """Return the distribution owning ``module``, or ``None`` when unclaimed."""
    if module in members:
        return members[module]
    best: str | None = None
    best_length = -1
    for prefix, code in prefixes.items():
        if module == prefix or module.startswith(prefix + "."):
            length = len(prefix)
            if length > best_length:
                best, best_length = code, length
            elif length == best_length and code != best:
                raise MeasurementError(
                    f"{module}: two equally long prefixes claim it -- "
                    "distribution_membership_is_total_and_disjoint is violated"
                )
    return best


def resolve_import_target(
    base: str, attribute: str, modules: dict[str, str | Path] | dict[str, Path]
) -> str:
    """Return the module a ``from base import attribute`` statement reaches."""
    candidate = f"{base}.{attribute}" if base else attribute
    if candidate in modules:
        return candidate
    return base


def iter_crossings(
    modules: dict[str, Path],
    prefixes: dict[str, str],
    members: dict[str, str],
    touches_bc: Callable[[str], bool],
) -> Iterable[Crossing]:
    """Yield every import statement that crosses a distribution boundary."""
    for importer, path in modules.items():
        importer_distribution = resolve_distribution(importer, prefixes, members)
        if importer_distribution is None and touches_bc(importer):
            raise MeasurementError(
                f"{importer}: unclaimed by the classification and part of the "
                "bounded context under measurement"
            )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = importer if path.name == "__init__.py" else importer.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("agentkit"):
                        continue
                    yield from _emit(
                        importer,
                        importer_distribution,
                        alias.name,
                        alias.name.rpartition(".")[2],
                        node.lineno,
                        prefixes,
                        members,
                        touches_bc,
                    )
            elif isinstance(node, ast.ImportFrom):
                base = _absolute_base(node, package)
                if base is None or not base.startswith("agentkit"):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        raise MeasurementError(
                            f"{importer}:{node.lineno}: star import from {base} -- "
                            "the reached symbols are unknown, measurement stops"
                        )
                    target = resolve_import_target(base, alias.name, modules)
                    yield from _emit(
                        importer,
                        importer_distribution,
                        target,
                        alias.name,
                        node.lineno,
                        prefixes,
                        members,
                        touches_bc,
                    )


def _absolute_base(node: ast.ImportFrom, package: str) -> str | None:
    """Return the absolute module a ``from ... import`` statement starts at."""
    if node.level == 0:
        return node.module
    parts = package.split(".")
    if node.level - 1 > len(parts):
        raise MeasurementError(f"relative import escapes the package: {package}")
    anchor = parts[: len(parts) - (node.level - 1)]
    if node.module:
        anchor = anchor + node.module.split(".")
    return ".".join(anchor)


def _emit(
    importer: str,
    importer_distribution: str | None,
    imported: str,
    symbol: str,
    lineno: int,
    prefixes: dict[str, str],
    members: dict[str, str],
    touches_bc: Callable[[str], bool],
) -> Iterable[Crossing]:
    """Yield a crossing when importer and imported sit in different distributions."""
    imported_distribution = resolve_distribution(imported, prefixes, members)
    if importer_distribution is None or imported_distribution is None:
        if touches_bc(importer) or touches_bc(imported):
            raise MeasurementError(
                f"{importer}:{lineno} -> {imported}: one side is unclaimed by "
                "the classification and the edge touches the bounded context "
                "under measurement"
            )
        return
    if imported_distribution == importer_distribution:
        return
    yield Crossing(
        importer=importer,
        imported=imported,
        symbol=symbol,
        lineno=lineno,
        importer_distribution=importer_distribution,
        imported_distribution=imported_distribution,
    )


def main() -> int:
    """Run the measurement and print the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bc",
        action="append",
        default=None,
        help="module prefix of the bounded context; repeatable. "
        "Omit to report every crossing.",
    )
    parser.add_argument("--json", type=Path, default=None)
    arguments = parser.parse_args()
    bc_prefixes = tuple(arguments.bc or ())

    prefixes, members = load_distribution_rules()
    modules = collect_modules()

    def touches_bc(module: str) -> bool:
        return any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in bc_prefixes
        )

    unclaimed = sorted(
        name
        for name in modules
        if resolve_distribution(name, prefixes, members) is None
    )
    crossings = list(iter_crossings(modules, prefixes, members, touches_bc))

    if bc_prefixes:
        crossings = [
            crossing
            for crossing in crossings
            if touches_bc(crossing.importer) or touches_bc(crossing.imported)
        ]

    pairs: dict[tuple[str, str], list[Crossing]] = {}
    for crossing in crossings:
        pairs.setdefault((crossing.importer, crossing.imported), []).append(crossing)

    edge_to_core = sum(
        1 for entries in pairs.values() if entries[0].direction == "edge-to-core"
    )
    core_to_edge = sum(
        1 for entries in pairs.values() if entries[0].direction == "core-to-edge"
    )
    symbols = {
        (crossing.imported, crossing.symbol)
        for crossing in crossings
        if touches_bc(crossing.imported) or not bc_prefixes
    }

    print(f"bounded context prefixes : {', '.join(bc_prefixes) or '(all)'}")
    print(f"unique ordered pairs     : {len(pairs)}")
    print(f"  edge-to-core           : {edge_to_core}")
    print(f"  core-to-edge           : {core_to_edge}")
    print(f"import statements        : {len(crossings)}")
    print(f"distinct imported symbols: {len(symbols)}")
    print(f"unclaimed modules        : {len(unclaimed)} {unclaimed}")
    print()
    for (importer, imported), entries in sorted(pairs.items()):
        names = sorted({entry.symbol for entry in entries})
        print(f"{entries[0].direction}  {importer} -> {imported}")
        for entry in sorted(entries, key=lambda item: item.lineno):
            print(f"    :{entry.lineno} {entry.symbol}")
        del names

    if arguments.json is not None:
        arguments.json.write_text(
            json.dumps(
                {
                    "pairs": [
                        {
                            "importer": importer,
                            "imported": imported,
                            "direction": entries[0].direction,
                            "symbols": sorted({e.symbol for e in entries}),
                            "lines": sorted(e.lineno for e in entries),
                        }
                        for (importer, imported), entries in sorted(pairs.items())
                    ],
                    "total": len(pairs),
                    "edge_to_core": edge_to_core,
                    "core_to_edge": core_to_edge,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasurementError as error:
        print(f"MEASUREMENT STOPPED: {error}", file=sys.stderr)
        sys.exit(2)
