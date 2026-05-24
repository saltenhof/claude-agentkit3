"""Domain exceptions for the skills BC (AG3-027, FK-43).

All exceptions inherit from AgentKitError so they carry a structured
``detail`` dict for programmatic inspection.
"""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class SkillError(AgentKitError):
    """Base error for all skills-BC operations."""


class SkillBindingFailedError(SkillError):
    """Raised when symlink creation fails during ``bind_skill``.

    Common causes on Windows: Developer Mode not enabled or the process
    lacks SeCreateSymbolicLinkPrivilege. Copying the bundle instead is
    explicitly forbidden by invariant ``project_binding_is_symlink_only``
    (formal.skills-and-bundles.invariants).

    To fix: enable Windows Developer Mode or run with elevated privileges.
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


class SkillBundleNotFoundError(SkillError):
    """Raised when ``SkillBundleStore.get_bundle`` cannot locate a bundle with
    the requested ``bundle_id``.
    """
