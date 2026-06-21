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
        objects: Sequence[dict[str, object]],
    ) -> int:
        """Index/update the story chunks via ``story_sync`` (FK-21 §21.11.4).

        Args:
            story_id: Story display-ID (kept for symmetry / future per-story
                deletes; the objects already carry their ``story_id``).
            objects: The story chunks to index.

        Returns:
            The number of objects written.

        Raises:
            VectorDbWriteError: When the indexing write fails (hard blocker,
                propagated from the adapter; fail-closed).
        """
        # story_id is mandated by the StoryIndexPort contract but not consulted
        # here: the objects already carry their own story_id, and story_sync
        # keys off that. Kept for symmetry / future per-story deletes.
        del story_id
        return self._adapter.story_sync(objects=objects)


__all__ = ["WeaviateStoryIndex"]
