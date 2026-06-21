"""Repo-affinity resolution from the story body (FK-21 §21.9).

Deterministic app-layer derivation of ``participating_repos`` -- this is the
authoritative SOURCE of the affinity, replacing the prior consume-only usage.

Rules (FK-21 §21.9):

* **Strong evidence only (§21.9.1):** ONLY file paths listed under the story
  section ``## Betroffene Dateien`` count. Paths from logs, examples or prose
  references outside that section are ignored.
* **Longest-prefix-match (§21.9.2):** each listed path is matched against the
  configured ``repositories[]`` by the LONGEST matching path prefix.
* **Root/Docs fallback (§21.9.3):** when no direct paths are listed, the scope
  is derived from the story's ``module`` field.
* **Deterministic sort (§21.9.5):** hits per repo descending, ties broken
  lexicographically. All repos are equal; the first entry is purely the
  spawn-CWD anchor (FK-22 §22.6.4) and carries no business special role.
* **Human correction (§21.9.2):** the result is a PROPOSAL; a manually set
  affinity is not hard-overridden without a re-run (the caller decides whether
  to apply the proposal).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.config.models import ProjectConfig

#: Heading that opens the strong-evidence section (FK-21 §21.9.1).
#:
#: ARCH-55 corpus-data exception: this string is DELIBERATELY German because it
#: must byte-match the real ``## Betroffene Dateien`` heading in the German
#: story.md corpus (FK-21 §21.9.1, the only authoritative strong-evidence
#: section). It is not an operational identifier but a literal that parses
#: German Fachprosa input — translating it to English would silently stop
#: matching every real story.md and break repo-affinity resolution. Operational
#: identifiers in this module stay English per ARCH-55.
_AFFECTED_FILES_HEADING = "## Betroffene Dateien"

#: A markdown ATX heading line (any level), used to bound the section scan.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")

#: A path token inside the section: bullet/numbered list item, optional inline
#: code fences, capturing a forward-slash path. Backtick-wrapped paths and bare
#: bullets are both accepted; trailing prose after the path is dropped.
_PATH_LINE_RE = re.compile(
    r"^\s*(?:[-*+]|\d+\.)\s+`?(?P<path>[\w./-]+/[\w./-]+|[\w.-]+)`?",
)


@dataclass(frozen=True)
class RepoAffinityResult:
    """Result of :func:`resolve_repo_affinity` (FK-21 §21.9).

    Attributes:
        participating_repos: Deterministically ordered repo names (hits
            descending, then lexicographic). The first entry is the spawn-CWD
            anchor (no business special role). Empty only when neither strong
            evidence nor a module fallback resolved any repo. The entries are
            repo *names* (the ``participating_repos`` story attribute is keyed
            by name), even though the prefix MATCH is performed against the
            configured repo *path* (§21.9.2).
        hit_counts: Per-repo strong-evidence hit count (audit / determinism
            evidence). Empty on the module fallback path.
        used_module_fallback: ``True`` when no strong-evidence paths were found
            and the scope was derived from the ``module`` field (§21.9.3).
    """

    participating_repos: tuple[str, ...]
    hit_counts: dict[str, int]
    used_module_fallback: bool


def _extract_affected_paths(story_body: str) -> list[str]:
    """Extract file paths listed strictly under ``## Betroffene Dateien``.

    The scan starts AFTER the heading and stops at the next markdown heading of
    any level, so paths elsewhere in the body (logs, examples) are ignored
    (strong-evidence-only, FK-21 §21.9.1).
    """
    lines = story_body.splitlines()
    in_section = False
    paths: list[str] = []
    for line in lines:
        if not in_section:
            if line.strip() == _AFFECTED_FILES_HEADING:
                in_section = True
            continue
        # Inside the section: a new heading closes it.
        if _HEADING_RE.match(line):
            break
        match = _PATH_LINE_RE.match(line)
        if match:
            paths.append(match.group("path"))
    return paths


def _normalise_root(raw: str) -> str:
    """Normalise a repo path / affected path to a ``/``-delimited form.

    Backslashes are folded to forward slashes (so a Windows-configured
    ``repo.path`` still matches the POSIX-style paths listed in ``story.md``),
    a single ``./`` lead is dropped, and trailing slashes are stripped.
    """
    folded = raw.replace("\\", "/").strip()
    if folded.startswith("./"):
        folded = folded[2:]
    return folded.rstrip("/")


def _repo_prefixes(pipeline_config: ProjectConfig) -> list[tuple[str, str]]:
    """Return ``(repo_name, normalised_root)`` pairs for prefix matching.

    The match prefix is the repo's configured ``path`` (the real repo ROOT),
    NOT its display ``name`` (FK-21 §21.9.2: longest-prefix-match against the
    ``repositories[]`` entries; FK-46/FK-47 consistently key the multi-repo
    file-resolution off the configured ``repo_path``). The returned tuple keeps
    the repo ``name`` as the result key because ``participating_repos`` is a
    name-keyed story attribute, while the *root* is what the listed file paths
    are matched against.
    """
    pairs: list[tuple[str, str]] = []
    for repo in pipeline_config.repositories:
        root = _normalise_root(str(repo.path))
        pairs.append((repo.name, root))
    return pairs


def _match_repo(path: str, prefixes: list[tuple[str, str]]) -> str | None:
    """Return the repo whose configured ROOT is the LONGEST match (§21.9.2).

    A path matches a repo when it equals the repo root or sits under it
    (``root/``-prefixed). Empty roots (a repo configured at ``.``) match nothing
    here; the module fallback (§21.9.3) handles root/docs repos.
    """
    candidate = _normalise_root(path)
    best_name: str | None = None
    best_len = -1
    for name, root in prefixes:
        if not root:
            continue
        if (candidate == root or candidate.startswith(f"{root}/")) and len(root) > best_len:
            best_name = name
            best_len = len(root)
    return best_name


def _sorted_repos(hit_counts: dict[str, int]) -> tuple[str, ...]:
    """Sort repos by hits descending, then lexicographically (§21.9.5)."""
    return tuple(
        sorted(hit_counts, key=lambda name: (-hit_counts[name], name))
    )


def resolve_repo_affinity(
    story_body: str,
    pipeline_config: ProjectConfig,
    *,
    module: str = "",
) -> RepoAffinityResult:
    """Resolve ``participating_repos`` from the story body (FK-21 §21.9).

    Args:
        story_body: The full story markdown body.
        pipeline_config: The project config carrying ``repositories[]`` (the FK
            signature names it ``pipeline_config``; in this codebase the
            ``repositories[]`` owner is ``ProjectConfig``).
        module: The story's ``module`` field, used for the root/docs fallback
            when no strong-evidence paths are listed (§21.9.3).

    Returns:
        A deterministic :class:`RepoAffinityResult` (a proposal; never a hard
        override of a manually set affinity).
    """
    prefixes = _repo_prefixes(pipeline_config)
    paths = _extract_affected_paths(story_body)

    hit_counts: dict[str, int] = {}
    for path in paths:
        repo = _match_repo(path, prefixes)
        if repo is not None:
            hit_counts[repo] = hit_counts.get(repo, 0) + 1

    if hit_counts:
        return RepoAffinityResult(
            participating_repos=_sorted_repos(hit_counts),
            hit_counts=hit_counts,
            used_module_fallback=False,
        )

    # Root/Docs fallback (§21.9.3): derive the scope from the module field by
    # longest-prefix-matching it against the configured repos.
    fallback = _match_repo(module, prefixes) if module else None
    if fallback is not None:
        return RepoAffinityResult(
            participating_repos=(fallback,),
            hit_counts={},
            used_module_fallback=True,
        )

    return RepoAffinityResult(
        participating_repos=(),
        hit_counts={},
        used_module_fallback=bool(module),
    )


__all__ = [
    "RepoAffinityResult",
    "resolve_repo_affinity",
]
