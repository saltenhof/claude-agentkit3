"""Unit tests for OperationClass enum + OperationClassifier (FK-55 §55.5, AK3)."""

from __future__ import annotations

from agentkit.backend.governance.principal_capabilities import OperationClass, OperationClassifier
from agentkit.backend.governance.principal_capabilities.operations import (
    bash_mutation_targets,
    is_subagent_spawn,
)

_CLF = OperationClassifier()


def test_operationclass_has_exactly_six_values() -> None:
    # AK3: FK-55 §55.5 defines exactly six operation classes.
    assert len(OperationClass) == 6
    assert {o.value for o in OperationClass} == {
        "read",
        "write",
        "execute",
        "git_mutation",
        "curate",
        "admin_transition",
    }


def test_structured_tools_map() -> None:
    assert _CLF.classify("Write", {}) is OperationClass.WRITE
    assert _CLF.classify("Edit", {}) is OperationClass.WRITE
    assert _CLF.classify("Read", {}) is OperationClass.READ
    assert _CLF.classify("Grep", {}) is OperationClass.READ


def test_harness_operation_values_map() -> None:
    assert _CLF.classify("file_read", {}) is OperationClass.READ
    assert _CLF.classify("file_write", {}) is OperationClass.WRITE
    assert _CLF.classify("file_edit", {}) is OperationClass.WRITE


def test_git_mutation_vs_git_read() -> None:
    assert _CLF.classify("Bash", {"command": "git push --force"}) is (
        OperationClass.GIT_MUTATION
    )
    assert _CLF.classify("Bash", {"command": "git commit -m x"}) is (
        OperationClass.GIT_MUTATION
    )
    assert _CLF.classify("Bash", {"command": "git status"}) is OperationClass.READ


def test_git_branch_listing_is_read() -> None:
    # ERROR B / FK-55 §55.5: a bare/listing ``git branch`` is a READ. No .git
    # mutation target is surfaced (so a worker is not over-blocked on it).
    for cmd in (
        "git branch",
        "git branch --list",
        "git branch -a",
        "git branch -r",
        "git branch -v",
        "git branch -vv",
        "git branch --all",
        "git branch --show-current",
        "git branch --contains HEAD",
        "git branch --merged main",
        "git branch --format=%(refname)",
    ):
        assert _CLF.classify("Bash", {"command": cmd}) is OperationClass.READ, cmd
        assert bash_mutation_targets(cmd) == [], cmd


def test_git_branch_mutation_is_git_mutation_with_git_target() -> None:
    # ERROR B / FK-55 §55.5: a creating/renaming/deleting/upstream-setting
    # ``git branch`` is a GIT_MUTATION targeting the repository internals (.git),
    # NOT a READ. This was the misclassification (branch in the read set).
    for cmd in (
        "git branch -D foo",
        "git branch -d foo",
        "git branch --delete foo",
        "git branch -m old new",
        "git branch -M main",
        "git branch --move a b",
        "git branch -c a b",
        "git branch -C a b",
        "git branch --copy a b",
        "git branch --set-upstream-to=origin/main",
        "git branch -u origin/main",
        "git branch --unset-upstream",
        "git branch -f foo origin/main",
        "git branch newbranch",  # bare create
        "git branch newbranch origin/main",  # create from start-point
    ):
        assert _CLF.classify("Bash", {"command": cmd}) is (
            OperationClass.GIT_MUTATION
        ), cmd
        assert ".git" in bash_mutation_targets(cmd), cmd


def test_git_worktree_is_git_mutation() -> None:
    # ERROR B: ``git worktree add/remove`` mutates the repo → GIT_MUTATION with a
    # .git target (verifies the existing behavior is correct).
    for cmd in ("git worktree add ../wt", "git worktree remove ../wt"):
        assert _CLF.classify("Bash", {"command": cmd}) is (
            OperationClass.GIT_MUTATION
        ), cmd
        assert ".git" in bash_mutation_targets(cmd), cmd


def test_shell_exec_default() -> None:
    assert _CLF.classify("Bash", {"command": "pytest -q"}) is OperationClass.EXECUTE


def test_bash_file_mutation_is_write_not_execute() -> None:
    # FK-55 §55.10.2: visible Bash file mutations (redirect / mutating verb)
    # are WRITE, never collapsed to execute — even without a git subcommand.
    assert _CLF.classify("Bash", {"command": "rm -rf .git/index"}) is OperationClass.WRITE
    assert _CLF.classify(
        "Bash", {"command": "echo x > _temp/governance/freeze.json"}
    ) is OperationClass.WRITE
    assert _CLF.classify(
        "Bash", {"command": "tee var/context.json"}
    ) is OperationClass.WRITE
    assert _CLF.classify("Bash", {"command": "mv a b"}) is OperationClass.WRITE
    assert _CLF.classify("Bash", {"command": "cp a b"}) is OperationClass.WRITE


def test_bash_mutation_targets_extracts_redirect_and_operands() -> None:
    # ERROR 4: the mutated target paths are surfaced for path classification.
    assert ".git/index" in bash_mutation_targets("rm -rf .git/index")
    assert "_temp/governance/freeze.json" in bash_mutation_targets(
        "echo x > _temp/governance/freeze.json"
    )
    assert "var/context.json" in bash_mutation_targets("tee var/context.json")
    # A git mutation surfaces the repository-internal target (.git).
    assert ".git" in bash_mutation_targets("git commit -m x")
    # A read-only git command surfaces no mutation target.
    assert bash_mutation_targets("git status") == []
    # A plain exec surfaces no target.
    assert bash_mutation_targets("pytest -q") == []


def test_chained_mutation_after_benign_lead_is_write() -> None:
    # FK-55 §55.10.2: a benign leading command must NOT mask a mutating follow-up
    # in a VISIBLE top-level chain. The classifier evaluates EVERY top-level
    # sub-command.
    assert _CLF.classify(
        "Bash", {"command": "git status && rm .git/index"}
    ) is OperationClass.WRITE  # benign git read + rm mutation → WRITE wins
    # A git read followed by a git mutation surfaces git_mutation.
    assert _CLF.classify(
        "Bash", {"command": "git status && git commit -m x"}
    ) is OperationClass.GIT_MUTATION
    assert _CLF.classify(
        "Bash", {"command": "echo ok ; rm _temp/governance/x"}
    ) is OperationClass.WRITE
    assert _CLF.classify(
        "Bash", {"command": "echo ok | tee _temp/governance/freeze.json"}
    ) is OperationClass.WRITE
    assert _CLF.classify(
        "Bash", {"command": "ls\nrm .git/index"}
    ) is OperationClass.WRITE


def test_interpreter_wrapped_mutation_is_execute_out_of_scope() -> None:
    # FK-55 §55.1a Schicht A boundary: a mutation hidden inside an interpreter
    # (``bash -c '<script>'`` / ``sh -c "..."``) is active obfuscation (threat
    # level 3 / Schicht B) and is explicitly OUT OF SCOPE for this layer. The
    # wrapper is NOT unwrapped; the visible command (``bash``) is a plain exec.
    assert _CLF.classify(
        "Bash", {"command": "bash -c 'rm .git/index'"}
    ) is OperationClass.EXECUTE
    assert _CLF.classify(
        "Bash", {"command": 'sh -c "rm _temp/governance/x"'}
    ) is OperationClass.EXECUTE
    # Nested wrappers are likewise not recursed into.
    assert _CLF.classify(
        "Bash", {"command": "bash -c 'sh -c \"rm .git/index\"'"}
    ) is OperationClass.EXECUTE
    # No visible mutation target is fabricated from the wrapped script.
    assert bash_mutation_targets("bash -c 'rm .git/index'") == []


def test_substitution_hidden_mutation_is_execute_out_of_scope() -> None:
    # FK-55 §55.1a Schicht A boundary: a mutation hidden in a ``$(...)`` /
    # backtick command substitution is threat level 3 — NOT extracted, NOT
    # blocked here. It classifies as a plain exec and surfaces no fabricated
    # target (the cheap classifier does not interpret substitutions).
    assert _CLF.classify(
        "Bash", {"command": "echo $(rm .git/index)"}
    ) is OperationClass.EXECUTE
    assert _CLF.classify(
        "Bash", {"command": "echo `rm .git/index`"}
    ) is OperationClass.EXECUTE
    assert bash_mutation_targets("echo $(rm .git/index)") == []
    assert bash_mutation_targets("echo `rm .git/index`") == []


def test_chained_mutation_targets_collected() -> None:
    # FK-55 §55.10.2: targets from EVERY visible top-level sub-command collected.
    assert ".git/index" in bash_mutation_targets("git status && rm .git/index")
    assert "_temp/governance/x" in bash_mutation_targets("echo ok; rm _temp/governance/x")
    assert "_temp/governance/freeze.json" in bash_mutation_targets(
        "echo ok | tee _temp/governance/freeze.json"
    )
    # The benign leading command surfaces no spurious target.
    targets = bash_mutation_targets("git status && rm .git/index")
    assert "status" not in targets


def test_fd_prefixed_and_combined_redirects_recognised() -> None:
    # FK-55 §55.10.2: fd-prefixed (``1>>``) and combined (``&>``) redirects into a
    # protected zone are visible mutations with a clean target.
    assert _CLF.classify(
        "Bash", {"command": "echo x 1>>.git/config"}
    ) is OperationClass.WRITE
    assert ".git/config" in bash_mutation_targets("echo x 1>>.git/config")
    assert _CLF.classify(
        "Bash", {"command": "echo x &> .git/config"}
    ) is OperationClass.WRITE
    assert ".git/config" in bash_mutation_targets("echo x &> .git/config")


def test_visible_redirect_into_protected_zone_is_write() -> None:
    # FK-55 §55.10.2: a plainly-visible redirect into a protected zone is a WRITE
    # with a clean surfaced target, regardless of the (benign) leading verb.
    assert _CLF.classify(
        "Bash", {"command": "echo x > _temp/governance/freeze.json"}
    ) is OperationClass.WRITE
    assert "_temp/governance/freeze.json" in bash_mutation_targets(
        "echo x > _temp/governance/freeze.json"
    )


def test_classifier_does_not_overblock_benign_commands() -> None:
    # Benign reads / execs stay EXECUTE/READ (no over-blocking, no raw-text net).
    assert _CLF.classify("Bash", {"command": "git status"}) is OperationClass.READ
    assert _CLF.classify("Bash", {"command": "pytest -q"}) is OperationClass.EXECUTE
    assert _CLF.classify("Bash", {"command": "cat README.md"}) is OperationClass.EXECUTE
    # A redirect into an UNprotected file is a plain WRITE (not a protected target).
    assert _CLF.classify(
        "Bash", {"command": "echo x > out.txt"}
    ) is OperationClass.WRITE
    assert "out.txt" in bash_mutation_targets("echo x > out.txt")


def test_agentkit_admin_transition() -> None:
    assert _CLF.classify("Bash", {"command": "agentkit reset-story --story X"}) is (
        OperationClass.ADMIN_TRANSITION
    )
    assert _CLF.classify("Bash", {"command": "agentkit split-story X"}) is (
        OperationClass.ADMIN_TRANSITION
    )


def test_unknown_tool_is_execute_not_mutation() -> None:
    # FK-55 §55.6.1: an unknown tool is an UNKNOWN PERMISSION, not a mutation. It
    # classifies as the inert EXECUTE so the enforcement pipeline resolves it
    # mode-scharf (story_execution ⇒ BLOCK; otherwise defer to the mode rule /
    # CCAG) rather than hard-blocking it as an unclassified mutation. Turning an
    # unknown tool into WRITE was the over-block this rework removes.
    assert _CLF.classify("MysteryTool", {}) is OperationClass.EXECUTE
    assert _CLF.classify("Task", {}) is OperationClass.EXECUTE
    assert _CLF.classify("TodoWrite", {}) is OperationClass.EXECUTE
    # The four structured edit tools remain known WRITE mutations.
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert _CLF.classify(tool, {}) is OperationClass.WRITE


def test_web_tools_are_known_read() -> None:
    # AG3-036 FIX-1 / FK-55 §55.5 / FK-68 §68.6.1: a research web tool (WebFetch /
    # WebSearch) is a KNOWN, non-mutating READ — both when the name is the
    # operation name directly AND when it arrives as the harness ``unknown_tool``
    # operation carrying its (alias-tolerant) name in ``args["tool_name"]``.
    assert _CLF.classify("WebFetch", {}) is OperationClass.READ
    assert _CLF.classify("WebSearch", {}) is OperationClass.READ
    assert (
        _CLF.classify("unknown_tool", {"tool_name": "WebFetch"})
        is OperationClass.READ
    )
    assert _CLF.is_known("WebFetch") is True
    assert _CLF.is_known("unknown_tool", {"tool_name": "WebSearch"}) is True
    # A genuinely unknown tool stays UNKNOWN / inert EXECUTE.
    assert _CLF.is_known("unknown_tool", {"todos": []}) is False
    assert _CLF.classify("unknown_tool", {"todos": []}) is OperationClass.EXECUTE


def test_web_tool_aliases_classify_as_read() -> None:
    # AG3-036 FIX-2: every alias / casing form of the two web surfaces is a known
    # READ (the canonicalization is shared with the runner edge ``_event_tool``).
    for alias in (
        "web_fetch",
        "web-fetch",
        "WEBFETCH",
        "web_search",
        "web-search",
        "WEBSEARCH",
    ):
        assert (
            _CLF.classify("unknown_tool", {"tool_name": alias})
            is OperationClass.READ
        ), alias
        assert _CLF.is_known("unknown_tool", {"tool_name": alias}) is True, alias


def test_agent_spawn_is_known_and_recognised() -> None:
    # FIX A (FK-31 §31.7 / FK-91 §91.4): the Agent sub-agent spawn is a KNOWN
    # operation so it is NEVER the §55.6.1 unknown_permission block; is_subagent_spawn
    # recognises both the harness ``unknown_tool`` carrier and the literal name.
    assert is_subagent_spawn("unknown_tool", {"tool_name": "Agent"}) is True
    assert is_subagent_spawn("Agent", None) is True
    # A non-Agent operation name with no args is not a spawn (None-args branch).
    assert is_subagent_spawn("unknown_tool", None) is False
    assert is_subagent_spawn("unknown_tool", {"tool_name": "Bash"}) is False
    assert is_subagent_spawn("unknown_tool", {"todos": []}) is False
    assert _CLF.is_known("unknown_tool", {"tool_name": "Agent"}) is True
    # It still normalises to the inert EXECUTE (the enforcement layer routes it).
    assert (
        _CLF.classify("unknown_tool", {"tool_name": "Agent"})
        is OperationClass.EXECUTE
    )


def test_curate_reachable_via_admin_only_path() -> None:
    # curate has no harness tool; it is reachable as an enum value used by the
    # matrix. Cover its membership explicitly (AK3 all-values reachable).
    assert OperationClass("curate") is OperationClass.CURATE


def test_all_six_operationclasses_reachable_from_classifier_or_enum() -> None:
    reached = {
        _CLF.classify("Read", {}),
        _CLF.classify("Write", {}),
        _CLF.classify("Bash", {"command": "pytest"}),
        _CLF.classify("Bash", {"command": "git push"}),
        _CLF.classify("Bash", {"command": "agentkit reset-story"}),
        OperationClass.CURATE,
    }
    assert reached == set(OperationClass)
