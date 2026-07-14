"""Stable text rendering for W2 CLI results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concept_governance.models import AuthorityRunResult


def render_result(result: AuthorityRunResult) -> str:
    """Render every error and baselined report without silent suppression."""
    errors = sum(item.severity == "ERROR" for item in result.findings)
    reports = len(result.findings) - errors
    lines = [
        f"concept-authority-prose: {'PASS' if result.ok else 'ERROR'} "
        f"(errors={errors}, reports={reports})"
    ]
    for item in result.findings:
        lines.append(
            f"[{item.severity}] {item.code} {item.doc}#{item.anchor} "
            f"scope={item.scope!r} assertion={item.assertion!r} "
            f"prompt={item.prompt_version} model={item.model}: {item.message}"
        )
    return "\n".join(lines)
