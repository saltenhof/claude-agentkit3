# Execute User Story ARE

Execute an approved user story in an ARE-enabled project.

**Invocation:** `/execute-userstory <STORY-ID>`

**Profile:** ARE

## Contract

Use the same suffix-free harness identity as the CORE variant:
`skill_name=execute-userstory`. The profile-specific bundle identity is
`bundle_id=execute-userstory-are`.

## Orchestration

Follow the FK-43 §43.3.3 eight-step execution sequence:

1. Liest freigegebene Story aus dem AK3-Story-Backend.
2. Ruft `POST /phases/setup/start` auf.
3. Liest Phase-State -> spawnt Worker (oder Exploration-Worker).
4. Wartet auf Worker-Ende.
5. Ruft `POST /phases/implementation/start` auf — der QA-Subflow laeuft Subflow-intern in der Implementation-Phase und ruft die Capability `VerifySystem` (FK-27).
6. Liest Phase-State -> bei `qa_cycle_status: awaiting_remediation`: spawnt Remediation-Worker und ruft `POST /phases/implementation/start` erneut auf (Subflow-Loop, kein Phasenwechsel).
7. Bei `qa_cycle_status: pass` (Implementation COMPLETED): ruft `POST /phases/closure/start` auf.
8. Bei Eskalation: stoppt und informiert Mensch.

There is no standalone `verify` top-phase. QA is the Implementation-phase
subflow loop. The ARE profile additionally preserves requirement traceability
and stops when ARE linkage or requirement ownership is unclear.
