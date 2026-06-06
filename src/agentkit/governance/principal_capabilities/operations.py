"""Operation classes and deterministic tool normalization (FK-55 §55.5/§55.10.2).

:class:`OperationClass` transcribes the six canonical operation classes of FK-55
§55.5 (same wire values as the FK-55 glossary ``operation-class`` term).
:class:`OperationClassifier` normalizes a tool call to exactly one operation
class using only the tool name plus *cheap* argument inspection (FK-55 §55.10.2 —
no expensive semantic shell interpretation).

Scope boundary (FK-55 §55.1a Schicht A). This is the threat-level-1+2 layer
(negligent + disobedient-but-non-evasive). It does NOT chase active obfuscation
(threat level 3 / Schicht B). A command that hides its mutation behind an
interpreter (``bash -c '<script>'``), a command substitution or other evasion is
treated as a plain ``execute`` — OUT OF SCOPE by design, not waved through by a
fabricated target. An unknown tool is an UNKNOWN PERMISSION, not a mutation
(FK-55 §55.6.1): it classifies as the inert :attr:`OperationClass.EXECUTE` so the
enforcement pipeline resolves it mode-scharf (see :meth:`OperationClassifier.is_known`).

For ``Bash`` the classifier neither collapses every non-git command to
``execute`` nor looks only at the LEADING command. The string is split on
top-level separators (``;`` / ``&&`` / ``||`` / ``|`` / ``&`` / newlines) and
EVERY visible sub-command is evaluated for its leading verb (mutating shell verb
→ ``write``, git subcommand → read vs git_mutation, agentkit admin verb →
admin_transition) and for redirects (``>`` / ``>>`` / ``2>`` / ``&>`` →
``write``) — so a benign leading command cannot mask a mutating follow-up (FK-55
§55.10.2). :func:`bash_mutation_targets` exposes every visible mutated target so
the path classifier can resolve each path class (an unclassifiable SEEN target on
a mutating op is a fail-closed BLOCK in the enforcement layer). No ``bash -c``
unwrapping, no command-substitution extraction (Schicht B, out of scope).
"""

from __future__ import annotations

import shlex
from enum import StrEnum

#: Canonical research web-tool names (FK-68 §68.6.1: WebSearch / WebFetch). These
#: are the ONLY two web surfaces the concept budgets; both are non-mutating reads
#: in the repo-mutation sense (FK-55 §55.5 ``read``), so the worker principal may
#: issue them (FK-55 §55.7.2 read; FK-22 §22.5.1 research stories run AI-augmented
#: and recurse web search). Aliases (``web_fetch`` / ``web-search`` / mixed
#: casing) MUST canonicalize to one of these before any ``_WEB_TOOLS`` comparison
#: (AG3-036 FIX-2 — a casing/alias gap would fail OPEN past the budget guard).
WEB_FETCH = "WebFetch"
WEB_SEARCH = "WebSearch"

#: Alias → canonical web-tool mapping. Keyed by the case-insensitive,
#: separator-normalized (``-``/``_``/space → ``""``) tool name so ``web_fetch``,
#: ``web-search``, ``WEBFETCH`` and ``Web Search`` all resolve. Single source for
#: the runner edge and the OperationClassifier (FK-68 §68.6.1 / FK-55 §55.5).
_WEB_TOOL_ALIASES: dict[str, str] = {
    "webfetch": WEB_FETCH,
    "websearch": WEB_SEARCH,
}


def _web_alias_key(tool_name: str) -> str:
    """Normalize a tool name to its alias-lookup key (lower, separator-stripped)."""
    return tool_name.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def canonical_web_tool(tool_name: str) -> str | None:
    """Return the canonical web-tool name for ``tool_name``, or ``None``.

    Canonicalizes every alias / casing form of the two budgeted web surfaces to
    :data:`WEB_FETCH` / :data:`WEB_SEARCH` BEFORE any ``_WEB_TOOLS`` membership
    check (AG3-036 FIX-2). ``web_fetch`` / ``web-search`` / ``WEBFETCH`` /
    ``Web Search`` all resolve; a non-web tool returns ``None``.

    Args:
        tool_name: The raw (harness-preserved) tool name.

    Returns:
        The canonical ``"WebFetch"`` / ``"WebSearch"`` string, or ``None`` when
        ``tool_name`` is not a web tool.
    """
    return _WEB_TOOL_ALIASES.get(_web_alias_key(tool_name))


def is_web_tool(tool_name: str) -> bool:
    """Whether ``tool_name`` is one of the budgeted web surfaces (alias-tolerant)."""
    return canonical_web_tool(tool_name) is not None


class OperationClass(StrEnum):
    """The six canonical AK3 operation classes (FK-55 §55.5).

    Wire values are normative (FK-55 glossary ``operation-class``).
    """

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    GIT_MUTATION = "git_mutation"
    CURATE = "curate"
    ADMIN_TRANSITION = "admin_transition"


class _GitVerbs:
    """Cheap git/agentkit token sets (FK-55 §55.5 / §55.10.2 — single source).

    These live in a class body (not as module-level constants) so the module top
    level stays thin (project LOC linter); the free git-classification helpers
    reference them as class attributes. Built once at import; no per-call cost.
    """

    #: Unconditionally read-only git subcommands (FK-55 §55.5: "lesende Git-/
    #: Shell-Aufrufe" → read). ``branch`` is deliberately NOT here: a bare/listing
    #: ``git branch`` is READ but any creating/renaming/deleting/setting form is a
    #: GIT_MUTATION (FK-55 §55.5 "Branch-/Worktree-Aenderung"); see
    #: :func:`_is_git_read` / :func:`_branch_is_read`.
    READ_SUBCOMMANDS: frozenset[str] = frozenset({"status", "log", "diff", "show", "rev-parse", "ls-files", "blame"})

    #: ``git branch`` flags that KEEP it a pure listing/inspection (still READ).
    #: Any flag NOT in this set (``-d``/``-D``/``--delete``/``-m``/``-M``/
    #: ``--move``/``-c``/``-C``/``--copy``/``-u``/``--set-upstream-to``/
    #: ``--unset-upstream``/``-f``/``--force`` …) — or any positional branch name
    #: (a create) — makes it a mutation (FK-55 §55.5).
    BRANCH_READ_FLAGS: frozenset[str] = frozenset(
        {
            "-a",
            "--all",
            "-r",
            "--remotes",
            "-v",
            "-vv",
            "--verbose",
            "-l",
            "--list",
            "--show-current",
            "--contains",
            "--no-contains",
            "--merged",
            "--no-merged",
            "--points-at",
            "--color",
            "--no-color",
            "--column",
            "--no-column",
            "--sort",
            "--format",
            "-i",
            "--ignore-case",
            "--abbrev",
            "--no-abbrev",
        }
    )

    #: ``git branch`` listing flags that consume the FOLLOWING token as their
    #: value (so that token is NOT a create-name positional). Cheap, conservative
    #: subset; ``--flag=value`` forms are self-contained and need no entry here.
    BRANCH_VALUE_FLAGS: frozenset[str] = frozenset(
        {
            "--contains",
            "--no-contains",
            "--merged",
            "--no-merged",
            "--points-at",
            "--sort",
            "--format",
            "--color",
            "--column",
            "--abbrev",
        }
    )

    #: AK3 official admin CLI verbs (FK-55 §55.5 admin_transition / §55.9 service
    #: paths): reset, split, conflict resolution, registered service paths.
    ADMIN_SUBCOMMANDS: frozenset[str] = frozenset({"reset-story", "split-story", "resolve-conflict", "cleanup"})

    #: File-mutating shell verbs (FK-55 §55.10.2 — Bash file mutations must be
    #: recognised directly, not collapsed to ``execute``). These produce a WRITE
    #: when they are the leading verb of a visible sub-command.
    MUTATING_SHELL_VERBS: frozenset[str] = frozenset(
        {
            "rm",
            "mv",
            "cp",
            "tee",
            "touch",
            "mkdir",
            "rmdir",
            "chmod",
            "chown",
            "ln",
            "truncate",
            "dd",
            "install",
            "sed",  # in-place sed (-i) mutates; conservative WRITE
        }
    )


class OperationClassifier:
    """Normalizes a tool call to exactly one :class:`OperationClass`.

    Decision order (most specific first):

    1. Harness ``operation`` pre-class (``file_read`` / ``file_write`` / ...).
    2. Structured tool name (``Write`` → write, ``Read`` → read, ...).
    3. ``Bash`` command signature: split into visible top-level sub-commands,
       each evaluated for git mutation / git read / admin / file mutation
       (redirect / mutating verb → WRITE) vs plain exec. ANY mutating
       sub-command wins.
    4. Unknown tool → :attr:`OperationClass.EXECUTE` (an unknown permission, not
       a mutation — resolved mode-scharf downstream, FK-55 §55.6.1).
    """

    #: Tool-name → operation-class mapping for the harness's structured tools
    #: (FK-55 §55.5 examples). Keys are compared case-insensitively. Only the four
    #: structured edit tools are KNOWN mutations; every other (unknown) tool is an
    #: unknown permission resolved mode-scharf as ``execute`` (FK-55 §55.6.1).
    _TOOL_MAP: dict[str, OperationClass] = {
        "read": OperationClass.READ,
        "grep": OperationClass.READ,
        "glob": OperationClass.READ,
        "ls": OperationClass.READ,
        "write": OperationClass.WRITE,
        "edit": OperationClass.WRITE,
        "multiedit": OperationClass.WRITE,
        "notebookedit": OperationClass.WRITE,
    }

    #: Harness-neutral ``HookEvent.operation`` values (FK-30 guard_evaluation)
    #: that pre-classify the operation without a tool name.
    _OPERATION_MAP: dict[str, OperationClass] = {
        "file_read": OperationClass.READ,
        "file_write": OperationClass.WRITE,
        "file_edit": OperationClass.WRITE,
    }

    def is_known(
        self, operation_name: str, args: dict[str, object] | None = None
    ) -> bool:
        """Whether the classifier can positively map ``operation_name``.

        FK-55 §55.6.1 distinguishes a KNOWN tool (Read/Write/Edit/Bash/git/
        agentkit/WebFetch/WebSearch/… — mapped to a concrete operation class)
        from an UNKNOWN permission (a tool the classifier has no rule for). The
        enforcement layer uses this to resolve an unknown tool *mode-scharf*
        (story_execution ⇒ BLOCK + permission_request; interactive/ai_augmented ⇒
        defer) instead of force-fitting it to a matrix-matching ``execute`` ALLOW
        (the AG3-032 ERROR C fail-open hole). ``classify`` still returns the inert
        :attr:`OperationClass.EXECUTE` for an unknown tool (so CCAG / downstream
        keep working); this predicate is the explicit unknown signal.

        A research web tool (WebFetch / WebSearch, AG3-036 FIX-1) is KNOWN: it
        arrives as the harness ``unknown_tool`` operation carrying its canonical
        name in ``args["tool_name"]`` (FK-68 §68.6.1) and maps to the non-mutating
        :attr:`OperationClass.READ` (FK-55 §55.5 ``read`` — a worker may issue it,
        §55.7.2). Recognising it here is what lets it PASS capability enforcement
        and reach the budget hook instead of being blocked as an unknown tool.

        Args:
            operation_name: The tool name or harness ``operation`` value.
            args: Optional tool arguments. Inspected for the web-tool
                ``"tool_name"`` (how WebFetch / WebSearch arrive past the
                ``unknown_tool`` operation).

        Returns:
            ``True`` iff the tool maps to a concrete operation class (structured
            tool, harness operation, a shell command, or a web tool); ``False``
            for an unknown tool.
        """
        if self._web_tool_from(operation_name, args) is not None:
            return True
        key = operation_name.strip().lower()
        return key in self._OPERATION_MAP or key in self._TOOL_MAP or key in ("bash", "bash_command", "shell")

    def classify(self, operation_name: str, args: dict[str, object]) -> OperationClass:
        """Classify a tool/operation call.

        Args:
            operation_name: The tool name (e.g. ``"Write"``, ``"Bash"``) or the
                harness ``operation`` value (e.g. ``"file_write"``).
            args: Tool arguments. For ``Bash`` the ``"command"`` key (or
                ``"cmd"``) is inspected with cheap token matching only. For a web
                tool the ``"tool_name"`` key carries the (alias-tolerant)
                WebFetch / WebSearch name.

        Returns:
            Exactly one :class:`OperationClass`.
        """
        # AG3-036 FIX-1: a research web tool (WebFetch / WebSearch, alias-tolerant)
        # is a non-mutating READ (FK-55 §55.5 / FK-68 §68.6.1). It arrives as the
        # harness ``unknown_tool`` operation carrying its name in
        # ``args["tool_name"]``; classifying it as READ lets it pass the matrix
        # (worker READ, §55.7.2) and reach the budget hook.
        if self._web_tool_from(operation_name, args) is not None:
            return OperationClass.READ
        key = operation_name.strip().lower()
        if key in self._OPERATION_MAP:
            return self._OPERATION_MAP[key]
        if key in self._TOOL_MAP:
            return self._TOOL_MAP[key]
        if key in ("bash", "bash_command", "shell"):
            return self._classify_shell(args)
        # Unknown tool: an UNKNOWN PERMISSION, not a mutation (FK-55 §55.6.1).
        # EXECUTE is the inert non-mutating class so the enforcement pipeline
        # resolves it mode-scharf (via :meth:`is_known` → UNKNOWN_PERMISSION)
        # rather than treating it as an unclassified mutation. The classifier
        # does NOT consult the matrix for an unknown tool — the enforcement layer
        # signals UNKNOWN_PERMISSION before any ALLOW (AG3-032 ERROR C).
        return OperationClass.EXECUTE

    def _classify_shell(self, args: dict[str, object]) -> OperationClass:
        """Classify a shell command across ALL its visible sub-commands.

        Splits the command on top-level separators (FK-55 §55.10.2) and reduces
        the per-sub-command classes to a single class. Any mutation (WRITE /
        GIT_MUTATION / ADMIN_TRANSITION) wins over READ / EXECUTE so a benign
        leading command cannot mask a mutating follow-up. A command that hides
        its mutation behind an interpreter / substitution is NOT recursed into —
        it classifies as EXECUTE (Schicht B / threat level 3 — out of scope here
        by design, FK-55 §55.1a).
        """
        command = self._command_text(args)
        if not command:
            return OperationClass.EXECUTE
        sub_classes = [self._classify_subcommand(tokens) for tokens in _iter_subcommands(command)]
        if not sub_classes:
            return OperationClass.EXECUTE
        return _reduce_operation_classes(sub_classes)

    @staticmethod
    def _classify_subcommand(tokens: list[str]) -> OperationClass:
        """Classify a single (already-tokenized) visible sub-command.

        A redirect anywhere in the sub-command is a WRITE even when the leading
        verb is benign (``echo x > _temp/governance/freeze.json``). Otherwise the
        leading verb decides: an ``agentkit`` admin verb → admin_transition, a
        ``git`` subcommand → read vs git_mutation, a mutating shell verb →
        write, everything else → execute. Cheap leading-verb work only — no
        interpreter recursion, no obfuscation defeat (FK-55 §55.10.2 / §55.1a).
        """
        if not tokens:
            return OperationClass.EXECUTE
        # A redirect mutates regardless of the (possibly benign) leading verb —
        # e.g. ``echo x > _temp/governance/freeze.json``.
        if any(_is_redirect(tok) for tok in tokens):
            return OperationClass.WRITE
        first = _leading_verb(tokens)
        if first == "agentkit":
            return _classify_agentkit(tokens)
        if first == "git":
            return _classify_git(tokens)
        # FK-55 §55.10.2: a Bash file mutation (mutating verb) is a WRITE even
        # without a git subcommand — never collapsed to execute.
        if first in _GitVerbs.MUTATING_SHELL_VERBS:
            return OperationClass.WRITE
        return OperationClass.EXECUTE

    @staticmethod
    def _command_text(args: dict[str, object]) -> str:
        raw = args.get("command")
        if raw is None:
            raw = args.get("cmd")
        return raw.strip() if isinstance(raw, str) else ""

    @staticmethod
    def _web_tool_from(
        operation_name: str, args: dict[str, object] | None
    ) -> str | None:
        """Return the canonical web-tool name for this call, or ``None``.

        Resolves a web tool either from the operation name directly (``WebFetch``
        passed as the tool name) or — the harness path — from the preserved
        ``args["tool_name"]`` (WebFetch / WebSearch arrive as the ``unknown_tool``
        operation, AG3-036 FIX-1). Alias / casing tolerant via
        :func:`canonical_web_tool` (FIX-2).
        """
        direct = canonical_web_tool(operation_name)
        if direct is not None:
            return direct
        if args is None:
            return None
        raw = args.get("tool_name")
        return canonical_web_tool(raw) if isinstance(raw, str) else None


def _reduce_operation_classes(classes: list[OperationClass]) -> OperationClass:
    """Collapse the per-sub-command classes to the most consequential one.

    Mutation precedence (FK-55 §55.10.2): a chain is a mutation if ANY
    sub-command mutates. ``admin_transition`` ranks above generic mutations
    (it is the strongest signal), then ``git_mutation`` / ``write``, then
    ``read``, with ``execute`` as the inert default.
    """
    ordered = (
        OperationClass.ADMIN_TRANSITION,
        OperationClass.GIT_MUTATION,
        OperationClass.WRITE,
        OperationClass.READ,
    )
    for candidate in ordered:
        if candidate in classes:
            return candidate
    return OperationClass.EXECUTE


def _classify_agentkit(tokens: list[str]) -> OperationClass:
    subcommand = tokens[1].lower() if len(tokens) > 1 else ""
    if subcommand in _GitVerbs.ADMIN_SUBCOMMANDS:
        return OperationClass.ADMIN_TRANSITION
    return OperationClass.EXECUTE


def _classify_git(tokens: list[str]) -> OperationClass:
    if _is_git_read(tokens):
        return OperationClass.READ
    # Any non-read git subcommand (commit, push, checkout, ``branch -D``,
    # ``branch <new>``, worktree add/remove, ...) is a git mutation (FK-55 §55.5
    # git_mutation = "Commit, Push, Branch-/Worktree-Aenderung").
    return OperationClass.GIT_MUTATION


def _is_git_read(tokens: list[str]) -> bool:
    """Whether a ``git`` command is a pure read (no repository mutation).

    The unconditionally-read subcommands (:data:`_GitVerbs.READ_SUBCOMMANDS`) are
    always reads. ``git branch`` is read ONLY in its bare/listing form
    (:func:`_branch_is_read`); a creating/renaming/deleting/upstream-setting
    ``git branch`` is a mutation (FK-55 §55.5). Cheap flag inspection only — no
    shell semantics (FK-55 §55.10.2 / §55.1a).
    """
    subcommand = tokens[1].lower() if len(tokens) > 1 else ""
    if subcommand in _GitVerbs.READ_SUBCOMMANDS:
        return True
    if subcommand == "branch":
        return _branch_is_read(tokens[2:])
    return False


def _branch_is_read(args: list[str]) -> bool:
    """Whether ``git branch <args>`` is a bare/listing form (READ) vs a mutation.

    READ: no args (``git branch``), or only listing flags
    (:data:`_GitVerbs.BRANCH_READ_FLAGS`, plus their ``--flag=value`` forms and
    the value token consumed by a :data:`_GitVerbs.BRANCH_VALUE_FLAGS` flag).

    MUTATION: any flag that is not a listing flag (``-d``/``-D``/``--delete`` /
    ``-m``/``-M``/``--move`` / ``-c``/``-C``/``--copy`` / ``-u``/
    ``--set-upstream-to``/``--unset-upstream`` / ``-f``/``--force`` / …), OR any
    leftover positional token (a branch name to create). Cheap, fail-closed:
    an unrecognised flag is treated as a mutation.
    """
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            flag = token.split("=", 1)[0]
            if flag in _GitVerbs.BRANCH_READ_FLAGS:
                # A value-taking listing flag in its split form consumes the
                # following token (``--contains <commit>``); the ``--flag=value``
                # form is self-contained.
                if flag in _GitVerbs.BRANCH_VALUE_FLAGS and "=" not in token:
                    skip_next = True
                continue
            # Any other flag (-d/-D/-m/-M/-c/-C/-u/--set-upstream-to/-f/...) is a
            # branch mutation.
            return False
        # A positional token = a branch name to create / operate on → mutation.
        return False
    return True


def _tokenize(command: str) -> list[str]:
    """Cheap, no-semantics tokenization (FK-55 §55.10.2).

    Uses ``shlex`` in POSIX-tolerant mode; on a malformed quote it degrades to a
    plain whitespace split so a hostile command can never crash the hook. No
    fail-closed fabrication on a parse failure — a command that cannot be cheaply
    tokenized is treated by its plainly-visible tokens only (Schicht A; an
    obfuscated mutation is out of scope, FK-55 §55.1a).
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _split_top_level(command: str) -> list[str]:
    """Split a command string on top-level shell separators (FK-55 §55.10.2).

    Separators inside single/double quotes are preserved. This is a cheap
    character scan — no shell semantics, no globbing, no execution.

    Args:
        command: The raw command string.

    Returns:
        The list of top-level sub-command strings (empties dropped).
    """
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    length = len(command)
    while i < length:
        ch = command[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        two = command[i : i + 2]
        if two in ("&&", "||"):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        # ``&>`` / ``&>>`` is a combined redirect, NOT a background separator —
        # keep it attached so the redirect target is still recognised.
        if ch == "&" and command[i + 1 : i + 2] == ">":
            buf.append(ch)
            i += 1
            continue
        if ch in (";", "|", "&", "\n"):
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _iter_subcommands(command: str) -> list[list[str]]:
    """Yield the tokenized visible sub-commands of ``command`` (split only).

    Splits on top-level separators and tokenizes each piece. There is NO
    unwrapping of ``bash -c`` wrappers and NO command-substitution extraction —
    a mutation hidden inside an interpreter or substitution is threat level 3
    (Schicht B), out of scope for this layer (FK-55 §55.1a). Each returned token
    list represents one visible leaf sub-command.

    Args:
        command: The raw (possibly chained) command string.

    Returns:
        A list of tokenized visible sub-commands.
    """
    leaves: list[list[str]] = []
    for piece in _split_top_level(command):
        tokens = _tokenize(piece)
        if tokens:
            leaves.append(tokens)
    return leaves


def _leading_verb(tokens: list[str]) -> str:
    """Return the first non-env-assignment command verb, lowercased.

    A plainly-visible leading ``VAR=val`` assignment (``FOO=1 rm x``) is skipped
    so the real verb surfaces. This is the only env handling — there is no
    ``env``-prefix net or evasion stripping (that is Schicht B, FK-55 §55.1a).
    """
    for tok in tokens:
        # Skip leading ENV=val assignments (e.g. ``FOO=bar rm x``).
        if "=" in tok and not tok.startswith(("-", "/", ".")):
            head = tok.split("=", 1)[0]
            if head.isidentifier():
                continue
        return tok.lower()
    return ""


def _is_redirect(token: str) -> bool:
    """Whether a token is (or starts with) a file-writing redirect operator.

    Recognises plain (``>`` / ``>>``), fd-prefixed (``1>`` / ``2>>``) and
    combined (``&>``) forms — both standalone and with an attached target
    (``>out.txt``). Input redirects (``<``) are NOT mutations. Cheap prefix
    matching only (FK-55 §55.10.2); no ``:``-no-op trickery (Schicht B).
    """
    if not token or token.startswith("<"):
        return False
    rest = token
    # Strip a leading fd / combined-stream marker (``1`` / ``2`` / ``&``).
    if rest[0] in "&0123456789":
        rest = rest[1:]
    return rest.startswith(">")


def _redirect_target_of(token: str) -> str | None:
    """Return the attached redirect target of ``token``, or ``None``.

    ``>out`` → ``out``; ``1>>.git/x`` → ``.git/x``. A bare operator (``>`` /
    ``2>``) with no attached path returns ``None`` (the path is the following
    token, handled by the caller).
    """
    if not _is_redirect(token):
        return None
    stripped = token.lstrip("&0123456789>")
    return stripped or None


def bash_mutation_targets(command: str) -> list[str]:
    """Extract the *visible* file-mutation target paths from a Bash ``command``.

    FK-55 §55.10.2 requires Bash file mutations under ``.git/**``,
    ``_temp/governance/**`` and content-plane to be recognised directly — and a
    chained command must not be able to hide a mutation behind a benign leading
    command. The command is split on top-level separators and EVERY visible
    sub-command contributes its redirect targets, mutating-verb operands and
    git-internal targets.

    Only *visible* targets are surfaced. A target hidden inside a ``bash -c``
    wrapper or a command substitution is NOT extracted (threat level 3 / Schicht
    B — out of scope, FK-55 §55.1a). When a visible target IS surfaced on a
    mutating op but cannot be classified to a path class, the enforcement layer
    fails closed to BLOCK (FK-55 §55.10.2); this function does not fabricate a
    target to force that outcome.

    Args:
        command: The raw Bash command string (may be chained).

    Returns:
        The de-duplicated list of visible mutated target paths (may be empty).
    """
    targets: list[str] = []
    for tokens in _iter_subcommands(command):
        targets.extend(_leaf_targets(tokens))
    return _dedupe(targets)


def _leaf_targets(tokens: list[str]) -> list[str]:
    """Surface redirect / mutating-verb / git-internal targets of a leaf command."""
    targets: list[str] = []
    targets.extend(_redirect_targets(tokens))
    verb = _leading_verb(tokens)
    if verb in _GitVerbs.MUTATING_SHELL_VERBS:
        targets.extend(_operands(tokens, verb))
    if verb == "git":
        targets.extend(_git_targets(tokens))
    return targets


def _redirect_targets(tokens: list[str]) -> list[str]:
    """Surface the file target of every redirect token (attached or following).

    Handles attached (``>out`` / ``1>>.git/x``) and standalone (``> out`` where
    the path is the next token) redirect forms.
    """
    targets: list[str] = []
    for index, token in enumerate(tokens):
        if not _is_redirect(token):
            continue
        attached = _redirect_target_of(token)
        if attached is not None:
            targets.append(attached)
        elif index + 1 < len(tokens):
            targets.append(tokens[index + 1])
    return targets


def _operands(tokens: list[str], verb: str) -> list[str]:
    """Non-flag, non-redirect operands of a mutating verb (its target paths)."""
    operands: list[str] = []
    started = False
    for token in tokens:
        if not started:
            if token.lower() == verb:
                started = True
            continue
        if token.startswith("-"):
            continue
        if _is_redirect(token) or token.startswith(("<", "|", "&")):
            break
        operands.append(token)
    return operands


def _git_targets(tokens: list[str]) -> list[str]:
    """For a mutating git command, surface the repository-internal target.

    A git mutation always targets the repository internals (``.git/**``): the
    classifier resolves ``.git`` to ``git_internal`` (FK-55 §55.10.2 — git
    internals are never freely mutated). We surface ``.git`` as the target so a
    bare ``git commit`` / ``git push`` is recognised as a git_internal mutation
    even with no explicit path argument.
    """
    if len(tokens) < 2:
        return []
    if _is_git_read(tokens):
        return []
    return [".git"]


def _dedupe(targets: list[str]) -> list[str]:
    """De-duplicate target paths while preserving first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for target in targets:
        if target and target not in seen:
            seen.add(target)
            ordered.append(target)
    return ordered


__all__ = [
    "WEB_FETCH",
    "WEB_SEARCH",
    "OperationClass",
    "OperationClassifier",
    "bash_mutation_targets",
    "canonical_web_tool",
    "is_web_tool",
]
