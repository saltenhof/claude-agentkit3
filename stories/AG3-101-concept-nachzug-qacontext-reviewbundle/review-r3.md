OVERALL CHANGES-REQUESTED

Per-Dimension: Konzept ERROR, AC-Schaerfe ERROR, Klarheit PASS, Kontext ERROR.
R2-ERRORs substantiell geloest (37.1.0:137-138 + 37.1.5:282-283 in Scope; AC7 Routing-Treue IMPLEMENTATION voll vs EXPLORATION reduziert).

Remaining Must-Fix:
1. story.md:90 DoD sagt "AK 1-6", aber AC7 existiert (story.md:88) -> muss "AK 1-7".
2. FK-37 37.1 enthaelt noch stale "Exploration nicht via QA-Subflow / Implementation-only-Trigger"-Prosa (37_...:140/153/173). Story fuehrt EXPLORATION_INITIAL/REMEDIATION-Routing ein, scopt den Invarianten-Rewrite aber nur fuer 37.1.4/37.1.5 -> wuerde FK-37 intern widerspruechlich lassen ggue. bc-cut-decisions.md:78 + routing.py:71. Scope/AC muss 37.1.0-37.1.2 mit angleichen ODER explizit begruenden warum gueltig.
(job-e1cfbccb)
