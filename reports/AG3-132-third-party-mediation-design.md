# AG3-132 — Backend owns third-system reachability validation: DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-132-third-party-backend-mediation/story.md`. Size L, BC installation-and-bootstrap +
control_plane_http (host/router only). ONE story. Not LLM/hub — REAL integration tests (register-project
→ real route → faked third-systems at the thin-client boundary, AK3 mediation NOT stubbed). Grounded in
the scout brief (facts file:line-cited); do not re-derive.

## 0. The one open fork — RESOLVED: project-scoped route
`POST /v1/projects/{project_key}/installation/third-party-validation` (project-scoped). EVIDENCE: CP7
(backend registration, writes the central tenant row that TenantScopeMiddleware reads + the visible
project-management row) provably PRECEDES CP10d (Sonar/CI preflight) in the canonical checkpoint order
(bootstrap_checkpoints/registry.py; FK-50 §50.3 flow cp_07 → … → cp_10d). So the tenant EXISTS at
validation time → the project-scoped route gets tenant-existence (404 project_not_found), archived-guard,
and `project_api_token` project-binding FOR FREE from TenantScopeMiddleware + AuthMiddleware. NO unscoped
bootstrap variant, NO FK-72/FK-91 exception. (If a future story needs pre-CP7 validation, that ordering
does not exist today and would force the unscoped variant — out of scope here.)

## 1. Core-service home (FK-72 §72.8.2: one host, no per-BC mount)
Relocate the validation as an in-process CORE service, NOT verify_system HTTP, NOT app.py. Home: a new
`ThirdPartyPreflightService` under `backend/installer/` (e.g. `installer/third_party_preflight.py`),
built in the composition root (`bootstrap/composition_*`), delegated to by ONE thin route class in
`control_plane_http` (mirror TakeoverApprovalRoutes / ProjectManagementRoutes thin-route→service
delegation; the route serializes, the service decides). REUSE — do NOT rebuild — the existing preflight
logic (`installer/integration_checkpoints/sonar_preflight.check_sonarqube_preconditions`,
`ci_preflight.check_ci_preconditions`, `branch_plugin_self_test.run_branch_plugin_conformance_self_test`)
by moving it behind the service; all its external deps are already injected Protocols (relocatable).
`integration_clients` stay thin; NO second transport.

## 2. Light (sync) vs heavy (async op) split (AC1, AC4)
- **Light validation = SYNCHRONOUS** on the route: Sonar/Jenkins (+ARE, `features.are`-gated)
  reachability + token validity + light config (incl. branch-plugin PRESENCE). The BACKEND reaches the
  systems (I2). Typed Pydantic v2 request/response, per-system result, structured `error_code`s, `op_id`
  (idempotency via `inflight_idempotency_guard.run_route_idempotent`), `X-Correlation-Id`,
  version-handshake.
- **Heavy branch-plugin conformance self-test = ON-DEMAND ASYNC** (side-effecting: creates/deletes a
  Sonar project, polls Jenkins queue+build+CE task, up to 1800s). Return `202 + op_id`; reuse the
  `ControlPlaneOperationRecord` lifecycle (control_plane/runtime/_operation_records.py: claimed
  placeholder → terminal record + request_body_hash) + a `GET .../operations/{op_id}` reconcile poller
  (ProjectEdgeClient.reconcile_operation pattern). It runs ONLY when explicitly invoked — NOT implicitly
  on every register (AC4). It is NOT part of verify-project read-only (§6).

## 3. The one wobble — local default-profile file check stays dev-side (documented)
`sonar_preflight._check_default_profile` (:133-143) resolves `repo_root / default_profile` and requires
`.is_file()` on the DEV repo_root — the backend has no dev repo_root. This is a LOCAL config-artifact
sanity check, NOT a third-system reachability concern (FK-10 I2 is about DRIVING third systems). FREEZE:
keep this pure-local-FS profile-existence check DEV-SIDE as a pre-send config validation; move ONLY the
third-system PROBES (reachable/version/token-role/branch-plugin-presence) server-side. Document this
boundary explicitly in the service + concept — do NOT silently drop the profile check, and do NOT ship
a dev repo_root into the backend. (If the profile MUST be validated server-side, carry its content/
reference in the payload — but the default is: local artifact check stays local.)

## 4. Secret handling (P3) — references only, redaction mandatory
Config payloads carry only `*_env` REFERENCES (`sonarqube.token_env`/`ci.token_env` — the frozen config
models are already reference-only, never inline). The BACKEND resolves `os.environ.get(token_env)` in
ITS OWN env and reaches the systems; the installer sends the config stanza + reference names, NO secret
VALUES. Add EXPLICIT redaction at the service boundary (none exists today): never echo a resolved token
in the route response / CheckpointResult.detail / SonarPreflightResult.details / telemetry / logs;
ensure Sonar/Jenkins client errors (`str(exc)`) cannot embed the Basic-auth header. A redaction unit
test is required.

## 5. Installer consumes the verdict (AC2, AC3) — no dev-side clients
Register/verify checkpoints (sonar_preflight, ci_preflight wrappers in installer/runner.py) call the
backend route via the established `ProjectEdgeClient` seam (build_project_edge_client → control-plane.json
base_url/ca + `project_api_token` + version handshake; add a `validate_third_party(...)` method mirroring
`run_phase`/`_post_project_phase`, URL-encoding project_key; a reconcile-style poller for the async
self-test). The dev-side `SonarClient`/`JenkinsClient` instantiation
(installer_commands.py `_wire_sonar_install_integration` ~:281 / `_wire_ci_install_integration` ~:313 +
`_wire_branch_plugin_self_test_integration` ~:343) is REMOVED for these flows; the checkpoint reaches the
backend verdict into the existing CheckpointResult/InstallationError/exit semantics. REGRESSION PIN:
register-project/verify-project instantiate NO SonarClient/JenkinsClient in the dev process (static/import
+ runtime test).

## 6. verify-project read-only (premise) 
`verify-project` (read-only) may trigger LIVE reachability probes (reads) but NO mutating ops; adjust the
CP10d read-only modes (`cp10.py` ~:455/:466) so the live probe runs read-only. The heavy self-test
(side-effecting) is NOT triggered by verify-project — it is the explicit on-demand op only.

## 7. Fail-closed (AC3)
Backend unreachable → installer exit ≠ 0, structured message, NO dev-side fallback check. Sonar/Jenkins
unreachable/invalid token → the BACKEND returns a structured fail-closed verdict; the installer reaches
it into a fail-closed checkpoint abort. No bypass, no silent downgrade, no second (dev-side) reach.

## 8. Concept nachzug + dogfood W4 (AC-concept)
Normative edits (the W4 gate WILL trip → author `concept/_meta/decisions/2026-07-14-third-party-backend-
mediation.md` OR a `Concept-Decision:` trailer; prefer the record): FK-50 §50.2/§50.3 (core-validated
preflight replacing dev-side client/env-secret resolution; light-vs-heavy split), formal-spec/installer/
{commands,invariants,state-machine,scenarios}.md (new backend-preflight command + invariant + scenario;
verify read-only live-probe; the cp10d-self-test-as-on-demand-op), FK-91 §91.1a (the new sync validation
endpoint + the async self-test op row: path/method/request/response/error_code/op_id/X-Correlation-Id),
the FK-03 config-model doc (token_env resolved BACKEND-side), FK-10 §10.2.1/§10.2.2 as the sollbild
reference. Gate-semantics (FK-33 §33.6 / FK-27 §27.6a) UNCHANGED — only the reachability preflight moves.
Keep W1 reference-integrity + all 4 concept gates green; state/schema/contract changes pull the
contract/golden tests.

## 9. Tests (AC1-8) — real path + fail-closed + no-dev-client
Real integration (postgres_isolated_schema + in-process control-plane HTTP server, mirror
tests/integration/control_plane_http/test_version_handshake_e2e.py + tests/integration/installer/
test_register_project.py): register-project → real `control_plane_http` validation route → third-system
adapter boundary faked (FakeSonarClient/FakeCiBackend pattern — the AK3 mediation/preflight logic runs
FOR REAL, only the external system is faked, MOCKS-Regel). Required: (1) the reach originates from the
backend process (no dev client); (2) no-dev-client regression pin; (3) backend-unreachable → installer
exit≠0; (4) Sonar/Jenkins-unreachable → backend fail-closed verdict → installer fail-closed abort; (5)
heavy self-test as async op (202+op_id, poll to terminal, idempotent); (6) secret redaction; (7) light-
vs-heavy split (register does NOT run the heavy self-test implicitly). Contract-pin the request/response +
error_code + the FK-91 endpoint rows.

## 10. Blood types + review plan
Validation policy/verdict model = A; REST route/wire mappers = R; relocated third-system probes +
transport + file/CI = T (integration_clients stay thin). Worker owns green: pytest ex-e2e (-n0 for PG),
ruff, mypy strict native + --platform linux, coverage ≥85%, the 4 concept gates (W1 + W4 — the FK-50/
FK-91/formal edits need the dogfood record), remote gates (Jenkins green + Sonar 0/0/0). Then Codex
read-only review + orchestrator code-adjudication → whole-story Fable finale (this IS a fail-closed/I2/
secret surface — focus: the reach truly originates from the backend not a surviving dev client; no
secret value crosses the wire + redaction holds; backend-unreachable and system-unreachable both fail
VISIBLY closed with no dev-side fallback; the heavy self-test never runs implicitly; verify-project stays
read-only) → Jenkins + Sonar 0/0/0 on the final commit. Serialize: no orchestrator git/gate ops while the
worker is active on the shared tree.
