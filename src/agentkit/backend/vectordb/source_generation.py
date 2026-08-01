"""Persistent, strictly monotonic source-generation ownership ladder."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.record_fields import (
    iso,
    positive_int,
    required_strings,
    utc_clock,
)
from agentkit.backend.vectordb.sync import (
    ClaimSupersededError,
    ConcurrentSyncRejectedError,
    SourceClaim,
    parse_utc_timestamp,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from agentkit.backend.vectordb.client_port import CorpusClientPort

CLAIM_COLLECTION = "__agentkit_source_claims"
CLAIM_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "state",
    "owner_id",
    "generation",
    "claimed_at",
    "reclaimed_from",
    "reclaim_reason",
)
CLAIM_STATE_HELD: Final[str] = "claimed"
CLAIM_STATE_RELEASED: Final[str] = "released"
_CLAIM_NAMESPACE = uuid.UUID("9d6f3a4b-2c7e-5f8b-ad9c-3b2c4d5e6f7a")


def claim_record_uuid(project_id: str, source_file: str, generation: int) -> str:
    """Return the deterministic identity of a held generation record."""
    return str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}|{generation}"))


def release_marker_uuid(project_id: str, source_file: str, generation: int) -> str:
    """Return the deterministic identity of a generation release marker."""
    return str(
        uuid.uuid5(
            _CLAIM_NAMESPACE,
            f"{project_id}|{source_file}|{generation}|released",
        )
    )


@dataclass
class SourceGenerationLadder:
    """Arbitrate exclusive, monotonic write authority for each corpus source."""

    client: CorpusClientPort
    clock: Callable[[], datetime] = utc_clock

    def try_claim_source(self, *, project_id: str, source_file: str, owner_id: str) -> SourceClaim | None:
        """Atomically claim a source by CREATING the next source generation (N37).

        The claim is STORE-LEVEL and ATOMIC (N03/D3): each generation is a distinct
        record whose uuid folds in the generation number, so acquiring it is a
        compare-and-create the store arbitrates -- there is no read-then-write window
        in which two writers both observe "no claim" and both proceed.

        The generation ladder is PERSISTENT and STRICTLY MONOTONIC per
        ``(project_id, source_file)`` (N37): a normal release does not remove the
        ladder position, it adds an insert-only ``released`` marker, so the next
        acquisition allocates a strictly HIGHER number. Without that, a released
        claim used to reset the ladder to 1 and no ordering statement about "who
        wrote this object" was decidable at all.

        There is NO time-based takeover (N27/D3): a HELD generation rejects the
        writer, no matter how old it is. It is released only by its holder finishing
        or by the EXPLICIT :meth:`reclaim_source` path.
        """
        rows = self._generation_rows(project_id, source_file)
        highest = self._highest_generation(rows)
        if self._held_claim(project_id, source_file, rows) is not None:
            return None
        return self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=highest + 1,
        )

    def reclaim_source(self, *, project_id: str, source_file: str, owner_id: str, reason: str) -> SourceClaim:
        """ADMINISTRATIVELY take a claim over by creating the NEXT generation (N27).

        Only reached from an explicit operator path, which asserts the previous
        holder is dead. The takeover is a conditional CREATE of the next generation,
        so two concurrent reclaimers still produce exactly one winner, and the
        previous holder can never again delete data this generation writes (N37: its
        generation is strictly lower).
        """
        rows = self._generation_rows(project_id, source_file)
        held = self._held_claim(project_id, source_file, rows)
        generation = self._highest_generation(rows) + 1
        claim = self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            reclaimed_from=held.owner_id if held is not None else "",
            reason=reason,
        )
        if claim is None:
            raise ConcurrentSyncRejectedError(
                f"administrative reclaim of {(project_id, source_file)!r} lost the "
                f"race for generation {generation}; fail-closed (N27)."
            )
        return claim

    def _create_generation(
        self,
        *,
        project_id: str,
        source_file: str,
        owner_id: str,
        generation: int,
        reclaimed_from: str = "",
        reason: str = "",
    ) -> SourceClaim | None:
        """Conditionally CREATE one generation; ``None`` when it is already taken."""
        claimed_at = iso(self.clock())
        acquired = self.client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=claim_record_uuid(project_id, source_file, generation),
            properties={
                "project_id": project_id,
                "source_file": source_file,
                "state": CLAIM_STATE_HELD,
                "owner_id": owner_id,
                "generation": str(generation),
                "claimed_at": claimed_at,
                "reclaimed_from": reclaimed_from,
                "reclaim_reason": reason,
            },
        )
        if not acquired:
            return None
        self._prune_generations_below(project_id, source_file, generation)
        return SourceClaim(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            claimed_at=claimed_at,
            reclaimed_from=reclaimed_from,
        )

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Fence: the claim must still be the HELD generation (N15/N27).

        This check can be overtaken between here and the following mutation, which
        is why it is NOT what protects the destructive step -- that is bound
        storage-side to the generation ordering (N37).
        """
        held = self._held_claim(claim.project_id, claim.source_file)
        if held is None or held.generation != claim.generation or held.owner_id != claim.owner_id:
            raise ClaimSupersededError(
                f"source claim on {(claim.project_id, claim.source_file)!r} was "
                f"superseded (held generation {claim.generation} owner "
                f"{claim.owner_id!r}, active {held!r}); fail-closed (N15/N27)."
            )

    def release_source(self, *, claim: SourceClaim) -> None:
        """Release the held generation by ADDING its release marker (N37/N45).

        Insert-only: the ladder position survives, so the next acquisition of this
        source is strictly higher.

        The release is CONFIRMED, not best-effort (N45). A suppressed failure left the
        source held forever: the sync could publish its completion, fail to persist the
        marker, report success, and every later sync of that source would then be
        rejected until someone issued an administrative reclaim with no idea why. A
        release that did not land is therefore a typed, named fault.

        Raises:
            ClaimReleaseFailedError: When the marker could not be persisted, or the
                store denied it. An ALREADY EXISTING marker is success -- releasing
                twice is idempotent, not a fault.
        """
        from agentkit.backend.vectordb.sync import ClaimReleaseFailedError

        try:
            created = self.client.insert_object(
                collection=CLAIM_COLLECTION,
                uuid=release_marker_uuid(claim.project_id, claim.source_file, claim.generation),
                properties={
                    "project_id": claim.project_id,
                    "source_file": claim.source_file,
                    "state": CLAIM_STATE_RELEASED,
                    "owner_id": claim.owner_id,
                    "generation": str(claim.generation),
                    "claimed_at": iso(self.clock()),
                    "reclaimed_from": "",
                    "reclaim_reason": "",
                },
            )
        except (VectorDbUnavailableError, VectorDbWriteError) as exc:
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released ({exc}); it stays HELD and "
                "every later sync of it will be rejected until an administrative "
                "reclaim. Reported instead of suppressed (fail-closed, N45)."
            ) from exc
        if not created and not self._release_marker_exists(claim):
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released: the store neither created "
                "nor holds the release marker; it stays HELD (fail-closed, N45)."
            )

    def _release_marker_exists(self, claim: SourceClaim) -> bool:
        """Whether THIS generation's valid release marker is persisted (N45/N50).

        The deterministic uuid alone is not proof. Accepting any row stored at that id
        meant a malformed duplicate -- e.g. one carrying ``state=claimed`` -- made the
        sync report a successful release while the source stayed HELD, which is exactly
        the silent-success path N45 closed. The persisted record is therefore validated
        in FULL: it must be a ``released`` marker for this project, source, owner and
        generation. Anything else is not this claim's release.

        Args:
            claim: The claim whose release is being confirmed.

        Returns:
            ``True`` only for a complete, matching release marker.
        """
        wanted = release_marker_uuid(claim.project_id, claim.source_file, claim.generation)
        expected = {
            "project_id": claim.project_id,
            "source_file": claim.source_file,
            "state": CLAIM_STATE_RELEASED,
            "owner_id": claim.owner_id,
            "generation": str(claim.generation),
        }
        for uid, props in self._generation_rows(claim.project_id, claim.source_file):
            if uid != wanted:
                continue
            return all(props.get(name) == value for name, value in expected.items())
        return False

    def _prune_generations_below(self, project_id: str, source_file: str, generation: int) -> None:
        """Drop ladder records BELOW the given generation (housekeeping only).

        The record of the highest generation is never removed, so the ladder cannot
        reset -- that is the property the destructive delete depends on. Everything
        below it carries no decision any more.
        """
        import contextlib

        stale: list[str] = []
        for _uid, props in self._generation_rows(project_id, source_file):
            row_generation = positive_int(props.get("generation"), field_name="generation")
            if row_generation >= generation:
                continue
            stale.append(claim_record_uuid(project_id, source_file, row_generation))
            stale.append(release_marker_uuid(project_id, source_file, row_generation))
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=CLAIM_COLLECTION, uuids=stale)

    def _generation_rows(self, project_id: str, source_file: str) -> list[tuple[str, Mapping[str, object]]]:
        """Return this source's ladder records (claims AND release markers).

        Read with the SAME server-side project scope as the corpus (AC4/N51): the
        app-side filter that used to follow was not enough, because another project
        holding the same ``source_file`` still had to be transported and could push this
        read into the pagination ceiling.
        """
        return list(
            self.client.fetch_by_property(
                collection=CLAIM_COLLECTION,
                project_id=project_id,
                prop="source_file",
                value=source_file,
                return_props=CLAIM_PROPERTIES,
            )
        )

    @staticmethod
    def _highest_generation(rows: Sequence[tuple[str, Mapping[str, object]]]) -> int:
        """Return the highest generation EVER allocated for the source (N37).

        Release markers count: the ladder must not reset when a claim is released,
        or "written by an older generation" stops being decidable.
        """
        highest = 0
        for _uid, props in rows:
            highest = max(highest, positive_int(props.get("generation"), field_name="generation"))
        return highest

    def _held_claim(
        self,
        project_id: str,
        source_file: str,
        rows: Sequence[tuple[str, Mapping[str, object]]] | None = None,
    ) -> SourceClaim | None:
        """Return the currently HELD claim of a source, or ``None``.

        The highest generation decides: it is held when it has a ``claimed`` record
        and no ``released`` marker. Older generations carry no ownership any more.
        """
        ladder = list(rows) if rows is not None else self._generation_rows(project_id, source_file)
        highest = self._highest_generation(ladder)
        if highest == 0:
            return None
        claimed: SourceClaim | None = None
        for _uid, props in ladder:
            generation = positive_int(props.get("generation"), field_name="generation")
            if generation != highest:
                continue
            if props.get("state") == CLAIM_STATE_RELEASED:
                return None
            claimed = self._claim_from_props(project_id, source_file, props)
        return claimed

    @staticmethod
    def _claim_from_props(project_id: str, source_file: str, props: Mapping[str, object]) -> SourceClaim:
        """Rebuild a persisted claim strictly (owner/generation/timestamp, N15/N27/N37).

        There is NO expiry field: a claim never expires by time (N27). ``claimed_at``
        is diagnostics and must still be a valid UTC instant.
        """
        values = required_strings(props, ("owner_id", "state", "claimed_at"), context="source claim")
        if values["state"] not in (CLAIM_STATE_HELD, CLAIM_STATE_RELEASED):
            raise VectorDbUnavailableError(
                f"persisted source claim for {source_file!r} has unknown state {values['state']!r}; fail-closed (N15)."
            )
        parse_utc_timestamp(values["claimed_at"])
        reclaimed_from = props.get("reclaimed_from")
        return SourceClaim(
            project_id=project_id,
            source_file=source_file,
            owner_id=values["owner_id"],
            generation=positive_int(props.get("generation"), field_name="generation"),
            claimed_at=values["claimed_at"],
            reclaimed_from=reclaimed_from if isinstance(reclaimed_from, str) else "",
        )


__all__ = [
    "CLAIM_COLLECTION",
    "CLAIM_PROPERTIES",
    "CLAIM_STATE_HELD",
    "CLAIM_STATE_RELEASED",
    "SourceGenerationLadder",
    "claim_record_uuid",
    "release_marker_uuid",
]
