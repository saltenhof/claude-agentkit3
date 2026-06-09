OVERALL APPROVE

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: PASS
- AC-Schaerfe: PASS
- Klarheit: PASS
- Kontext-Sinnhaftigkeit: PASS

**Round-1 Errors**
- §70.11 #10 is now in source scope, in-scope enforcement, AC7, test list, and guardrails.
- AG3-091 owner overlap is resolved in both story files: AG3-100 owns `snapshot|next`, selector, and `next` reason entity; AG3-091 owns only `limits` plus other read-models.
- Wire fields are now snake_case and bound to `frontend-contracts.entity.execution_input_snapshot`.
- `PreStartGuard` / Tor-2 migration from `assess_readiness` to `evaluate_scheduling` is explicitly named as the real admission path.
- Remote gates are now in AC8/DoD/agent notes with strict Sonar metrics.

**Remaining Must-Fix ERRORs**
None.

Note: I did not run the remote gate script as a green implementation proof; this story is still `draft` / `review_pending`, and the required Jenkins/Sonar credentials are not loaded in the current environment. The story now correctly requires those gates before “fertig”.
