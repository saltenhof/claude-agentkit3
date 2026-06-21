"""Domain exceptions for the skills BC (AG3-027, FK-43).

All exceptions inherit from AgentKitError so they carry a structured
``detail`` dict for programmatic inspection.
"""

from __future__ import annotations

from agentkit.backend.exceptions import AgentKitError


class SkillError(AgentKitError):
    """Base error for all skills-BC operations."""


class SkillBindingFailedError(SkillError):
    """Raised when the binding link cannot be created during ``bind_skill``.

    The binding is a thin filesystem link — a symbolic link on POSIX, a
    directory junction on Windows (FK-43 §43.4.1.1). Copying the bundle instead
    is explicitly forbidden by invariant ``project_binding_is_link_only``
    (formal.skills-and-bundles.invariants); on any OS-level link failure this is
    raised rather than falling back to a copy.

    The Windows junction needs no Developer Mode and no
    ``SeCreateSymbolicLinkPrivilege``, so this is not the usual Windows-symlink
    privilege failure; the underlying ``OSError`` is carried in ``detail``.
    """


class SkillBindingPartialStateError(SkillBindingFailedError):
    """Raised when ``bind_skill`` failed AND its self-atomic cleanup could NOT
    fully undo the partial state (AG3-048 Codex-r4 FINDING 1).

    This is the HONEST counterpart to a clean ``SkillBindingFailedError``: the
    bind failed and the compensating cleanup left residual side effects behind
    (one or more harness links could not be detached, and/or the persisted
    binding row could not be deleted). The caller MUST NOT mistake this for a
    fully-clean failure — the leftover state needs operator/installer attention.

    The ``detail`` dict carries:

    * ``residual_links`` — list of binding-link paths that could not be removed.
    * ``persisted_row_remains`` — ``True`` when the binding row delete failed.
    * ``original_error`` — string form of the error that caused the bind to fail.

    It subclasses ``SkillBindingFailedError`` so existing ``except
    SkillBindingFailedError`` handlers still catch it, but its distinct type and
    detail surface the residual partial state explicitly.
    """


class SkillBundleDigestMismatchError(SkillError):
    """Raised when the bundle manifest digest does not match the expected value.

    Indicates that the bundle at ``bundle_root`` has been tampered with or
    is corrupt.
    """


class SkillProfileNotSupportedError(SkillError):
    """Raised when the requested ``SkillProfile`` is not present in a bundle's
    variant map.

    The caller must either choose a supported profile or supply a bundle that
    carries the required variant.
    """


class UnknownPlaceholderError(SkillError):
    """Raised by ``PlaceholderSubstitutor`` when an unrecognised placeholder
    token is encountered in content (fail-closed per FK-43 §43.4.2).

    The ``detail`` dict contains ``placeholder`` (the raw token string) and
    ``supported`` (list of known placeholder names).
    """


class SkillQualityMetricSourceUnavailableError(SkillError):
    """Raised when quality metrics are requested without a projection accessor."""


class UnknownSkillNameError(SkillError):
    """Raised when quality metrics are requested for a non-catalogued skill."""


class SkillBundleNotFoundError(SkillError):
    """Raised when ``SkillBundleStore.get_bundle`` cannot locate a bundle with
    the requested ``bundle_id``.
    """


class SkillBundleCorruptError(SkillError):
    """Raised when a REQUESTED bundle directory exists but its manifest is
    unreadable/malformed (AG3-048 Codex-r3, fail-closed discovery).

    Distinct from ``SkillBundleNotFoundError``: the bundle directory is
    present, so the operator must be told the bundle is CORRUPT (with the
    offending manifest path and parse error) rather than being misled into
    thinking it was never shipped. Discovery never silently downgrades to an
    older parseable version when the highest version is corrupt.

    The ``detail`` dict carries ``bundle_id``, ``manifest_path`` and
    ``parse_error``.
    """
