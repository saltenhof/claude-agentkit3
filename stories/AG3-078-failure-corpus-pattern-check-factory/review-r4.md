OVERALL APPROVE

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: PASS. R3 ERRORs are resolved: CP2/CP3/CP4 are no longer falsely routed to AG3-081/AG3-079; `fc_check_outcomes` remains removed; reset semantics now match FK-41/FK-69.
- AC-Schaerfe: PASS. AC5/AC8 are explicitly fail-closed against missing CP fields and testable via seeded data; AC6 now clearly separates read/write wiring from reset deletion.
- Klarheit/Eindeutigkeit: PASS. `status.yaml` removes the false AG3-081 dependency and labels CP1-CP4 as prerequisites/action items, not delivered scope.
- Kontext-Sinnhaftigkeit: PASS. Real code matches the story’s current-state claims for `StoryMetricsRecord`, `ProjectionFilter`, `SonarQubeConfig`, and `ProjectionAccessor` ownership.

**Remaining/New Must-Fix ERRORs**
- None.

Non-blocking note: AG3-078 still says FK-03 lacks `accept_frequency_fc_threshold`, but current FK-03 already lists it with default `0.25`. This does not block approval because the code model still lacks the field and CP1 is honestly routed as a config-owner extension, but the owner story should use the existing FK-03 default when extended.
