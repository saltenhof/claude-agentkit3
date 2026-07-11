# AG3-151 — takeover reconcile / ex-owner quarantine / contested_local_writes: feasibility ground truth

**Status:** FEASIBILITY captured at main@6b5b7468 (scout + to-be-adjudicated). This is the
input to the design freeze — the next step is to AUTHOR the frozen design note (like the
AG3-150 one) and dispatch the worker. Story loci in `story.md` are STALE (control_plane runtime
decomposed into `control_plane/runtime/` submodules; freeze/transfer reworked by 148/149/150) —
use the corrected coordinates below. Orchestrator must adjudicate the load-bearing claims
(esp. records.py:304 pattern lock) at code before freezing.

FEASIBILITY VERDICT: implementable as scoped. All 4 deps (145/148/149/150) completed; every seam
present. status.yaml says `blocked` — stale workflow flag, NOT a code blocker.

## Corrected coordinates (HEAD, use these not story.md)
- Quarantine (reuse as-is, NO change): `harness_client/projectedge/quarantine.py` —
  `quarantine_worktree(*, source_root, quarantine_store, reason, now) -> QuarantineResult|None` :37,
  local-only, no Git/upload. AG3-151 adds the CALLER `harness_client/projectedge/reconcile.py` (NEW).
- Freeze family (150, consumable): `core_types/freeze.py` FreezeKind.CONTESTED_LOCAL_WRITES :17,
  RESOLVING_COMMANDS_BY_KIND[CONTESTED_LOCAL_WRITES]={"takeover_reconcile_clear"} :28. Entry is
  vocabulary-ONLY (no set_freeze(kind=contested) caller exists → AG3-151 wires ENTRY). Persistence:
  `state_backend/store/freeze_repository.py` set_freeze accepts any kind :182, read_freezes (whole
  family) :273, challenge-invalidation-on-entry :229. Admission fence is generic over kind
  (`ownership_fence.py:105-112` + `repository.py:136 _load_active_freezes`) → a contested row blocks
  all mutations except command `takeover_reconcile_clear`. NOTE: `ConflictFreezeOverlay.freeze()/
  release()` hard-code CONFLICT_FREEZE (`principal_capabilities/freeze.py:238,257`) → contested
  entry/exit uses `FreezeRepository` directly or a new thin overlay method, NOT the existing overlay.
- Reconcile contract (docks at transfer-record, NOT a new table): decision-record
  `concept/_meta/decisions/2026-07-09-takeover-challenge-persistence-und-reconcile-obligation.md`
  §2.4. Fields `TakeoverTransferRecord.reconciled_at/reconcile_ref` (`control_plane/records.py:287-288`,
  paired-null invariant :298-303). **LOAD-BEARING DRIFT:** `records.py:304` rejects any reconcile_ref
  not matching `_ADMIN_TRANSITION_REF_PATTERN=^admin_transition:[…]$` (:39-41) — AG3-151 MUST WIDEN this
  (add a `takeover_reconcile:{op_id}` form) so the regular reconcile endpoint can write the clear,
  WITHOUT weakening the admin-audit invariant. Admission read port
  `has_unreconciled_takeover_transfer_for_story_global` (`operation_ledger/__init__.py:636` →
  `_control_plane_rows.py:829`); rejection error_code `takeover_reconcile_required`
  (`runtime/_admission_rejections.py:67-83`). Admin clear path today: `runtime/_admin.py:150-269`
  (command `_TAKEOVER_RECONCILE_CLEAR="takeover_reconcile_clear"` :50), CAS
  `commit_takeover_reconcile_clear_global_row` (`_takeover_rows.py:306-344`).
- Transfer/disown surface: `control_plane/ownership_transfer.py` evaluate_takeover_confirm :248,
  OwnershipBasis :60-245; runtime `runtime/_ownership_transfer.py` (_active_freezes :114). Disown
  `control_plane/disown.py` build_disown_plan :49. Edge vocab `control_plane/edge_commands.py`:
  `takeover_reconcile` is a REGISTERED but NOT-yet-executable kind (CommandKind :56;
  EXECUTABLE_COMMAND_KINDS lacks it :74-76, comment :47-50 "owned by AG3-151") → 151 adds it to the
  executor set.
- Wire shapes (foundation-only, present): `control_plane/models.py` TakeoverErrorResult.result_type
  ∈ {remote_branch_diverged_after_takeover, local_stale_or_dirty_takeover_target,
  contested_local_writes} :1089-1095; TakeoverQuarantineDetail :1064-1076; worktree-identity probe
  (head_sha, marker_present) :1060. Edge resolve today models only binding_invalid
  (`projectedge/runtime.py:189-258`, :229/:244/:256).

## Biggest risk (design must address head-on)
Edge-side state-publication + fail-closed consumption (Scope §4 / AC1-2): the FOUR guard states must
round-trip server bundle assembly → edge bundle → `projectedge/runtime.py resolve()` → `.agent-guard`,
a surface modelling only `binding_invalid` today. Tests MUST drive it through the REAL AG3-148 transfer
+ AG3-145 command queue (testing-guardrail forbids hand-assembled state). Secondary: the records.py:304
pattern relaxation; and not silently reusing the conflict-freeze-only overlay for contested.

## Concept item to settle at freeze time
Decision-record §2.4/§6.6: AG3-151 uses BOTH surfaces — transfer-record obligation
(`takeover_reconcile_required`, the confirm→reconcile gate) AND freeze-family `contested_local_writes`
(the failed-reconcile freeze). Confirm they get DISTINCT error codes (§6.6, Repair-Lock vs
Reconcile-Obligation) and are not conflated. Same command id `takeover_reconcile_clear` serves both
the freeze resolver and the transfer-record clear → keep coherent (success clears BOTH).

## Suggested sequencing (scout)
1. Backend contracts: widen _ADMIN_TRANSITION_REF_PATTERN for takeover_reconcile:{op_id}; add the
   takeover-reconcile-worktree HTTP route (`control_plane_http/`); wire models reusing foundation shapes.
2. `control_plane/takeover_reconcile.py` (A-core, pure): per-repo SHA compare vs transfer-record
   takeover_base_sha; identity/diverged/stale classification; four state transitions.
3. Commission + persist: commission takeover_reconcile after confirm; clear obligation on success
   (extend _admin.py/commit_takeover_reconcile_clear); enter contested_local_writes freeze on failure
   (FreezeRepository.set_freeze + local export).
4. Edge executor: new `harness_client/projectedge/reconcile.py` (marker+path identity, same-worktree
   quarantine via quarantine.py, reprovision via provision_worktree); add takeover_reconcile to
   EXECUTABLE_COMMAND_KINDS; wire deployed `bundles/target_project/tools/agentkit/projectedge.py`.
5. Bundle publication + fail-closed consumption of the four states in projectedge/runtime.py + client.py.
6. Contract/negative/multi-repo tests through the real transfer + command-queue paths; SOLL-079 exit
   contract test (grep found NO lingering teardown call in story_exit/** → likely contract-test-only).

## Next action (post-freeze)
Adjudicate records.py:304 + the edge resolve() surface at code → author the frozen design note
(increments if warranted: backend contract+classifier+commission as Inc-1; edge executor+bundle
publication+fail-closed as Inc-2) → dispatch Codex worker → maturity (Codex + adjudicate-every-verdict
+ Fable finale). status.yaml still `blocked` → flip to ready at freeze time.
