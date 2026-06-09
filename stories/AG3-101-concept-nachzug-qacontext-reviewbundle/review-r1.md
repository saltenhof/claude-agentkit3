OVERALL CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: ERROR**

Finding: AG3-101 deckt nicht alle stale `VerifyContext`-Prosa im eigenen FK-37-Row-Scope ab. Die Story fokussiert [story.md](T:/codebase/claude-agentkit3/stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md:32) auf §37.1.0/§37.1.2, aber FK-37 §37.1.4 enthält ebenfalls stale `VerifyContext`-Text/Pseudocode, z. B. [37_verify_context_und_qa_bundle.md](T:/codebase/claude-agentkit3/concept/technical-design/37_verify_context_und_qa_bundle.md:209). Der Index scoped AG3-101 auf FK-37 §37.1 insgesamt, nicht nur 37.1.0/37.1.2.

Fix: Scope und AC um alle stale `VerifyContext`-Enum-Erwähnungen innerhalb FK-37 §37.1 erweitern, insbesondere §37.1.4 Entscheidungsregel/Pseudocode.

**2. AC-Schaerfe: ERROR**

Finding: AC2 ist zeitlich widersprüchlich zur Abhängigkeit. AG3-101 `depends_on: AG3-067` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-101-concept-nachzug-qacontext-reviewbundle/status.yaml:8)); AG3-067 `unblocks: AG3-101` und will `ReviewBundle` um `arch_references`/`evidence_manifest` erweitern ([AG3-067 story.md](T:/codebase/claude-agentkit3/stories/AG3-067-context-sufficiency-packing-feedback-fidelity/story.md:32), [line 49](T:/codebase/claude-agentkit3/stories/AG3-067-context-sufficiency-packing-feedback-fidelity/story.md:49)). AG3-101 dagegen fixiert das aktuelle Acht-Feld-`ReviewBundle` und markiert fehlende `arch_references`/`evidence_manifest` als AG3-067-Code-Bedarf ([story.md](T:/codebase/claude-agentkit3/stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md:45)). Nach AG3-067 ist diese AC voraussichtlich stale.

Fix: Entweder Dependency auf AG3-067 entfernen und AG3-101 vor AG3-067 als Ist-Code-Nachzug ausführen, oder besser: Dependency behalten und AC2 so formulieren, dass nach AG3-067 erneut gegen den dann realen `ReviewBundle`-Code gegrounded wird.

**3. Klarheit: ERROR**

Finding: Die Story trennt den alten Enum-Namen `VerifyContext` nicht klar vom weiterhin realen öffentlichen Contract-Typ `VerifyContextBundle`. Realer Code: `run_qa_subflow(ctx: VerifyContextBundle, ..., qa_context: QaContext, ...)` in [system.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/system.py:478), Contract-Klasse in [contract.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/contract.py:136). AC1 fordert aber “kein verbleibender `VerifyContext`-Treffer” in genannten Abschnitten ([story.md](T:/codebase/claude-agentkit3/stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md:44)) und Guardrail-Prosa sagt “keine zweite Vokabular-Wahrheit (`VerifyContext` neben `QaContext`)” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md:54)). Das ist substring-gefährlich und kann FK-Prosa gegen die Code-Realität verfälschen.

Fix: Explizit: Nur das exakte alte Enum/Discriminator-Symbol `VerifyContext` wird ersetzt. `VerifyContextBundle` bleibt als realer Contract-Typ gültig und muss, falls FK-37 den `ctx`-Parameter beschreibt, bewusst erhalten oder korrekt eingeordnet werden.

**4. Kontext-Sinnhaftigkeit: ERROR**

Finding: Für doc-only ist die Story noch nicht robust gegen Code-vs-FK-Drift. Sie sagt zwar “Code autoritativ”, aber der `ReviewBundle`-Teil ist an die aktuelle Vor-AG3-067-Codezeile gebunden ([bundle.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/llm_evaluator/bundle.py:44)) und gleichzeitig durch AG3-067 blockiert. Damit kann die spätere FK-Prosa entweder eine veraltete Acht-Feld-Realität dokumentieren oder Code-Bedarf als offen markieren, der durch die Voraussetzung bereits erledigt sein soll.

Fix: AG3-101 muss eine Re-Grounding-Pflicht nach AG3-067 enthalten: “vor FK-Änderung realen `ReviewBundle`/`build_review_bundle` erneut prüfen; FK folgt exakt diesem Feldset; offene Felder nur dann an AG3-067/Follow-up spiegeln, wenn nach AG3-067 weiterhin fehlend.”

**Must-Fix List**

1. FK-37 §37.1.4 stale `VerifyContext`-Stellen in Scope/AC aufnehmen.
2. `VerifyContext` exakt vom gültigen `VerifyContextBundle` abgrenzen; keine pauschale substring-Löschung.
3. AG3-067-Abhängigkeit mit AC2 auflösen: nach AG3-067 re-grounden oder Dependency entfernen.
