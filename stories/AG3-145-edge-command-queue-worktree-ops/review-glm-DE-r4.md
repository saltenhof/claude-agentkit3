# GLM r4 CONFIRMATION review — AG3-145 sub-steps D+E

Scope: independent confirmation of the adjudicated TEST-ONLY fix at HEAD
`e28b96b2` (`git --no-pager diff a3aa7d12..e28b96b2` — only
`tests/contract/backend/test_soll136_execution_location.py` changed,
+89/-35). Codex r3 REJECTED on (a) an evadable worktree-add guard,
(b) missed git-invocation forms, (c) a docstring overclaim. This review
checks whether the bounded fix closes all three without regression.

Method: static only. Read the diff and the full test module; re-grep
`src/agentkit/backend` independently with the four scan regexes to
confirm the 12==12 inventory; attempt to construct evading backend
`git worktree add` forms; ran `.venv/Scripts/python -m ruff check src tests`
and `.venv/Scripts/python -m mypy src` (both clean); ran the contract
test module in isolation (10 passed). No Postgres / control-plane DB
touched, no production / test / concept / CI file modified.

## Summary

All three Codex r3 findings are genuinely closed by the bounded test-only
delta. The docstring now names the retained AG3-152 teardown surface and
states precisely what the test verifies; the worktree-add guard is
form-comprehensive across argv-list, tuple argv, shell-string and
`os.system` (incl. f-strings and `shlex.split`), with `shutil.which("git")`
correctly excluded; the broadened scan recognizes tuple argv (comma-guarded),
`os.system` / shell-string and GitPython submodule imports, with an accurate
out-of-scope note for dynamically-built argv. Independent re-grep of
`src/agentkit/backend` confirms the inventory is exactly 12==12 (no
unassigned, no stale), so the drift proof is intact. No regression: the
delta touches only the AC11 contract test; AC7/AC8 and the other contract
assertions are untouched.

## Per-item confirmation

### 1. Docstring honesty — CONFIRMED

`tests/contract/backend/test_soll136_execution_location.py:24-28` now
explicitly names the retained AG3-152 backend worktree-teardown
primitives:

> the AG3-152 closure/merge block, which INCLUDES the RETAINED backend
> worktree-teardown primitives (``utils/git.py`` ``remove_worktree`` =
> ``git worktree remove`` / ``prune``, consumed by
> ``closure/multi_repo_saga.py``) -- retained by design and correctly
> assigned to AG3-152;

This matches production reality:
- `src/agentkit/backend/utils/git.py:153` defines `remove_worktree` and
  issues `["git", "-C", ..., "worktree", "prune"]` (the teardown
  primitive).
- `src/agentkit/backend/closure/multi_repo_saga.py:81` is the AG3-152
  closure saga that consumes it.

The earlier overclaim "NONE is a worktree provisioning/teardown/path op"
is removed. The replaced wording (lines 35-37) states the precise
verified claim:

> NO backend git call-site is UNASSIGNED, and NO AG3-145-scope
> worktree-PROVISIONING op (``git worktree add``) remains anywhere in the
> backend.

Claim == test behaviour:
- "no UNASSIGNED" == `test_every_backend_git_subprocess_site_is_assigned_in_the_inventory`
  (lines 271-289).
- "no `git worktree add`" == `test_no_backend_site_runs_git_worktree_add`
  (lines 304-321).

### 2. Worktree-add guard form-comprehensive — CONFIRMED

`_GIT_WORKTREE_ADD` at lines 299-301:

```
r"""["']worktree["']\s*,\s*["']add["']|["']git\s+worktree\s+add"""
```

The first alternative catches the argv adjacency
`"worktree", "add"` in EITHER a list OR a tuple (it is delimiter-agnostic
and `\s` matches newlines, so multiline argv is covered); the second
catches any quote-prefixed `git worktree add` literal (shell-string,
`os.system`, f-string, `shlex.split("git worktree add")`).

I exercised the regex from the project venv against the canonical forms:

| form | result |
|---|---|
| `subprocess.run(["git","worktree","add"])` (argv list) | CAUGHT |
| `subprocess.run(("git","worktree","add"))` (tuple argv) | CAUGHT |
| `os.system("git worktree add foo")` | CAUGHT |
| `subprocess.run(f"git worktree add {x}", shell=True)` (f-string) | CAUGHT |
| multiline `cmd=[\n "worktree",\n "add"\n]` | CAUGHT |
| `shlex.split("git worktree add")` | CAUGHT |
| `shutil.which("git")` (PATH lookup, not an invocation) | correctly EVADED |

Attempted evasion via dynamic construction
(`["worktree"]+["add"]`, `"git"+" worktree add"`, `["git","work"+"tree","add"]`,
`[*argv]`) evades — but those are undecidable dynamic-built forms that the
docstring at lines 91-94 and 257-261 explicitly scopes out, and the claim
asserts nothing beyond the literal forms. Zero offenders in
`src/agentkit/backend` today (test passes). The Codex r3 "literal argv only"
evasion is closed: tuple argv, shell-string and `os.system` are now caught.

### 3. Broadened scan honestly scoped — CONFIRMED

The scan now uses four regexes (`_GIT_INVOCATION_FORMS`, lines 95-100):

- `_GIT_ARGV_LIST` (line 70) — `["git", ...]`, multiline-capable.
- `_GIT_ARGV_TUPLE` (line 74) — `("git", ...)` with a COMMA guard, so
  `shutil.which("git")` (single arg, no comma) is correctly NOT matched.
  Verified directly: the comma guard excludes the PATH-lookup false
  positive the Codex r2/r3 review worried about.
- `_GIT_SHELL_STRING` (lines 80-82) — `os.system(...)` / `subprocess.\w+(...)`
  whose command literal starts with `git`; a prose `git ...` mention in a
  `#` comment or a ``` `git ...` ``` docstring is not quote-prefixed and is
  excluded.
- `_GITPYTHON` (lines 86-90) — now recognizes submodule imports via
  `from\s+git(?:\.[\w.]+)?\s+import\b` (the previous `from\s+git\s+import\b`
  would have missed `from git.submodule import ...`), plus `import git`,
  `import git.x` and `git.Repo(...)`.

Scope notes (lines 91-94 and 257-261) accurately state that a git argv
held in a variable and built dynamically is out of scope (undecidable),
and the docstring claims nothing beyond what these patterns verify.

Independent re-grep of `src/agentkit/backend` running the four regexes
from the project venv:

```
FOUND 12 INV 12
unassigned []
stale []
```

The 12 scanned files equal exactly the 12-entry `_GIT_SUBPROCESS_INVENTORY`
(lines 105-130). The drift proof
(`test_every_backend_git_subprocess_site_is_assigned_in_the_inventory`)
therefore remains intact: a new unassigned git call-site OR a stale
inventory entry both fail the test. The previously-missed
`verify_system/evidence/request_resolver.py` (multiline argv list,
`command = [\n "git", ...`) is correctly captured via `_GIT_ARGV_LIST`
because `\s` matches the newline, and is assigned to AG3-147 in the
inventory (line 115).

### 4. No regression — CONFIRMED

`git diff a3aa7d12..e28b96b2 --stat` shows the delta is test-only:
only `tests/contract/backend/test_soll136_execution_location.py`
(+89/-35). No production code, no AC7/AC8 surface, no other contract
assertion, no concept / status / README / CI / LOC-analyzer file
touched. AC7/AC8 live on different modules and are not imported or
referenced here. The 10 contract assertions in this module all pass
in isolation (10 passed in 2.77 s). `ruff check src tests` and
`mypy src` both clean.

## Findings

None. All three Codex r3 rejections are closed by the bounded test-only
fix; the worktree-add guard is genuinely form-comprehensive for every
literal invocation form; the broadened scan is honestly scoped with an
accurate out-of-scope note; the 12==12 inventory and drift proof are
intact; no regression.

VERDICT: APPROVE
