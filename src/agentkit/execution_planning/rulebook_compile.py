"""Official rulebook compile step + admin-only revision update (FK-70 §70.7d).

The rulebook is an INPUT artifact, never direct runtime truth. This module owns:

* ``compile_rulebook`` -- the official compile step that translates raw rulebook
  syntax into the canonical ``CompiledRulebook`` wrapped in a
  ``RulebookCompileResult`` (raw -> canonical). A successful compile mandates an
  official RE-PLAN (``triggers_replan``), not a hot-reload (§70.7d #5). A syntax
  error yields a ``REJECTED`` result and never becomes runtime truth (FAIL-CLOSED).
* ``update_rulebook_revision`` -- the ONLY sanctioned mutation entry point. It
  requires an admin/control-plane principal (§70.7d #6); free agent mutation is
  rejected with ``RulebookMutationNotAuthorizedError``. It increments
  ``rulebook_revision`` monotonically and persists both the new revision and its
  compile result through the planning projection write path.

DSL boundary (§70.7d): the rulebook DSL parsed here is NOT the FK-20
``FlowDefinition`` DSL; this module imports nothing from the pipeline-framework
flow DSL.

Sources:
- FK-70 §70.7d -- compile step, rulebook_revision, re-plan-not-hot-reload,
  admin/control-plane-only mutation, FlowDefinition distinction
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.exceptions import AgentKitError
from agentkit.execution_planning.persistence.records import (
    RulebookCompileResultRecord,
    RulebookRevisionRecord,
)
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.execution_planning.planning_model.rulebook import (
    CompiledRulebook,
    RulebookCompileResult,
    RulebookCompileStatus,
    RulebookRevision,
    RulebookSchedulingRule,
)

if TYPE_CHECKING:
    from agentkit.execution_planning.audit import PlanningAuditEmitter
    from agentkit.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )

__all__ = [
    "RulebookMutationNotAuthorizedError",
    "RulebookUpdateOutcome",
    "compile_rulebook",
    "update_rulebook_revision",
]

# Closed admin/control-plane principal prefixes (FK-70 §70.7d #6). A rulebook may
# only be updated through an official admin/control-plane principal, never by free
# agent mutation in the project.
_ADMIN_PRINCIPAL_PREFIXES: tuple[str, ...] = ("admin:", "control-plane:")

# Canonical rulebook-rule keywords (the rulebook DSL maps ONLY onto canonical
# FK-70 primitives; it never replaces them, §70.7d #3).
_RULE_KEYWORDS: frozenset[str] = frozenset(
    {"parallelize", "serialize", "priority", "conflict"}
)


class RulebookMutationNotAuthorizedError(AgentKitError):
    """Raised when a non-admin principal attempts to mutate a rulebook.

    FK-70 §70.7d #6: a rulebook may only be updated via the official
    admin/control-plane path. FAIL-CLOSED on free agent mutation.
    """

    def __init__(self, *, principal: str) -> None:
        super().__init__(
            f"Rulebook mutation not authorized for principal {principal!r}: "
            "only admin/control-plane principals may update a rulebook "
            "(FK-70 §70.7d #6).",
            detail={"principal": principal},
        )
        self.principal = principal


def _is_admin_principal(principal: str) -> bool:
    return any(principal.startswith(prefix) for prefix in _ADMIN_PRINCIPAL_PREFIXES)


def compile_rulebook(revision: RulebookRevision) -> RulebookCompileResult:
    """Translate a raw rulebook revision into the canonical compiled model.

    The official compile step (§70.7d #4): raw syntax -> canonical
    ``CompiledRulebook``. Each non-empty, non-comment line must be
    ``<keyword> <story_id>[ <story_id>...][ # detail]`` with ``keyword`` from the
    canonical rule vocabulary. A malformed line yields a ``REJECTED`` result with
    errors and no compiled form (FAIL-CLOSED: a rejected rulebook is never runtime
    truth). A successful compile mandates a re-plan, not a hot-reload.

    Args:
        revision: The raw rulebook revision to compile.

    Returns:
        A ``RulebookCompileResult`` (``COMPILED`` with rules + ``triggers_replan``,
        or ``REJECTED`` with errors).
    """
    rules: list[RulebookSchedulingRule] = []
    errors: list[str] = []

    for line_no, raw_line in enumerate(revision.raw_syntax.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, detail_part = line.partition("#")
        tokens = body.split()
        if len(tokens) < 2:
            errors.append(f"line {line_no}: expected '<keyword> <story_id>...'")
            continue
        keyword = tokens[0].lower()
        if keyword not in _RULE_KEYWORDS:
            errors.append(
                f"line {line_no}: unknown rule keyword {tokens[0]!r} "
                f"(allowed: {', '.join(sorted(_RULE_KEYWORDS))})"
            )
            continue
        rules.append(
            RulebookSchedulingRule(
                rule_kind=keyword,
                story_ids=tuple(tokens[1:]),
                detail=detail_part.strip() or None,
            )
        )

    compiled_at = datetime.now(UTC)
    if errors:
        return RulebookCompileResult(
            project_key=revision.project_key,
            rulebook_id=revision.rulebook_id,
            revision=revision.revision,
            status=RulebookCompileStatus.REJECTED,
            compiled=None,
            errors=tuple(errors),
            triggers_replan=False,
            compiled_at=compiled_at,
        )
    return RulebookCompileResult(
        project_key=revision.project_key,
        rulebook_id=revision.rulebook_id,
        revision=revision.revision,
        status=RulebookCompileStatus.COMPILED,
        compiled=CompiledRulebook(
            project_key=revision.project_key,
            rulebook_id=revision.rulebook_id,
            revision=revision.revision,
            rules=tuple(rules),
        ),
        errors=(),
        triggers_replan=True,
        compiled_at=compiled_at,
    )


class RulebookUpdateOutcome:
    """Outcome of an official rulebook update (revision + compile result).

    Attributes:
        revision: The newly persisted rulebook revision.
        compile_result: The compile result for the new revision.
    """

    __slots__ = ("compile_result", "revision")

    def __init__(
        self,
        *,
        revision: RulebookRevision,
        compile_result: RulebookCompileResult,
    ) -> None:
        self.revision = revision
        self.compile_result = compile_result

    @property
    def triggers_replan(self) -> bool:
        """Whether this update mandates an official re-plan (not a hot-reload)."""
        return self.compile_result.triggers_replan


def update_rulebook_revision(
    *,
    project_key: str,
    rulebook_id: str,
    raw_syntax: str,
    principal: str,
    accessor: PlanningProjectionAccessor,
    current_revision: int,
    audit: PlanningAuditEmitter | None = None,
    audit_story_id: str | None = None,
) -> RulebookUpdateOutcome:
    """Update a rulebook via the admin/control-plane path only (FK-70 §70.7d #6).

    Increments ``rulebook_revision`` monotonically, compiles the new raw syntax
    and persists both the new ``rulebook_revision`` and its
    ``rulebook_compile_result`` through the planning projection write path. A
    successful compile signals an official re-plan (``triggers_replan``), never a
    hot-reload. Optionally emits the ``rulebook_compiled`` audit event.

    Args:
        project_key: Tenant/project scope key.
        rulebook_id: Stable rulebook identity.
        raw_syntax: The new raw rulebook source.
        principal: The updating principal; must be admin/control-plane.
        accessor: The planning projection write path.
        current_revision: The current highest revision (0 if none yet).
        audit: Optional audit emitter for ``rulebook_compiled``.
        audit_story_id: Story id used for the audit event scope (required if
            ``audit`` is given).

    Returns:
        A ``RulebookUpdateOutcome`` with the new revision and its compile result.

    Raises:
        RulebookMutationNotAuthorizedError: If ``principal`` is not admin/control-plane.
    """
    if not _is_admin_principal(principal):
        raise RulebookMutationNotAuthorizedError(principal=principal)

    new_revision_no = current_revision + 1
    revision = RulebookRevision(
        project_key=project_key,
        rulebook_id=rulebook_id,
        revision=new_revision_no,
        raw_syntax=raw_syntax,
        updated_by_principal=principal,
        created_at=datetime.now(UTC),
    )
    compile_result = compile_rulebook(revision)

    accessor.write_projection(
        PlanningSchemaKind.RULEBOOK_REVISION,
        RulebookRevisionRecord(
            project_key=revision.project_key,
            rulebook_id=revision.rulebook_id,
            revision=revision.revision,
            raw_syntax=revision.raw_syntax,
            updated_by_principal=revision.updated_by_principal,
            created_at=revision.created_at.isoformat(),
        ),
    )
    accessor.write_projection(
        PlanningSchemaKind.RULEBOOK_COMPILE_RESULT,
        _compile_result_to_record(compile_result),
    )

    if audit is not None and audit_story_id is not None:
        audit.rulebook_compiled(
            story_id=audit_story_id,
            rulebook_id=rulebook_id,
            project_key=project_key,
        )
        # Re-plan trigger (FK-70 §70.6.2a): a rulebook change mandates an official
        # re-plan, not a hot-reload. When the new revision compiles successfully
        # (``triggers_replan``) this IS the AG3-099-scoped re-plan trigger, so we
        # emit ``plan_revised`` here. (Scheduling/gate/wave re-plan triggers are
        # AG3-100-scoped and are NOT emitted from this story.)
        if compile_result.triggers_replan:
            audit.plan_revised(
                story_id=audit_story_id,
                plan_id=f"{project_key}:{rulebook_id}:rev{new_revision_no}",
                trigger="rulebook_compiled",
                project_key=project_key,
            )

    return RulebookUpdateOutcome(revision=revision, compile_result=compile_result)


def _compile_result_to_record(
    result: RulebookCompileResult,
) -> RulebookCompileResultRecord:
    import json

    compiled_rules = (
        [rule.model_dump(mode="json") for rule in result.compiled.rules]
        if result.compiled is not None
        else []
    )
    return RulebookCompileResultRecord(
        project_key=result.project_key,
        rulebook_id=result.rulebook_id,
        revision=result.revision,
        status=result.status.value,
        compiled_rules_json=json.dumps(compiled_rules),
        errors_json=json.dumps(list(result.errors)),
        triggers_replan=result.triggers_replan,
        compiled_at=result.compiled_at.isoformat(),
    )
