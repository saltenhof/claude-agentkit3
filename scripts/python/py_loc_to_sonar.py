#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import io
import json
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    "dist",
    "build",
    ".eggs",
}

FUNCTION_MAX_LOC = 500
CLASS_WARN_MAX_LOC = 800
CLASS_ERROR_MAX_LOC = 1200
MODULE_TOP_LEVEL_MAX_LOC = 100

ENGINE_ID = "agentkit-python-loc"


@dataclass(frozen=True)
class Issue:
    rule_id: str
    message: str
    file_path: str
    start_line: int
    end_line: int
    start_column: int = 1
    end_column: int = 1
    effort_minutes: int = 20


RULES = [
    {
        "id": "PY_FUNCTION_MAX_LOC_500",
        "name": "Python function or method exceeds 500 LOC",
        "description": "Functions and methods must not exceed 500 lines of code.",
        "engineId": ENGINE_ID,
        "cleanCodeAttribute": "FOCUSED",
        "type": "CODE_SMELL",
        "severity": "CRITICAL",
    },
    {
        "id": "PY_CLASS_MAX_LOC_800",
        "name": "Python class exceeds 800 LOC",
        "description": "Classes should not exceed 800 lines of code.",
        "engineId": ENGINE_ID,
        "cleanCodeAttribute": "FOCUSED",
        "type": "CODE_SMELL",
        "severity": "MAJOR",
    },
    {
        "id": "PY_CLASS_MAX_LOC_1200",
        "name": "Python class exceeds 1200 LOC",
        "description": "Classes must not exceed 1200 lines of code.",
        "engineId": ENGINE_ID,
        "cleanCodeAttribute": "FOCUSED",
        "type": "CODE_SMELL",
        "severity": "CRITICAL",
    },
    {
        "id": "PY_MODULE_TOP_LEVEL_MAX_LOC_100",
        "name": "Python module-level code exceeds 100 LOC",
        "description": "Module-level code outside classes and functions must not exceed 100 lines of code.",
        "engineId": ENGINE_ID,
        "cleanCodeAttribute": "FOCUSED",
        "type": "CODE_SMELL",
        "severity": "CRITICAL",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SonarQube generic external issues for Python LOC thresholds."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to analyze. Defaults to current directory.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the SonarQube generic issue JSON file to write.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory used to relativize file paths in the report. Defaults to current directory.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude. Can be passed multiple times.",
    )
    parser.add_argument(
        "--fail-on-parse-error",
        action="store_true",
        help="Exit with a non-zero code if a Python file cannot be parsed.",
    )
    return parser.parse_args()


def iter_python_files(paths: Sequence[str], excluded_dirs: set[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        if path.is_file() and path.suffix == ".py":
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved
            continue
        if path.is_dir():
            for file_path in path.rglob("*.py"):
                if any(part in excluded_dirs for part in file_path.parts):
                    continue
                resolved = file_path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield resolved


def attach_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            setattr(child, "parent", parent)


def build_executable_line_index(source: str) -> set[int]:
    executable_lines: set[int] = set()
    reader = io.StringIO(source).readline
    for token in tokenize.generate_tokens(reader):
        if token.type in {
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.COMMENT,
            tokenize.ENDMARKER,
        }:
            continue
        start_line = token.start[0]
        end_line = token.end[0]
        for line_no in range(start_line, end_line + 1):
            executable_lines.add(line_no)
    return executable_lines


def count_lines_in_range(executable_lines: set[int], start_line: int, end_line: int) -> int:
    return sum(1 for line_no in executable_lines if start_line <= line_no <= end_line)


def merge_intervals(intervals: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged: list[list[int]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        current = merged[-1]
        if start <= current[1] + 1:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def count_lines_in_intervals(executable_lines: set[int], intervals: Sequence[tuple[int, int]]) -> int:
    merged = merge_intervals(intervals)
    total = 0
    for start, end in merged:
        total += count_lines_in_range(executable_lines, start, end)
    return total


def relative_path(path: Path, base_dir: Path) -> str:
    try:
        rel = path.resolve().relative_to(base_dir.resolve())
        return rel.as_posix()
    except ValueError:
        return path.resolve().as_posix()


def safe_end_lineno(node: ast.AST) -> int:
    end_lineno = getattr(node, "end_lineno", None)
    lineno = getattr(node, "lineno", None)
    if end_lineno is None and lineno is not None:
        return lineno
    if end_lineno is None:
        raise ValueError(f"Node has no line information: {node!r}")
    return end_lineno


def function_label(node: ast.AST) -> str:
    parent = getattr(node, "parent", None)
    if isinstance(parent, ast.ClassDef):
        return f"method '{getattr(node, 'name', '<anonymous>')}'"
    return f"function '{getattr(node, 'name', '<anonymous>')}'"


def analyze_file(file_path: Path, base_dir: Path) -> tuple[list[Issue], list[str]]:
    source = file_path.read_text(encoding="utf-8")
    executable_lines = build_executable_line_index(source)
    parse_errors: list[str] = []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        parse_errors.append(f"{file_path}: syntax error: {exc.msg} at line {exc.lineno}")
        return [], parse_errors

    attach_parents(tree)
    issues: list[Issue] = []
    rel_path = relative_path(file_path, base_dir)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = node.lineno
            end_line = safe_end_lineno(node)
            loc = count_lines_in_range(executable_lines, start_line, end_line)
            if loc > FUNCTION_MAX_LOC:
                issues.append(
                    Issue(
                        rule_id="PY_FUNCTION_MAX_LOC_500",
                        message=(
                            f"{function_label(node)} has {loc} LOC; maximum allowed is {FUNCTION_MAX_LOC}."
                        ),
                        file_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        effort_minutes=max(20, (loc - FUNCTION_MAX_LOC) // 5),
                    )
                )
        elif isinstance(node, ast.ClassDef):
            start_line = node.lineno
            end_line = safe_end_lineno(node)
            loc = count_lines_in_range(executable_lines, start_line, end_line)
            if loc > CLASS_ERROR_MAX_LOC:
                issues.append(
                    Issue(
                        rule_id="PY_CLASS_MAX_LOC_1200",
                        message=(
                            f"class '{node.name}' has {loc} LOC; maximum allowed is {CLASS_ERROR_MAX_LOC}."
                        ),
                        file_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        effort_minutes=max(30, (loc - CLASS_ERROR_MAX_LOC) // 5),
                    )
                )
            elif loc > CLASS_WARN_MAX_LOC:
                issues.append(
                    Issue(
                        rule_id="PY_CLASS_MAX_LOC_800",
                        message=(
                            f"class '{node.name}' has {loc} LOC; warning threshold is {CLASS_WARN_MAX_LOC}."
                        ),
                        file_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        effort_minutes=max(20, (loc - CLASS_WARN_MAX_LOC) // 5),
                    )
                )

    top_level_intervals: list[tuple[int, int]] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if hasattr(stmt, "lineno"):
            top_level_intervals.append((stmt.lineno, safe_end_lineno(stmt)))

    module_level_loc = count_lines_in_intervals(executable_lines, top_level_intervals)
    if module_level_loc > MODULE_TOP_LEVEL_MAX_LOC and top_level_intervals:
        merged = merge_intervals(top_level_intervals)
        start_line = merged[0][0]
        end_line = merged[-1][1]
        issues.append(
            Issue(
                rule_id="PY_MODULE_TOP_LEVEL_MAX_LOC_100",
                message=(
                    "module-level code outside classes/functions "
                    f"has {module_level_loc} LOC; maximum allowed is {MODULE_TOP_LEVEL_MAX_LOC}."
                ),
                file_path=rel_path,
                start_line=start_line,
                end_line=end_line,
                effort_minutes=max(20, (module_level_loc - MODULE_TOP_LEVEL_MAX_LOC) // 3),
            )
        )

    issues.sort(key=lambda item: (item.file_path, item.start_line, item.rule_id))
    return issues, parse_errors


def to_sonar_report(issues: Sequence[Issue]) -> dict[str, object]:
    return {
        "rules": RULES,
        "issues": [
            {
                "ruleId": issue.rule_id,
                "effortMinutes": issue.effort_minutes,
                "primaryLocation": {
                    "message": issue.message,
                    "filePath": issue.file_path,
                    "textRange": {
                        "startLine": issue.start_line,
                        "endLine": issue.end_line,
                        "startColumn": issue.start_column,
                        "endColumn": issue.end_column,
                    },
                },
            }
            for issue in issues
        ],
    }


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir)
    excluded_dirs = DEFAULT_EXCLUDE_DIRS.union(args.exclude_dir)

    all_issues: list[Issue] = []
    parse_errors: list[str] = []

    for file_path in iter_python_files(args.paths, excluded_dirs):
        file_issues, file_errors = analyze_file(file_path, base_dir)
        all_issues.extend(file_issues)
        parse_errors.extend(file_errors)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(to_sonar_report(all_issues), indent=2) + "\n",
        encoding="utf-8",
    )

    if parse_errors:
        for error in parse_errors:
            print(error, file=sys.stderr)
        if args.fail_on_parse_error:
            return 2

    print(
        f"Wrote {len(all_issues)} issues to {output_path} "
        f"({len(parse_errors)} parse errors)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
