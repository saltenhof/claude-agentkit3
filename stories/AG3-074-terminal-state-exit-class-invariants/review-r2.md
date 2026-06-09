OVERALL APPROVE

**Konzept-Vollstaendigkeit: PASS**  
Round-1 ERROR resolved. AG3-074 is now limited to `TerminalState`, `ExitClass`, `derive_terminal_state(...)`, and `validate_exit_class_constraints(...)`. `cancel_story` is explicitly preserved, and #4 is correctly scoped to normal Closure only.

**AC-Schaerfe: PASS**  
AC5 is now testable against `ClosurePhaseHandler -> _transition_story_done() -> complete_story()`, with a separate regression check that administrative `cancel_story` from `Backlog`/`Approved` still produces `Cancelled`. AC6 was reduced to a concrete importable function; dashboard/KPI is only a future consumer.

**Klarheit: PASS**  
The signatures are fixed: `derive_terminal_state(status: StoryStatus) -> TerminalState` and `validate_exit_class_constraints(terminal_state, exit_class | None) -> None`. Reset interim states are explicitly not current `StoryStatus` members and are handled future-compatibly via `else -> Open`.

**Kontext-Sinnhaftigkeit: PASS**  
Producer/orchestration ownership is now routed out: AG3-071 for reset statuses, AG3-072 for `scope_split`, AG3-073 for `viability_handoff` and administrative exit cancellation. AG3-074 remains the common axis/constraint owner.

**Remaining Must-Fix ERRORs:** none.

Read-only evidence checked against FK-59 and real code: `StoryStatus` has only `Backlog|Approved|In Progress|Done|Cancelled`; `complete_story()` writes only `Done`; `cancel_story()` still writes `Cancelled` for allowed frontend transitions; generic `In Progress -> Cancelled` remains blocked; no current `exit_class`/`TerminalState` implementation exists under `src`.
