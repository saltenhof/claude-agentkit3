"""Unit-Tests fuer StateBackendArtifactRepository (SQLite-Backend).

AG3-023 §2.1.7 — Roundtrip-Tests:
- write -> read -> envelope Bit-fuer-Bit gleich
- exists True/False
- UNIQUE-Constraint blockt Doppelt-Insert (idempotent per INSERT OR IGNORE)
- Idempotenz-Test fuer Schema-Bootstrap
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.artifacts.reference import ArtifactReference
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus
from agentkit.backend.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
    _ensure_artifact_table_sqlite,
    _record_key,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateBackendArtifactRepository:
    """SQLite-Repository gegen tmp_path."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    return StateBackendArtifactRepository(store_dir=tmp_path)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_envelope(
    *,
    story_id: str = "AG3-023",
    run_id: str = "run-001",
    stage: str = "impl",
    attempt: int = 1,
    producer_name: str = "verify-system.layer-1-structural",
    producer_type: ProducerType = ProducerType.DETERMINISTIC,
    status: EnvelopeStatus = EnvelopeStatus.PASS,
    artifact_class: ArtifactClass = ArtifactClass.QA,
    payload: dict[str, object] | None = None,
) -> ArtifactEnvelope:
    start = _now()
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=stage,
        attempt=attempt,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId("inst-001"),
        ),
        started_at=start,
        finished_at=start,
        status=status,
        artifact_class=artifact_class,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_write_returns_artifact_reference(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        env = _make_envelope()
        ref = repo.write_envelope(env)
        assert isinstance(ref, ArtifactReference)
        assert ref.artifact_class is ArtifactClass.QA
        assert ref.story_id == "AG3-023"
        assert ref.run_id == "run-001"

    def test_write_then_read_is_identical(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        env = _make_envelope()
        ref = repo.write_envelope(env)
        loaded = repo.read_envelope(ref)
        assert loaded is not None
        assert loaded.story_id == env.story_id
        assert loaded.run_id == env.run_id
        assert loaded.stage == env.stage
        assert loaded.attempt == env.attempt
        assert loaded.schema_version == env.schema_version
        assert loaded.artifact_class is env.artifact_class
        assert loaded.status is env.status
        assert loaded.producer.type is env.producer.type
        assert loaded.producer.name == env.producer.name
        assert loaded.producer.id == env.producer.id
        assert loaded.producer.version == env.producer.version
        # UTC tz-awareness preserved
        assert loaded.started_at.tzinfo is not None
        assert loaded.finished_at.tzinfo is not None

    def test_write_then_read_payload_preserved(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        payload = {"checks": 7, "passed": True, "source": "contract"}
        env = _make_envelope(payload=payload)
        ref = repo.write_envelope(env)
        loaded = repo.read_envelope(ref)
        assert loaded is not None
        assert loaded.payload == payload

    def test_read_returns_none_for_missing(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        ghost = ArtifactReference(
            artifact_class=ArtifactClass.QA,
            story_id="AG3-023",
            run_id="ghost",
            record_key="AG3-023|ghost|impl|1|qa|verify-system.layer-1-structural",
        )
        result = repo.read_envelope(ghost)
        assert result is None

    def test_write_all_nine_artifact_classes(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        """Alle neun ArtifactClass-Wire-Werte sind schreib- und lesbar.

        AG3-015: ``prompt_audit`` ergaenzt (FK-44 §44.6).
        """
        all_classes = [
            (ArtifactClass.WORKER, ProducerType.WORKER),
            (ArtifactClass.QA, ProducerType.DETERMINISTIC),
            (ArtifactClass.PIPELINE, ProducerType.DETERMINISTIC),
            (ArtifactClass.TELEMETRY, ProducerType.DETERMINISTIC),
            (ArtifactClass.GOVERNANCE, ProducerType.DETERMINISTIC),
            (ArtifactClass.ENTWURF, ProducerType.WORKER),
            (ArtifactClass.HANDOVER, ProducerType.WORKER),
            (ArtifactClass.ADVERSARIAL_TEST_SANDBOX, ProducerType.LLM_REVIEWER),
            (ArtifactClass.PROMPT_AUDIT, ProducerType.DETERMINISTIC),
        ]
        for artifact_class, producer_type in all_classes:
            env = _make_envelope(
                artifact_class=artifact_class,
                producer_type=producer_type,
                producer_name=f"producer-{artifact_class.value}",
                run_id=f"run-{artifact_class.value}",
            )
            ref = repo.write_envelope(env)
            loaded = repo.read_envelope(ref)
            assert loaded is not None
            assert loaded.artifact_class is artifact_class

    def test_reference_is_deterministic(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        """Gleiche Identitaetsfelder -> gleicher record_key."""
        env = _make_envelope()
        ref1 = repo.write_envelope(env)
        # Compute expected key manually
        expected_key = _record_key(
            story_id="AG3-023",
            run_id="run-001",
            stage="impl",
            attempt=1,
            artifact_class=ArtifactClass.QA,
            producer_name="verify-system.layer-1-structural",
        )
        assert ref1.record_key == expected_key


# ---------------------------------------------------------------------------
# exists_envelope
# ---------------------------------------------------------------------------


class TestExistsEnvelope:
    def test_exists_true_after_write(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        env = _make_envelope()
        ref = repo.write_envelope(env)
        assert repo.exists_envelope(ref) is True

    def test_exists_false_for_missing(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        ghost = ArtifactReference(
            artifact_class=ArtifactClass.QA,
            story_id="AG3-023",
            run_id="ghost",
            record_key="AG3-023|ghost|impl|1|qa|verify-system.layer-1-structural",
        )
        assert repo.exists_envelope(ghost) is False


# ---------------------------------------------------------------------------
# Idempotenz (UNIQUE-Constraint / INSERT OR IGNORE)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_double_write_does_not_raise(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        """Zweiter write mit gleichen Identitaetsfeldern muss kein Fehler werfen."""
        env = _make_envelope()
        ref1 = repo.write_envelope(env)
        ref2 = repo.write_envelope(env)
        assert ref1.record_key == ref2.record_key

    def test_double_write_does_not_duplicate_rows(
        self, repo: StateBackendArtifactRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nach Doppelt-Write: genau eine Zeile in der DB."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        env = _make_envelope()
        repo.write_envelope(env)
        repo.write_envelope(env)

        # DB direkt pruefen
        from agentkit.backend.state_backend.config import versioned_sqlite_db_file
        from agentkit.backend.state_backend.paths import state_backend_dir

        db_path = state_backend_dir(tmp_path) / versioned_sqlite_db_file()
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM artifact_envelopes")
            count = cursor.fetchone()[0]
        assert count == 1

    def test_different_attempts_are_separate_rows(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        """Verschiedene attempt-Nummern ergeben separate Eintraege."""
        env1 = _make_envelope(attempt=1)
        env2 = _make_envelope(attempt=2)
        ref1 = repo.write_envelope(env1)
        ref2 = repo.write_envelope(env2)
        assert ref1.record_key != ref2.record_key
        assert repo.read_envelope(ref1) is not None
        assert repo.read_envelope(ref2) is not None


# ---------------------------------------------------------------------------
# Schema-Bootstrap-Idempotenz (AG3-023 §2.1.4.2)
# ---------------------------------------------------------------------------


class TestSchemaBootstrapIdempotent:
    def test_bootstrap_twice_no_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zweite _ensure_artifact_table_sqlite-Ausfuehrung darf keinen Fehler werfen."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

        db_path = tmp_path / "test_idempotent.sqlite"
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_artifact_table_sqlite(conn)
            conn.commit()

        with sqlite3.connect(str(db_path)) as conn:
            _ensure_artifact_table_sqlite(conn)  # zweiter Aufruf — darf nicht failen
            conn.commit()
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_envelopes'"
            )
            assert cursor.fetchone() is not None

    def test_bootstrap_side_by_side_dbs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Alte DB unter alter SCHEMA_VERSION bleibt unangetastet (FK-18 §18.9a)."""
        from agentkit.backend.state_backend import config as state_config

        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

        # Schreibe Daten in "alte" Version
        monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.3.0")
        repo_old = StateBackendArtifactRepository(store_dir=tmp_path)
        env = _make_envelope()
        repo_old.write_envelope(env)

        # Wechsel auf neue Version
        monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.4.0")
        repo_new = StateBackendArtifactRepository(store_dir=tmp_path)

        # Neue Version: leere DB
        ghost = ArtifactReference(
            artifact_class=ArtifactClass.QA,
            story_id="AG3-023",
            run_id="run-001",
            record_key="AG3-023|run-001|impl|1|qa|verify-system.layer-1-structural",
        )
        assert repo_new.read_envelope(ghost) is None

        # Alte DB-Datei existiert noch
        from agentkit.backend.state_backend.paths import state_backend_dir
        old_db = state_backend_dir(tmp_path) / state_config.versioned_sqlite_db_file("3.3.0")
        new_db = state_backend_dir(tmp_path) / state_config.versioned_sqlite_db_file("3.4.0")
        assert old_db.exists()
        assert new_db.exists()
        assert old_db.name != new_db.name


class TestFindPromptAuditOutputHashes:
    """``find_prompt_audit_output_hashes`` (FK-44 §44.6 / FK-31 §31.7.4).

    The PromptIntegrityGuard Stage-3 baseline (AG3-086): the set of all
    prompt-audit ``output_sha256`` digests for a (story, run) -- ALL of them, not
    just the latest, so any prompt the pipeline legitimately materialized for the
    run (worker / qa / remediation) is an admissible baseline.
    """

    def test_returns_all_output_hashes_for_scope(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        # Three prompt-audit records (different invocations / attempts) for one run.
        for attempt, digest in ((1, "a" * 64), (1, "b" * 64), (2, "c" * 64)):
            repo.write_envelope(
                _make_envelope(
                    story_id="AG3-900",
                    run_id="run-900",
                    stage="prompt-materialization",
                    attempt=attempt,
                    producer_name=f"prompt-runtime.materialization-{digest[:4]}",
                    artifact_class=ArtifactClass.PROMPT_AUDIT,
                    payload={"output_sha256": digest},
                )
            )
        result = repo.find_prompt_audit_output_hashes(
            story_id="AG3-900", run_id="run-900"
        )
        assert result == frozenset({"a" * 64, "b" * 64, "c" * 64})

    def test_scopes_to_story_and_run(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-900",
                run_id="run-900",
                stage="prompt-materialization",
                producer_name="prompt-runtime.materialization",
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload={"output_sha256": "a" * 64},
            )
        )
        # A different run must NOT leak into the scope.
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-900",
                run_id="run-OTHER",
                stage="prompt-materialization",
                producer_name="prompt-runtime.materialization",
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload={"output_sha256": "z" * 64},
            )
        )
        # A non-prompt-audit class with the same run must NOT leak in.
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-900",
                run_id="run-900",
                stage="impl",
                artifact_class=ArtifactClass.QA,
                payload={"output_sha256": "q" * 64},
            )
        )
        result = repo.find_prompt_audit_output_hashes(
            story_id="AG3-900", run_id="run-900"
        )
        assert result == frozenset({"a" * 64})

    def test_empty_when_none_materialized(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        assert (
            repo.find_prompt_audit_output_hashes(story_id="AG3-900", run_id="run-900")
            == frozenset()
        )

    def test_ignores_records_without_output_sha256(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-900",
                run_id="run-900",
                stage="prompt-materialization",
                producer_name="prompt-runtime.materialization",
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload={"unrelated": "value"},
            )
        )
        assert (
            repo.find_prompt_audit_output_hashes(story_id="AG3-900", run_id="run-900")
            == frozenset()
        )

    def test_ignores_record_with_null_payload(
        self, repo: StateBackendArtifactRepository
    ) -> None:
        # A PROMPT_AUDIT record persisted with a NULL payload (payload_json IS NULL)
        # is skipped, not a crash.
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-900",
                run_id="run-900",
                stage="prompt-materialization",
                producer_name="prompt-runtime.materialization",
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload=None,
            )
        )
        assert (
            repo.find_prompt_audit_output_hashes(story_id="AG3-900", run_id="run-900")
            == frozenset()
        )


class TestFacadeFindPromptAuditOutputHashes:
    """``facade.find_prompt_audit_output_hashes`` (the governance read seam)."""

    @pytest.fixture(autouse=True)
    def _sqlite_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

    def test_explicit_scope_returns_pinned_hashes(self, tmp_path: Path) -> None:
        from agentkit.backend.state_backend.scope import RuntimeStateScope
        from agentkit.backend.state_backend.store.facade import (
            find_prompt_audit_output_hashes,
        )

        repo = StateBackendArtifactRepository(store_dir=tmp_path)
        repo.write_envelope(
            _make_envelope(
                story_id="AG3-901",
                run_id="run-901",
                stage="prompt-materialization",
                producer_name="prompt-runtime.materialization",
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload={"output_sha256": "d" * 64},
            )
        )
        scope = RuntimeStateScope(
            project_key="demo",
            story_id="AG3-901",
            story_dir=tmp_path,
            run_id="run-901",
        )
        result = find_prompt_audit_output_hashes(tmp_path, scope)
        assert result == frozenset({"d" * 64})

    def test_empty_run_id_returns_empty(self, tmp_path: Path) -> None:
        from agentkit.backend.state_backend.scope import RuntimeStateScope
        from agentkit.backend.state_backend.store.facade import (
            find_prompt_audit_output_hashes,
        )

        scope = RuntimeStateScope(
            project_key="demo",
            story_id="AG3-901",
            story_dir=tmp_path,
            run_id=None,
        )
        assert find_prompt_audit_output_hashes(tmp_path, scope) == frozenset()

    def test_unresolvable_scope_returns_empty(self, tmp_path: Path) -> None:
        # scope=None with no runtime state -> CorruptStateError -> empty (fail-soft;
        # the guard then treats Stage 3 as fail-closed downstream).
        from agentkit.backend.state_backend.store.facade import (
            find_prompt_audit_output_hashes,
        )

        assert find_prompt_audit_output_hashes(tmp_path, None) == frozenset()
