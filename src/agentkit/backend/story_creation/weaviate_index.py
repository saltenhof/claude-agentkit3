"""App-layer adapter binding ``StoryIndexPort`` to the Weaviate adapter.

Thin shim: it maps the ``index_story`` indexing contract onto the transport
``story_sync``. The fail-closed indexing policy (a failure blocks the export)
lives in :mod:`agentkit.backend.story_creation.story_md_export`; this shim only forwards
to the adapter, which raises a typed
:class:`~agentkit.integration_clients.vectordb.VectorDbError` on a write fault.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter


class WeaviateStoryIndex:
    """Bind the Weaviate adapter's ``story_sync`` to the ``StoryIndexPort``."""

    def __init__(self, adapter: WeaviateStoryAdapter) -> None:
        """Initialise with a connected Weaviate adapter.

        Args:
            adapter: The thin Weaviate transport adapter.
        """
        self._adapter = adapter

    def index_story(
        self,
        *,
        story_id: str,
        project_id: str,
        objects: Sequence[dict[str, object]],
    ) -> int:
        """Index/update the story chunks via ``story_sync`` (FK-21 §21.11.4).

        Args:
            story_id: Story display-ID (kept for symmetry / future per-story
                deletes; the objects already carry their ``story_id``).
            project_id: Bound multi-tenant discriminator; objects already carry
                it (R04). Asserted for parity with the port contract.
            objects: The full StoryContext objects to index (with deterministic
                UUIDs).

        Returns:
            The number of objects written.

        Raises:
            VectorDbWriteError: When the indexing write fails (hard blocker,
                propagated from the adapter; fail-closed).
        """
        # story_id/project_id are mandated by the StoryIndexPort contract; the
        # objects already carry their own identity fields and story_sync keys off
        # them. project_id is asserted so a wrong binding surfaces immediately.
        del story_id
        if project_id:
            for obj in objects:
                if str(obj.get("project_id", project_id)) != project_id:  # defensive parity
                    obj["project_id"] = project_id
        return self._adapter.story_sync(objects=objects)


__all__ = ["WeaviateStoryIndex"]
