# AG3-180 — Remediation mutation evidence

Date: 2026-08-03. Every mutation below was applied separately to the productive
implementation with `apply_patch`, executed red, removed immediately, and then
executed green against the restored implementation. No mutation remains in the
working tree.

| Finding | Reverted security property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| E1 | `_require_strategist()` allowed every authenticated principal | `test_project_token_cannot_administer_strategist_or_project_tokens` | FAIL: first project-token request returned `200`, expected `403` | `1 passed` |
| E2 | Pydantic `errors()` included the rejected input | `test_password_validation_error_never_echoes_request_input` | FAIL: response contained `LEAK-ME-NEVER` | `1 passed` |
| E3 | CLI persisted a machine-selected password instead of the twice-entered operator password | `test_interactive_bootstrap_writes_only_operator_chosen_password_hash` | FAIL: operator password could not verify the published hash | `1 passed` |
| E4 | The removed global Loopback restriction was restored, making the FK-10 remote-Core topology unreachable | `TestServe::test_core_serve_preserves_remote_core_bind_topology`; real non-Loopback no-bootstrap proof in `test_non_loopback_request_cannot_reach_an_http_bootstrap_surface` | `3 failed`: `0.0.0.0`, `192.0.2.10`, and `::` were rejected before the Core listener | `3 passed`; integration proof also passes |
| E5 | (a) Invalid pending credentials were caught as though absent; (b) `issue-token` continued into a second rotation after reconciling an already-published sidecar; (c) runtime and `register-project` ignored a divergent pending rotation beside an active token | `test_corrupt_pending_credential_fails_closed_without_registration_or_overwrite`; `test_crash_after_active_publication_recovers_without_second_registration` with the public `replace_active=True` flag; `test_build_project_edge_client_rejects_unreconciled_pending_rotation`; `test_register_auth_context_rejects_unreconciled_pending_rotation` | (a) registration transport called and corrupt file replaced; (b) FAIL: returned `active` after a second registration instead of `already_active`; (c) both public entry points continued without raising | all four focused tests pass; crash recovery performs exactly one HTTP registration and ambiguous active/pending states block runtime and installer |
| E6 | SQLite insert regained `ON CONFLICT ... DO UPDATE`, including clearing revocation through the new row | `test_revoked_project_api_token_id_cannot_be_registered_again`; PostgreSQL counterpart in `test_token_identity_postgres.py` | FAIL: duplicate registration did not raise `ProjectApiTokenAlreadyExistsError` | `2 passed` across SQLite and PostgreSQL |
| E7 | A Python module was added under forbidden `src/agentkit/shared/` | `test_ag3_180_does_not_create_a_shared_deployment_unit_or_edge_backend_import` | FAIL: forbidden `mutation.py` detected | `1 passed` |
| E8 | One project-management exception regained a non-static `Exception` base | `test_all_project_management_errors_have_one_static_agentkit_base_contract` | FAIL: direct bases no longer all equal `(AgentKitError,)` | `1 passed` |
| E9 | (a) FK-15 again stated that an anonymous HTTP bootstrap route exists; (b) password rotation bypassed the FK-91 claim/body-hash/replay path | concept-owner contract; `test_password_rotation_replays_after_login_with_new_password`; `test_password_rotation_rejects_op_id_reuse_with_another_password`; `test_password_rotation_in_flight_is_rejected_without_changing_secret` | (a) normative no-route contract absent; (b) `3 failed`: replay mutated again, differing body returned `200`, and a preclaimed operation rotated the password instead of returning `409 operation_in_flight` | concept contract passes; `3 passed` for rotation replay/mismatch/in-flight |
| E10 | The temporary strategist ProjectEdge client was no longer injected before the installer ran CP10d | `test_fresh_public_flow_runs_default_cp10d_before_activating_project_token` | FAIL in the real register/HTTPS/default-CP10d flow: `.agentkit/credentials` was missing before it could be issued | `1 passed`; no Sonar/CI opt-out and token becomes active only after CP10d |
| E11 | `StrategistCredentialStore._mutation_lock()` yielded without an OS lock | `test_repeated_real_two_process_bootstrap_race_has_exactly_one_winner` | FAIL in first real process race: `[201, 201]` instead of `[201, 409]` | `1 passed in 29.79s` across ten process races |
| E12 | Core secret file was published with `os.replace()` before permission measurement | `test_failed_permission_measurement_does_not_publish_plaintext` | FAIL: destination contained `must-never-be-published` after the forced measurement failure | full file-security module: `3 passed, 1 skipped` (POSIX reality test runs on POSIX) |
| E13 | A real unused import was introduced into the changed bind-boundary module | `ruff check src/agentkit/backend/boundary/network.py`, followed by the mandatory full Ruff command | FAIL: `F401 math imported but unused` | `ruff check src tests`: `All checks passed!` |

The commands were run with `.venv\Scripts\python` only. E11 uses spawned OS
processes, not threads. E12 uses the real platform permission implementation;
the POSIX `0600` assertion is intentionally skipped on Windows and is exercised
by the Linux CI run.

## Follow-up independent-review mutations

The second independent review found contract surfaces that the first mutation
set did not exercise. These additional mutations were run and restored as well:

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| FK-15 bind contradiction | Reintroduced the absolute sentence that all AgentKit services run on localhost | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | FAIL on the forbidden absolute sentence | `1 passed` |
| FK-91 auth CLI catalog | Removed the `agentkit auth issue-token` catalog row | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | FAIL because one of the five public auth verbs was absent | `1 passed` |
| FK-13 vocabulary | Disabled the closed `status`/`doc_kind` value check | `test_disallowed_enum_value_fails_closed` | FAIL because `status: published` was accepted | `1 passed` |
| FK-13 nested schema | Changed `_SupersedesEntry` from `extra=forbid` to `extra=ignore` | `test_malformed_scope_qualified_supersedes_fails_closed` | FAIL because the unknown nested key was accepted | `3 passed` |

## Third independent-review mutations

The third independent review identified seven additional security and recovery
properties. Each mutation below was applied to production code, observed red,
restored, and observed green:

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| Orphaned idempotency claim | Disabled route-specific recovery after the domain mutation had succeeded but idempotency finalization had not | `test_password_rotation_recovers_crash_after_hash_publish_before_finalize`; `test_create_token_recovers_crash_after_insert_before_finalize` | `2 failed`: both retries returned `409 operation_in_flight` | `2 passed` |
| Password-rotation operation identity | Ignored the operator-provided `--op-id` and minted a replacement | `test_rotate_password_exposes_and_reuses_operator_operation_id` | FAIL: emitted and submitted operation ID differed from the requested ID | `1 passed` |
| Concurrent token issuance | Removed the process-wide credential transition lock | `test_concurrent_real_process_token_issue_has_one_registration` | FAIL: the second OS process reached token registration | `1 passed` |
| Pending request reconstruction | Used the retrying command's current label instead of the label persisted before the lost response | `test_response_loss_retry_reuses_pending_label_and_complete_request` | FAIL: retry sent `default` instead of the original `custom` label | `1 passed` |
| Pending-state validation at every entry point | Removed reconciliation from the governance runtime and removed the missing-active pending check from `register-project` | `test_governance_edge_client_rejects_unreconciled_pending_rotation`; `test_register_auth_context_rejects_corrupt_pending_before_prompt` | runtime continued with an ambiguous rotation; installer continued to an unrelated interactive failure | both focused tests pass |
| Secret transport | Removed the HTTPS precondition before strategist authentication | `test_strategist_password_is_rejected_before_plain_http_transport` | FAIL: the HTTP transport was invoked with the password | `1 passed` |
| Logout replay | Rejected a missing session instead of treating the already-absent target state as success | `test_logout_replay_without_a_remaining_session_is_successful` | FAIL: replay returned `401` | `1 passed` |

## Fourth independent-review mutations

The fourth independent review found seven remaining concurrency, identity, and
W4 gaps. Each mutation below was applied separately to the productive source or
normative owner, observed red, restored, and observed green:

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| Session resurrection | Removed the shared lock from `revoke_all()` while validation was paused before refresh publication | `test_parallel_validation_cannot_resurrect_a_revoked_session` | FAIL: revocation completed inside the validation critical section and the session could be republished | `1 passed`; `test_parallel_old_password_login_cannot_survive_rotation` additionally proves verify/create versus rotate/revoke ordering |
| Runtime/operator credential race | Removed the lifecycle lock from active-plus-pending runtime reconciliation | `test_runtime_cannot_reconcile_inside_an_operator_publication` | FAIL in two spawned OS processes: runtime returned `runtime_ok` inside the paused operator publication instead of `PrivateFileLockBusyError` | `1 passed` |
| Foreign pending before CP10d | Removed the pending `project_key` comparison from the pre-installer state check | `test_register_auth_context_rejects_foreign_pending_before_installer` | FAIL: processing continued to the unrelated interactive-terminal error | `1 passed` |
| Token-revocation operation identity | Ignored the supplied `revoke-token --op-id` and minted a replacement UUID | `test_revoke_token_exposes_and_reuses_operator_operation_id` | FAIL: emitted and submitted operation ID differed from `op-revoke-visible` | `1 passed` |
| Project-scoped idempotency | Removed `project_key` comparison from the in-memory guard's request classification | `test_password_rotation_rejects_cross_project_op_id_replay` | FAIL: project B received project A's stored `200` result | unit and real-Postgres proofs: `2 passed` |
| Logout normative consistency | Removed the explicit FK-15 logout-replay exception while leaving the implementation intact | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | FAIL: normative replay contract absent | `1 passed` |
| Distribution-record W4 | Replaced the required `Impact-Sweep (P3/W4)` section with an unrecognized heading | `test_edge_core_distribution_record_has_w4_evidence_and_real_story_locators` | FAIL: W4 evidence absent | `1 passed` |

## Fifth independent-review mutation

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| Malformed persisted Argon2 hash | Removed `InvalidHashError` from the credential verification error mapping | `test_login_maps_a_malformed_persisted_password_hash_to_opaque_unauthorized` | FAIL: `InvalidHashError` escaped the HTTP route instead of an opaque response | `1 passed`; login returns stable `401 unauthorized` without hash/password disclosure |

## Sixth independent-review mutations

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| Closed strategist credential document | Changed the persisted credential model from `extra=forbid` to `extra=ignore` | `test_login_maps_a_malformed_persisted_password_hash_to_opaque_unauthorized` (also exercises missing/null username, metadata/type mismatch, valid Argon2i PHC, and invalid PHC) | FAIL: document with an unknown field authenticated and returned `200` | `1 passed`; all malformed forms return opaque `401` |
| Operation-specific password recovery | Replaced `verify_applied_rotation(..., op_id=...)` with password-only verification | `test_same_as_current_password_cannot_terminalize_a_live_rotation_claim` | FAIL: an unexecuted live claim for the already-current password returned `200` and became terminal | `2 passed` including genuine post-publish/pre-finalize recovery |
| Auth-profile concept split | Removed the explicit FK-15 statement that UI-BFF and Project-API belong to the same Control-Plane security domain | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | FAIL: the implementation's operator-login surface no longer had an authoritative profile contract | `1 passed` |

## Seventh independent-review mutations

These three late R2 mutations were re-run on 2026-08-03 for this remediation;
the results below are the observed outputs of those runs, not inferred results.

| Review blocker | Reverted property | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| Password-recovery TOCTOU | Replaced the recovery transition-lock context with an unlocked branch | `test_password_recovery_holds_credential_lock_through_claim_finalization` | `1 failed`: `later_rotation_was_blocked` was false | `1 passed in 5.76s`; the competing writer enters only after the recovered claim is terminal |
| Cross-profile session revocation | Replaced `FileSessionStore.revoke_all()` with a no-op | `test_real_profile_processes_share_session_revocation` | The original proof unexpectedly stayed green (`1 passed in 6.43s`) because credential-generation invalidation masked the populated shared session table. The proof was strengthened to measure the table before releasing the creator; the same mutation then failed with session count `1`, expected `0`. | Strengthened proof: `1 passed in 6.74s`; the revoking profile has durably emptied the shared table before the creator resumes. |
| Two-endpoint security-domain concept | Replaced the normative cross-process session owner with a local store | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | `1 failed`: FK-15 no longer contained `prozessuebergreifenden Session-Store` | `1 passed in 1.37s`; W4 also names and reconciles FK-72 §72.8 |

## R2 role separation and findings 3–5

Each mutation below was applied after its focused proof was in place and was
restored before the next mutation.

| R2 requirement | Applied mutation | Focused proof | Mutated result | Restored result |
|---|---|---|---|---|
| AC 1a, backend-admin side | Made `issue-token` write the issued token into `.agentkit/credentials` on the Core machine | `test_ac1a_backend_admin_issues_token_without_core_credential_file` | `1 failed`: the Core credential file existed | `1 passed in 9.29s` |
| AC 1b, client-operator side | Added a `Strategist password` prompt to `store-token` | `test_ac1b_client_operator_stores_and_uses_handoff_without_admin_secret` | `1 failed`: the separate laptop process recorded the forbidden second prompt and returned exit code 1 | `1 passed in 12.01s`; its sole prompt is `Project API token` |
| FK-15 role contract | Replaced the two named roles with one common operator | `test_ag3_180_decision_record_and_secret_class_contract_are_present` | `1 failed`: `Backend-Admin und Client-Bediener` was absent | `1 passed in 1.35s` |
| Project credential exception chain | Restored `raise CredentialInvalidError(...) from ValidationError` around the secret-bearing Pydantic input | `test_invalid_credential_never_retains_plaintext_in_exception_channels` | `1 failed`: formatted traceback contained `stranded-secret` | `1 passed in 2.90s` |
| Strategist credential exception chain | Reattached the secret-bearing Pydantic validation exception | `test_malformed_auth_file_does_not_retain_hash_in_exception_chain` | `1 failed`: formatted traceback contained `argon2id-secret-hash-material` | `1 passed in 2.10s` |
| Argon2 parser exception | Allowed `VerificationError` to escape | `test_invalid_argon2_hash_does_not_survive_auth_exception_channels` | `1 failed`: `VerificationError: Decoding failed` escaped instead of the opaque auth error | `1 passed in 2.15s` |
| Shared session document exception chain | Reattached the secret-bearing Pydantic validation exception | `test_malformed_session_file_does_not_retain_tokens_in_exception_chain` | `1 failed`: formatted traceback contained `session-secret-material` | `1 passed in 2.85s` |
| Dead HTTP-bootstrap contract | Reintroduced `BootstrapOriginError` | `test_removed_http_bootstrap_origin_error_has_no_contract_residue` | `1 failed`: the removed symbol was visible again | `1 passed in 1.35s` |
| SQLite warning ownership | Replaced one `closing(sqlite3.connect(...))` test context with raw `sqlite3.connect(...)` | `test_sqlite_connections_are_not_used_as_closing_context_managers` | `1 failed`: reported `test_schema_versioning.py:110` | `1 passed in 3.76s` |
| VectorDB test-journal ownership | Removed the explicit finalizer for the real `TemporaryDirectory` held by the installer VectorDB double | role-separated default-CP10d flow plus the three `wire_ready_vectordb` CLI flows, with `ResourceWarning` and `PytestUnraisableExceptionWarning` promoted to errors | `4 passed, 1 error`: implicit cleanup of `agentkit-vectordb-recovery-*` surfaced during teardown | Explicit `FixtureRequest` finalizers: `4 passed in 16.89s`, no warning/error |
