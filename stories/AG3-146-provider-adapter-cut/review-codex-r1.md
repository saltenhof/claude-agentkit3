## Summary

Core provider-adapter cut is architecturally sound: the new backend port is narrow, the GitHub adapter owns the `gh` subprocess boundary, `ref_read` is implemented through `git ls-remote`, and no production consumer imports the old generic `run_gh` facade outside `integration_clients/github/`.

I reject the review because AC7/ARCH-55 is not met: new production Python docstrings/comments contain German prose. That is a direct project-rule violation for code comments/docstrings.

Targeted verification run:

` .venv\Scripts\python -m pytest tests/unit/code_backend tests/contract/external_adapter_contracts tests/unit/integrations/github/test_adapter.py tests/unit/integrations/github/test_run_gh_boundary.py tests/unit/installer/test_repo_probe.py `

Result: 47 passed.

## Per-AC Verification

**AC1 - Capability set / no generic write surface:** PASS. `provider_port.py` exposes only `repo_probe`, `ref_read`, `read_compare_evidence`, and `capability_supported` over `CodeBackendCapability`. No merge/write capability exists. `integration_clients/github/__init__.py` exports only `GitHubCodeBackendAdapter`; `run_gh`, `run_gh_json`, and `run_gh_graphql` remain in `integration_clients/github/client.py` and are not package exports.

**AC2 - ls-remote / fail-closed:** PASS. `GitLsRemoteReader.read_head_sha()` runs fixed-argv `git ls-remote --exit-code <remote> <ref>` and converts subprocess errors, non-zero exits, empty output, ambiguous output, and unparsable output into `RefReadResult(resolved=False, head_sha=None, detail=...)`. Tests use a real local bare-repo fixture.

**AC3 - gh only in GitHub adapter / CP2 fail-closed:** PASS. Grep found actual `["gh", ...]` subprocess invocations only under `src/agentkit/integration_clients/github/`. `repo_probe.py` routes through `build_github_code_backend_port(...).repo_probe()`, and CP2 maps negative probe outcomes to `FAILED` for repo missing, gh missing, and auth missing.

**AC4 - Provider CLI optional:** PASS. Missing `gh` yields a named unavailable result for `repo_probe`; `ref_read` remains supported and delegates to `git ls-remote` without consulting `gh`.

**AC5 - Azure DevOps substitutability:** PASS. The port signatures have no GitHub URL, owner/repo, gh-argument, or slug semantics. The contract suite is parameterized across `GitHubCodeBackendAdapter` and `FakeAzureDevOpsCodeBackendAdapter`, a real `CodeBackendPort` implementation using the same git-protocol read mechanic. The shared contract excludes `repo_probe` to avoid live provider/gh dependence, with per-adapter coverage for that method.

**AC6 - Single provider path / no run_gh consumers:** PASS. The boundary test parses `src/agentkit/**/*.py` and fails if a module outside `agentkit.integration_clients.github` imports `run_gh`, `run_gh_json`, `run_gh_graphql`, or `resolve_token_for_owner`; manual grep agrees.

**AC7 - Cross-cutting:** FAIL. Capability codes and wire keys are English, and the registration wire contract remains unchanged (`github_owner`/`github_repo`, `--gh-owner`/`--gh-repo`). `github_coordinates.py` behavior remains github.com-only and fail-closed. However, new Python docstrings/comments contain German prose, violating ARCH-55.

## Doctor `which('gh')` Adjudication

PASS. `src/agentkit/backend/cli/main.py:1335` only reports local tool availability in `agentkit doctor` via `shutil.which('gh')`. It does not bind provider coordinates, perform provider access, check auth, or execute `gh`. Routing this diagnostic through `CodeBackendPort.capability_supported()` would incorrectly require a bound repository just to print whether the CLI binary exists.

## Manual A-Core AT-Freeness Verification

PASS. `src/agentkit/backend/code_backend/provider_port.py` imports only `__future__`, `dataclasses`, `enum`, and `typing`. It imports no `integration_clients`, no `subprocess`, no `git`/`gh` mechanic, and no project module that would transitively pull those in. `code_backend/__init__.py` re-exports only names from `provider_port.py`.

The T mechanics are outside the A-core: `git_protocol.py` owns `git ls-remote`, and `integration_clients/github/adapter.py` owns `gh repo view`.

## Findings

**MAJOR - ARCH-55 violation in new Python docstrings/comments**

Files/lines:
`src/agentkit/backend/code_backend/provider_port.py:3`, `src/agentkit/backend/code_backend/provider_port.py:149`, `src/agentkit/backend/code_backend/git_protocol.py:3`, `src/agentkit/backend/code_backend/git_protocol.py:6`, `src/agentkit/backend/code_backend/__init__.py:7`, `src/agentkit/backend/bootstrap/composition_root.py:3470`, `tests/contract/external_adapter_contracts/test_code_backend_port_contract.py:6`.

Failure scenario: an ARCH-55 sweep or review gate rejects the story because code comments/docstrings include German terms such as `PO-Direktive`, `Azure-DevOps-Tauglichkeit`, `backend-seitige ... Zugriffe`, `Verifikation`, and `kein Worktree noetig`. ARCH-55 explicitly covers comments and docstrings, not only identifiers and wire keys.

Fix direction: translate these docstring/comment phrases to English while keeping exact concept paths and story references where needed, e.g. `PO Directive III`, `Azure DevOps readiness`, `backend-side subprocess git access`, `verification`, `no worktree needed`.

**MINOR - no-worktree test does not actually run from the neutral directory**

File/line: `tests/unit/code_backend/test_git_protocol.py:93`.

Failure scenario: `test_no_worktree_or_physical_repo_access_required()` creates `neutral_cwd` but never changes the process cwd or passes it to the subprocess. The read therefore runs from pytest's current cwd, which is typically the repository worktree. A future regression with unintended cwd dependence could still pass this test.

Fix direction: use `monkeypatch.chdir(neutral_cwd)` around the `GitLsRemoteReader().read_head_sha(...)` call, or otherwise assert the subprocess is invoked from a non-repo cwd.

VERDICT: REJECT
