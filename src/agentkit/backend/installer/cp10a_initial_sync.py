"""CP10a adapter: mandatory initial sync through the AG3-174 engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, model_validator

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.file_ops import atomic_write_text
from agentkit.backend.vectordb.commit_recovery import project_commit_recovery_journal
from agentkit.backend.vectordb.engine import compose_runtime
from agentkit.backend.vectordb.mcp_server import McpToolService
from agentkit.backend.vectordb.runtime_binding import RuntimeBindingError
from agentkit.backend.vectordb.sync import CommitOutcomeUnknownError, SyncError
from agentkit.integration_clients.vectordb.errors import VectorDbError

if TYPE_CHECKING:
    from agentkit.backend.vectordb.engine import CorpusClientPort

_RECEIPT_DIR = Path(".agentkit") / "receipts" / "vectordb"

#: Durable INTENT FENCE around the "commit + publish both receipts" span.
#: Written BEFORE the completion commit and removed only once BOTH receipts are
#: on disk. Its presence therefore does NOT assert that the corpus moved — it
#: asserts that nobody can currently prove the local pair matches it. That is
#: what makes the pair transactional *for readers*: any abort inside the span
#: (before the commit, after it, or between the two writes) leaves the fence
#: behind and every reader fails closed. A marker written afterwards could not
#: cover the very gap it exists for.
_PUBLICATION_MARKER = _RECEIPT_DIR / "publication-pending.json"


class PreparedInitialSyncPort(Protocol):
    """A run whose engine completions are retained until commit."""

    story_result: dict[str, object]
    concept_result: dict[str, object]

    def commit(self) -> None: ...

    def abort(self) -> None: ...


class SyncServicePort(Protocol):
    """The already-landed run-wide engine surface consumed by CP10a."""

    def prepare_initial_sync(self) -> PreparedInitialSyncPort: ...


#: The source types each producer owns (FK-13 §13.9.9). Fixed per tool: a
#: receipt that claims a foreign corpus is evidence of a mixed-up producer,
#: not a variant worth tolerating.
_TOOL_SOURCE_TYPES: dict[str, tuple[str, ...]] = {
    "story_sync": ("story", "research"),
    "concept_sync": ("concept",),
}


class InitialSyncReceipt(BaseModel):
    """Strict durable evidence for one CP10a full reindex.

    The field constraints are the FK-13 §13.9.9 contract, enforced on read as
    well as on write: a receipt is durable evidence, and evidence that is only
    checked when it is produced proves nothing about the file found later.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    project_id: StrictStr = Field(min_length=1)
    tool: Literal["story_sync", "concept_sync"]
    source_types: tuple[StrictStr, ...]
    discovered: StrictInt = Field(ge=0)
    unchanged: StrictInt = Field(ge=0)
    upserted: StrictInt = Field(ge=0)
    deleted: StrictInt = Field(ge=0)
    failed: StrictInt = Field(ge=0, le=0)
    empty_corpus: StrictBool
    start_revision: StrictStr
    end_revision: StrictStr = Field(min_length=1)
    status: Literal["success"]

    @model_validator(mode="after")
    def _source_types_belong_to_the_tool(self) -> InitialSyncReceipt:
        """Reject a receipt whose corpus does not belong to its producer."""
        expected = _TOOL_SOURCE_TYPES[self.tool]
        if self.source_types != expected:
            raise ValueError(
                f"{self.tool} receipt must carry source_types {expected}, got {self.source_types}"
            )
        return self

    @model_validator(mode="after")
    def _empty_corpus_matches_the_discovery_side(self) -> InitialSyncReceipt:
        """Tie ``empty_corpus`` to what was actually discovered (FK-13 §13.9.9).

        ``empty_corpus`` is not an independent opinion about the run — it is
        exactly "discovery found nothing". ``deleted`` stays free: a corpus that
        just became empty still removes its old chunks, and that is the one
        counter which legitimately stays positive.
        """
        if self.empty_corpus != (self.discovered == 0):
            raise ValueError(
                f"empty_corpus={self.empty_corpus} contradicts discovered={self.discovered}"
            )
        if self.empty_corpus and (self.unchanged, self.upserted) != (0, 0):
            raise ValueError(
                f"an empty corpus cannot report unchanged={self.unchanged} / upserted={self.upserted}"
            )
        return self


@dataclass(frozen=True)
class InitialSyncOutcome:
    receipts: tuple[InitialSyncReceipt, InitialSyncReceipt]
    changed: bool


def _service(
    project_root: Path,
    project_config: object,
    *,
    client: CorpusClientPort | None,
) -> McpToolService:
    from agentkit.backend.config.models import ProjectConfig

    if not isinstance(project_config, ProjectConfig):
        raise InstallationError("CP10a requires the validated ProjectConfig")
    vectordb = project_config.pipeline.vectordb
    if vectordb is None or vectordb.weaviate_http_endpoint is None or vectordb.weaviate_grpc_endpoint is None:
        raise InstallationError("CP10a requires both validated VectorDB endpoints")
    project_id = project_config.project_prefix
    if not isinstance(project_id, str) or not project_id:
        raise InstallationError("CP10a requires the validated project_prefix")
    env = {
        "PROJECT_ID": project_id,
        "WEAVIATE_HTTP_ENDPOINT": vectordb.weaviate_http_endpoint,
        "WEAVIATE_GRPC_ENDPOINT": vectordb.weaviate_grpc_endpoint,
        "AGENTKIT_CONCEPTS_DIR": str(project_root / project_config.concepts_dir),
        "AGENTKIT_STORIES_DIR": str(project_root / project_config.wiki_stories_dir),
    }
    composed = compose_runtime(
        env,
        concepts_dir=project_root / project_config.concepts_dir,
        stories_dir=project_root / project_config.wiki_stories_dir,
        client=client,
        cwd=str(project_root),
    )
    if not isinstance(composed, McpToolService):
        raise InstallationError("VectorDB composition returned an invalid service")
    return composed


def _load_receipt(
    path: Path,
    *,
    expected_tool: str,
    expected_project_id: str | None = None,
) -> InitialSyncReceipt:
    """Read one receipt and bind it to the producer and project it claims.

    Every read path goes through here. A receipt is only evidence if the file
    it was found in belongs to the producer that wrote it and to the project
    being installed — otherwise a receipt carried over from elsewhere would be
    accepted as a valid before-image and its revisions chained onto a foreign
    corpus.
    """
    try:
        receipt = InitialSyncReceipt.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise InstallationError(f"Invalid existing CP10a receipt {path}: {exc}") from exc
    if receipt.tool != expected_tool:
        raise InstallationError(f"CP10a receipt {path} carries the wrong producer: {receipt.tool}")
    if expected_project_id is not None and receipt.project_id != expected_project_id:
        raise InstallationError(
            f"CP10a receipt {path} belongs to project {receipt.project_id!r}, not {expected_project_id!r}"
        )
    return receipt


def _old_receipt(
    path: Path,
    *,
    expected_tool: str,
    expected_project_id: str | None = None,
) -> InitialSyncReceipt | None:
    if not path.is_file():
        return None
    return _load_receipt(path, expected_tool=expected_tool, expected_project_id=expected_project_id)


def _strict_counter(result: dict[str, object], key: str) -> int:
    if key not in result:
        raise InstallationError(f"VectorDB {key!r} counter is missing")
    value = result[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InstallationError(f"VectorDB {key!r} counter is not a non-negative int")
    return value


def _receipt(
    *,
    tool: Literal["story_sync", "concept_sync"],
    source_types: tuple[str, ...],
    result: dict[str, object],
    start_revision: str,
) -> InitialSyncReceipt:
    error = result.get("error")
    if error is not None:
        raise InstallationError(f"{tool} failed without publishing freshness: {error}: {result.get('detail', '')}")
    project_id = result.get("project_id")
    end_revision = result.get("corpus_revision")
    if not isinstance(project_id, str) or not project_id:
        raise InstallationError(f"{tool} returned no valid project_id")
    if not isinstance(end_revision, str):
        raise InstallationError(f"{tool} returned no valid corpus_revision")
    discovered = _strict_counter(result, "synced_sources")
    upserted = _strict_counter(result, "written")
    deleted = _strict_counter(result, "deleted")
    unchanged = _strict_counter(result, "unchanged")
    failed = _strict_counter(result, "failed")
    if failed:
        raise InstallationError(f"{tool} reported {failed} failed sources")
    return InitialSyncReceipt(
        project_id=project_id,
        tool=tool,
        source_types=source_types,
        discovered=discovered,
        unchanged=unchanged,
        upserted=upserted,
        deleted=deleted,
        failed=failed,
        empty_corpus=discovered == 0,
        start_revision=start_revision,
        end_revision=end_revision,
        status="success",
    )


def _render(receipt: InitialSyncReceipt) -> str:
    return json.dumps(receipt.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"


def _restore(path: Path, before: bytes | None) -> None:
    if before is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(before)


def _publish_pair(
    first_path: Path,
    first_text: str,
    second_path: Path,
    second_text: str,
    *,
    before_first: bytes | None,
    before_second: bytes | None,
) -> bool:
    if before_first == first_text.encode("utf-8") and before_second == second_text.encode("utf-8"):
        return False
    try:
        atomic_write_text(first_path, first_text, newline="")
        atomic_write_text(second_path, second_text, newline="")
    except OSError as write_exc:
        restoration_errors: list[str] = []
        for path, before in (
            (first_path, before_first),
            (second_path, before_second),
        ):
            try:
                _restore(path, before)
            except OSError as restore_exc:
                restoration_errors.append(f"{path}: {restore_exc}")
        if restoration_errors:
            raise InstallationError(
                "CP10a receipt publication failed and exact restoration failed: " + "; ".join(restoration_errors)
            ) from write_exc
        raise InstallationError("CP10a receipt publication failed; previous bytes were restored exactly") from write_exc
    return True


def _prepare_receipts(
    prepared: PreparedInitialSyncPort,
    old_story: InitialSyncReceipt | None,
    old_concept: InitialSyncReceipt | None,
) -> tuple[InitialSyncReceipt, InitialSyncReceipt]:
    try:
        story_receipt = _receipt(
            tool="story_sync",
            source_types=("story", "research"),
            result=prepared.story_result,
            start_revision=old_story.end_revision if old_story is not None else "",
        )
        concept_receipt = _receipt(
            tool="concept_sync",
            source_types=("concept",),
            result=prepared.concept_result,
            start_revision=old_concept.end_revision if old_concept is not None else "",
        )
    except InstallationError:
        prepared.abort()
        raise
    return story_receipt, concept_receipt


def _publish_receipts(
    prepared: PreparedInitialSyncPort,
    paths: tuple[Path, Path],
    before: tuple[bytes | None, bytes | None],
    old: tuple[InitialSyncReceipt | None, InitialSyncReceipt | None],
    candidate: tuple[InitialSyncReceipt, InitialSyncReceipt],
) -> tuple[tuple[InitialSyncReceipt, InitialSyncReceipt], bool]:
    old_story, old_concept = old
    story_receipt, concept_receipt = candidate
    if (
        old_story is not None
        and old_concept is not None
        and old_story.end_revision == story_receipt.end_revision
        and old_concept.end_revision == concept_receipt.end_revision
    ):
        return (old_story, old_concept), False
    # No ``prepared.abort()`` here: publication runs AFTER the completion commit,
    # so there is nothing left to abort. A half-failed publication restores the
    # exact previous bytes of both files and reports honestly; the corpus state
    # has already advanced and the next run republishes the missing evidence.
    changed = _publish_pair(
        paths[0],
        _render(story_receipt),
        paths[1],
        _render(concept_receipt),
        before_first=before[0],
        before_second=before[1],
    )
    return candidate, changed


def _commit_prepared(
    prepared: PreparedInitialSyncPort,
    paths: tuple[Path, Path],
    before: tuple[bytes | None, bytes | None],
    marker: Path,
) -> None:
    try:
        prepared.commit()
    except CommitOutcomeUnknownError as exc:
        prepared.abort()
        # The window stays OPEN on purpose: nobody observed whether the corpus
        # moved, so the receipts on disk cannot be certified either way.
        raise InstallationError(
            "CP10a completion outcome is commit_outcome_unknown; the local "
            "receipts, the publication window and the durable recovery journal "
            "were retained, and the outcome must be resolved before the next "
            "corpus mutation"
        ) from exc
    except (SyncError, VectorDbError) as exc:
        prepared.abort()
        restoration_errors: list[str] = []
        for path, old_bytes in zip(paths, before, strict=True):
            try:
                _restore(path, old_bytes)
            except OSError as restore_exc:
                restoration_errors.append(f"{path}: {restore_exc}")
        if restoration_errors:
            raise InstallationError(
                "CP10a engine completion failed and local receipt restoration "
                "failed: "
                + "; ".join(restoration_errors)
            ) from exc
        # The commit definitively did NOT happen and the local bytes are back to
        # their exact before-image: corpus and receipts agree again, so the
        # window is closed rather than left as a phantom blocker.
        _close_publication_window(marker)
        raise InstallationError(
            "CP10a engine completion failed; local receipt bytes and authoritative "
            "freshness were restored exactly"
        ) from exc


def run_initial_sync(
    project_root: Path,
    project_config: object,
    *,
    service: SyncServicePort | None = None,
    client: CorpusClientPort | None = None,
) -> InitialSyncOutcome:
    """Run both full reindexes, then atomically publish their local evidence."""
    receipt_dir = project_root / _RECEIPT_DIR
    story_path = receipt_dir / "story_sync.json"
    concept_path = receipt_dir / "concept_sync.json"
    from agentkit.backend.config.models import ProjectConfig

    if not isinstance(project_config, ProjectConfig):
        raise InstallationError("CP10a requires the validated ProjectConfig")
    # Deliberately NO unresolved-completion guard here: this is the path that
    # RESOLVES a pending outcome. Blocking it would wedge the project forever.
    # The guard belongs on the evidence readers (verify), not on the resolver.
    expected_project_id = project_config.project_prefix
    if not isinstance(expected_project_id, str) or not expected_project_id:
        raise InstallationError("CP10a requires a non-empty project_prefix in the validated ProjectConfig")
    old_story = _old_receipt(story_path, expected_tool="story_sync", expected_project_id=expected_project_id)
    old_concept = _old_receipt(concept_path, expected_tool="concept_sync", expected_project_id=expected_project_id)
    before_story = story_path.read_bytes() if story_path.is_file() else None
    before_concept = concept_path.read_bytes() if concept_path.is_file() else None
    (project_root / project_config.concepts_dir).mkdir(parents=True, exist_ok=True)
    (project_root / project_config.wiki_stories_dir).mkdir(parents=True, exist_ok=True)
    try:
        runtime = service or _service(project_root, project_config, client=client)
    except (RuntimeBindingError, VectorDbError) as exc:
        raise InstallationError(f"CP10a engine composition failed: {exc}") from exc
    try:
        prepared = runtime.prepare_initial_sync()
    except (SyncError, VectorDbError) as exc:
        raise InstallationError(f"CP10a initial sync failed without publishing freshness: {exc}") from exc
    old = (old_story, old_concept)
    paths = (story_path, concept_path)
    before = (before_story, before_concept)
    candidate = _prepare_receipts(prepared, *old)
    # Commit FIRST, publish second. The receipt files are evidence, and evidence
    # may only ever describe a state that was actually reached. Publishing them
    # before the completion commit made every unresolved or failed commit leave
    # a `status="success"` file behind that no reader could tell apart from the
    # real thing. The remaining failure mode is the harmless one: a committed
    # corpus whose local evidence is missing or stale, which fails closed on the
    # next verify and is republished by the next run.
    # The window opens BEFORE the commit, not after it. A marker written after
    # the commit cannot cover the very gap it exists for: a crash in between
    # would leave an advanced corpus, stale receipts, no marker and no pending
    # journal entry — indistinguishable from a clean run. Declaring the intent
    # first makes the window closed at both ends; the cost is a conservative
    # marker after a pre-commit abort, which the next run clears.
    marker = project_root / _PUBLICATION_MARKER
    _open_publication_window(marker, expected_project_id, candidate)
    _commit_prepared(prepared, paths, before, marker)
    published_receipts, changed = _publish_receipts(
        prepared,
        paths,
        before,
        old,
        candidate,
    )
    _close_publication_window(marker)
    return InitialSyncOutcome(
        receipts=published_receipts,
        changed=changed,
    )


def _open_publication_window(
    marker: Path,
    project_id: str,
    candidate: tuple[InitialSyncReceipt, InitialSyncReceipt],
) -> None:
    """Fence the span in which the local pair may not match the corpus."""
    payload = {
        "project_id": project_id,
        "pending_story_revision": candidate[0].end_revision,
        "pending_concept_revision": candidate[1].end_revision,
    }
    try:
        atomic_write_text(marker, json.dumps(payload, sort_keys=True, indent=2) + "\n", newline="")
    except OSError as exc:
        raise InstallationError(f"CP10a could not record the publication window: {marker}: {exc}") from exc


def _close_publication_window(marker: Path) -> None:
    """Clear the window once both receipts describe the committed state."""
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        raise InstallationError(
            f"CP10a published both receipts but could not clear the publication window: {marker}: {exc}"
        ) from exc


def _reject_open_publication_window(project_root: Path) -> None:
    """Fail closed while the local pair cannot be shown to match the corpus.

    This is the local, network-free answer to "did the evidence keep up with
    the corpus?": the fence is written BEFORE the commit and removed only after
    both files landed. Its presence does not prove the corpus moved — it proves
    that the span in which it could have moved was not completed, so the pair on
    disk is unproven either way. Deliberately conservative: an abort before the
    commit leaves a fence over a consistent state, which the next run clears.
    """
    marker = project_root / _PUBLICATION_MARKER
    if not marker.is_file():
        return
    raise InstallationError(
        f"CP10a receipt publication did not complete ({marker}); the local receipts cannot be shown "
        "to match the corpus, so they are not current evidence. Re-run the initial sync to republish them."
    )


def _reject_unresolved_completion(project_root: Path, project_id: str) -> None:
    """Fail closed while a completion outcome for this project is unknown.

    Receipts are published only AFTER a resolved commit, so the files on disk
    are never candidates — they are the last proven state. What an
    ``OUTCOME_UNKNOWN`` commit makes uncertain is whether the corpus has since
    moved past them. Reading them alone would therefore attest a currency
    nobody observed. The durable recovery journal is the authority on that
    question, so every reader asks it before it treats a receipt as current.
    """
    try:
        pending = project_commit_recovery_journal(project_root).list_pending(project_id)
    except VectorDbError as exc:
        raise InstallationError(f"CP10a completion recovery journal is unreadable: {exc}") from exc
    if pending:
        run_ids = ", ".join(sorted(entry.run_id for entry in pending))
        raise InstallationError(
            f"CP10a completion outcome is still unknown for project {project_id!r} "
            f"(pending recovery entries: {run_ids}); the receipts on disk are the last proven "
            "state but cannot be shown to be current, and the outcome must be resolved first"
        )


def verify_initial_sync(
    project_root: Path,
    *,
    expected_project_id: str | None = None,
) -> tuple[InitialSyncReceipt, InitialSyncReceipt]:
    """Strictly verify both success receipts as one pair.

    Args:
        project_root: The target project whose receipts are verified.
        expected_project_id: The project id from the validated configuration.
            Bound when the caller has it, so receipts carried over from another
            project cannot pass as this project's evidence.
    """
    receipts: list[InitialSyncReceipt] = []
    for tool in ("story_sync", "concept_sync"):
        path = project_root / _RECEIPT_DIR / f"{tool}.json"
        if not path.is_file():
            raise InstallationError(f"CP10a receipt is missing: {path}")
        receipts.append(_load_receipt(path, expected_tool=tool))
    story, concept = receipts[0], receipts[1]
    if story.project_id != concept.project_id:
        # The pair is evidence for ONE run. Two project ids mean two runs were
        # spliced together, and neither of them is proven complete.
        raise InstallationError(
            f"CP10a receipts belong to different projects: {story.project_id!r} vs {concept.project_id!r}"
        )
    if expected_project_id is not None and story.project_id != expected_project_id:
        raise InstallationError(
            f"CP10a receipts belong to project {story.project_id!r}, not {expected_project_id!r}"
        )
    # Root cause first: an unresolved outcome explains an open window, not the
    # other way round, and it is the more actionable message.
    _reject_unresolved_completion(project_root, story.project_id)
    _reject_open_publication_window(project_root)
    return story, concept


__all__ = [
    "InitialSyncOutcome",
    "InitialSyncReceipt",
    "run_initial_sync",
    "verify_initial_sync",
]
