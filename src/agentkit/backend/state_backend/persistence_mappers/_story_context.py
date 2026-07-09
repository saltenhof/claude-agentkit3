"""Story-context row mappers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import CorruptStateError

from ._common import dump_json

if TYPE_CHECKING:
    from agentkit.backend.story_context_manager.models import StoryContext



def story_context_to_row(ctx: StoryContext) -> dict[str, Any]:
    """Convert a ``StoryContext`` to a DB-insertable row dict."""

    return {
        "story_uuid": str(ctx.story_uuid),
        "project_key": ctx.project_key,
        "story_number": ctx.story_number,
        "story_id": ctx.story_id,
        "story_type": ctx.story_type.value,
        "execution_route": (
            ctx.execution_route.value
            if ctx.execution_route is not None
            else None
        ),
        "implementation_contract": (
            ctx.implementation_contract.value
            if ctx.implementation_contract is not None
            else None
        ),
        "title": ctx.title,
        "payload_json": dump_json(ctx.model_dump(mode="json")),
    }



def story_context_payload_to_record(
    payload_json: str,
    db_label: str = "unknown",
) -> StoryContext:
    """Deserialize a ``StoryContext`` from its JSON payload."""

    from agentkit.backend.story_context_manager.models import StoryContext as _StoryContext

    try:
        return _StoryContext.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"story_contexts payload is invalid in {db_label}: {exc}",
        ) from exc
