"""Remote-lock liveness (R9-3) and the normed ``consumer`` edge (R9-4)."""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import promotion_check, runmodel
from concept_toolchain.config import load_governance_config
from concept_toolchain.promotion_check import run_promotion_check
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc
from tests.unit.concept_toolchain.runfixtures import RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

pytestmark = pytest.mark.requires_git

FORMAL_HOST_REL = "concept/technical-design/20_formal_host.md"


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=True)


def run_check(fixture: RunFixture) -> CheckResult:
    config = load_governance_config(fixture.project_root)
    return run_promotion_check(fixture.project_root, config, fixture.run_dir)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.locator}: {finding.message}" for finding in result.findings)


def switch_to_git_remote(fixture: RunFixture, *, remote: str | None = "origin") -> None:
    config_rel = "concept/_meta/concept-governance.json"
    config_path = fixture.project_root / config_rel
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["lock_backend"] = "git-remote"
    if remote is not None:
        payload["lock_remote"] = remote
    runfixtures.write_json(config_path, payload)
    manifest = fixture.read_manifest()
    locks = manifest["scope_locks"]
    assert isinstance(locks, list) and isinstance(locks[0], dict)
    locks[0]["backend"] = "git-remote"
    fixture.write_manifest(manifest)
    runfixtures.refresh_normative_coverage(fixture)


def evidence(fixture: RunFixture, *, remote: str = "origin", **overrides: object) -> dict[str, object]:
    acquired_at = str(overrides.pop("acquired_at", runfixtures.now_utc()))
    ttl_seconds = int(str(overrides.pop("ttl_seconds", 3600)))
    ref: dict[str, object] = {
        "scope_id": fixture.scope_id,
        "ref": runmodel.scope_lock_ref(fixture.scope_id),
        "expected_ref": runmodel.scope_lock_ref(fixture.scope_id),
        "old_oid": "0" * 40,
        "new_oid": "b" * 40,
        "observed_oid": "b" * 40,
        "lock_blob_digest": runmodel.canonical_lock_blob_digest(
            fixture.scope_id, fixture.run_id, 7, "git-remote", ttl_seconds, acquired_at
        ),
        "fencing_token": 7,
        "ttl_seconds": ttl_seconds,
        "acquired_at": acquired_at,
        "attested_by_principal": "orch.alice",
        "attested_by_session": "sess-orch",
        "verified_at": runfixtures.now_utc(),
    }
    ref.update(overrides)
    return {"schema_version": "1.0.0", "backend": "git-remote", "remote": remote, "refs": [ref]}


def write_evidence(fixture: RunFixture, payload: dict[str, object]) -> None:
    runfixtures.write_json(fixture.run_dir / "promotion" / "lock-evidence.json", payload)


def test_live_attested_lock_completes_the_check(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture))
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is True, result.incomplete_reason


def test_expired_attested_lock_is_error(fixture: RunFixture) -> None:
    """R9-3 (a): the attested lock itself must still be live."""
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, acquired_at="2020-01-01T00:00:00Z"))
    assert "attested lock has expired" in finding_messages(run_check(fixture))


def test_stale_attestation_is_error(fixture: RunFixture) -> None:
    """R9-3 (b): the attestation must not be older than the lock TTL."""
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, verified_at="2020-01-01T00:00:00Z"))
    assert "CAS attestation is stale" in finding_messages(run_check(fixture))


def test_ttl_is_digest_bound(fixture: RunFixture) -> None:
    """Changing the TTL without re-attesting breaks the lock-blob digest."""
    switch_to_git_remote(fixture)
    payload = evidence(fixture)
    refs = payload["refs"]
    assert isinstance(refs, list) and isinstance(refs[0], dict)
    refs[0]["ttl_seconds"] = 99999
    write_evidence(fixture, payload)
    assert "lock_blob_digest does not match" in finding_messages(run_check(fixture))


def test_acquired_at_is_digest_bound(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    payload = evidence(fixture)
    refs = payload["refs"]
    assert isinstance(refs, list) and isinstance(refs[0], dict)
    refs[0]["acquired_at"] = "2026-07-19T00:00:00Z"
    write_evidence(fixture, payload)
    assert "lock_blob_digest does not match" in finding_messages(run_check(fixture))


def test_remote_must_match_the_configured_lock_remote(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, remote="upstream"))
    assert "does not match the configured lock_remote 'origin'" in finding_messages(run_check(fixture))


def test_git_remote_backend_without_lock_remote_is_config_error(fixture: RunFixture) -> None:
    config_rel = "concept/_meta/concept-governance.json"
    payload = json.loads((fixture.project_root / config_rel).read_text(encoding="utf-8"))
    payload["lock_backend"] = "git-remote"
    runfixtures.write_json(fixture.project_root / config_rel, payload)
    with pytest.raises(Exception, match="lock_remote"):
        load_governance_config(fixture.project_root)


def shifted(seconds: int) -> str:
    """Return a UTC-Z timestamp offset from now by ``seconds``."""
    moment = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_verified_at_far_in_the_future_is_error(fixture: RunFixture) -> None:
    """R10-2: 'not yet expired' alone was fail-open for future timestamps."""
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, verified_at=shifted(86_400)))
    assert "verified_at" in finding_messages(run_check(fixture))
    assert "lies in the future" in finding_messages(run_check(fixture))


def test_acquired_at_in_the_future_is_error(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    future = shifted(86_400)
    write_evidence(fixture, evidence(fixture, acquired_at=future, verified_at=future))
    assert "acquired_at" in finding_messages(run_check(fixture))
    assert "lies in the future" in finding_messages(run_check(fixture))


def test_verified_at_before_acquired_at_is_error(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, acquired_at=shifted(-60), verified_at=shifted(-600)))
    assert "precedes acquired_at" in finding_messages(run_check(fixture))


def test_verified_at_beyond_acquired_at_plus_ttl_is_error(fixture: RunFixture) -> None:
    switch_to_git_remote(fixture)
    write_evidence(fixture, evidence(fixture, ttl_seconds=60, acquired_at=shifted(-30), verified_at=shifted(120)))
    assert "beyond acquired_at + ttl_seconds" in finding_messages(run_check(fixture))


def test_small_clock_skew_is_tolerated(fixture: RunFixture) -> None:
    """A forward drift within CLOCK_SKEW_SECONDS must stay acceptable."""
    switch_to_git_remote(fixture)
    skew = promotion_check.CLOCK_SKEW_SECONDS - 60
    write_evidence(fixture, evidence(fixture, acquired_at=shifted(skew), verified_at=shifted(skew)))
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


# -- R9-4: normed consumer semantics ----------------------------------------


def add_consumer_edge(fixture: RunFixture, from_ref: str, to_ref: str) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": from_ref, "to": to_ref, "kind": "consumer"})
    fixture.write_manifest(manifest)


def test_consumer_edge_holds_via_formal_refs_binding(fixture: RunFixture) -> None:
    """The event set is bound by the document's formal_refs — edge satisfied."""
    add_consumer_edge(fixture, "sample.event.finished", "FK-20")
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_consumer_edge_documented_boundary_set_binding_not_event_processing(fixture: RunFixture) -> None:
    """Documented v1 limit: binding the SET satisfies the edge for ANY of its events.

    ``FK-20`` binds ``formal.sample.event-set`` and therefore satisfies a
    consumer edge for every event in that set — including one it never
    processes. This is the normed v1 semantics, not an oversight:
    event-specific consumption needs an explicit ``consumes_events``
    relation and must not be inferred from ``formal_refs``.
    """
    write_doc(
        fixture.project_root,
        "concept/formal-spec/sample/events.md",
        (fixture.project_root / "concept/formal-spec/sample/events.md")
        .read_text(encoding="utf-8")
        .replace(
            "events:\n  - id: sample.event.finished\n    producer: sample\n    role: lifecycle\n",
            "events:\n"
            "  - id: sample.event.finished\n    producer: sample\n    role: lifecycle\n"
            "  - id: sample.event.ignored\n    producer: sample\n    role: lifecycle\n",
        ),
    )
    runfixtures.refresh_normative_coverage(fixture)
    add_consumer_edge(fixture, "sample.event.ignored", "FK-20")
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_consumer_edge_without_formal_refs_binding_is_error(fixture: RunFixture) -> None:
    write_doc(fixture.project_root, "concept/domain-design/06-unbound.md", concept_doc("DK-06", scopes=("scope-dk-06",)))
    runfixtures.refresh_normative_coverage(fixture)
    add_consumer_edge(fixture, "sample.event.finished", "DK-06")
    assert "does not bind formal.sample.event-set via formal_refs" in finding_messages(run_check(fixture))


def test_consumer_edge_with_unknown_event_is_error(fixture: RunFixture) -> None:
    add_consumer_edge(fixture, "sample.event.nope", "FK-20")
    assert "does not resolve as doc id, scope id or registry entry" in finding_messages(run_check(fixture))
