OVERALL CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: ERROR**

- FK-18 ist zu eng gescoped. Die Story beschraenkt Scope/AC auf §18.4/§18.6a, aber die stale Tabellennamen kommen in FK-18 mehrfach vor, u.a. §18.3.x, §18.5.x, §18.13, §18.14, §18.15, §18.16. Wenn nur §18.4/§18.6a geaendert werden, bleibt FK-18 intern widerspruechlich.
- `phase_state_projection` wird korrekt als `phase_states`/`phase_snapshots` erkannt, muss aber ebenfalls ueber alle FK-18-Vorkommen hinweg bereinigt werden, nicht nur punktuell.

**2. AC-Schaerfe: ERROR**

- [story.md](T:/codebase/claude-agentkit3/stories/AG3-102-concept-nachzug-producer-envelope-naming/story.md:5) sagt: “keine `concept/`-Aenderung in dieser Story.” Das widerspricht dem Story-Typ `concept/doc-only`, dem Scope “nur FK-Prosa” und der DoD “Konzept-Prosa-Aenderung”.
- AC6 ist zu unkonkret: Es sollte die Pflicht-Commands explizit nennen: `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py` und vor fertig auch `scripts/ci/check_remote_gates.ps1`.
- AC3 nennt FK-56 nur in der Klammer, nicht im eigentlichen Satzgegenstand. Das macht den FK-56-Teil als Akzeptanzkriterium unscharf.

**3. Klarheit: WARNING**

- Die Story ist grob nachvollziehbar, aber die zentrale Scope-Aussage “keine `concept/`-Aenderung” macht den Arbeitsauftrag missverstaendlich.
- FK-76/FK-56 werden in den Hinweisen gemeinsam als “optional/kosmetisch” behandelt. Das gilt fuer FK-76 laut §76.3-Hinweis, aber nicht fuer FK-56: `bc-cut-decisions.md` fuehrt `agentkit.story_context_manager.operating_mode_resolver` autoritativ.

**4. Kontext-Sinnhaftigkeit: ERROR**

- FK-42 ist falsch entschieden. [story.md](T:/codebase/claude-agentkit3/stories/AG3-102-concept-nachzug-producer-envelope-naming/story.md:43) erklaert `governance/ccag/` als code-autoritativ und will FK-42/PROJECT_STRUCTURE von `ccag_permission_runtime` auf `ccag` nachziehen. Das widerspricht `bc-cut-decisions.md` BC 4 und [PROJECT_STRUCTURE.md](T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md:127), die `ccag_permission_runtime` als Soll-Namespace fuehren. Das ist kein doc-only FK-Nachzug, sondern mindestens ein Owner-Konflikt bzw. Code-Folgeauftrag.
- FK-56 ist ebenfalls nicht sauber gespiegelt: AG3-097 hat bereits den Code-Namespace `operating_mode_resolver` als Scope/AC. AG3-102 sollte diesen Code-Fix nur referenzieren, nicht offenlassen, ob FK die heutige Code-Verortung uebernimmt.

**Must-Fix**

1. `keine concept/-Aenderung` ersetzen durch: keine `src/`-/`tests/`-/Schema-Code-Aenderung; FK-/Konzept-Prosa ist der eigentliche doc-only Scope.
2. FK-18-Scope auf alle betroffenen Vorkommen im FK-18-Dokument erweitern oder explizit AC “alle Vorkommen der alten Tabellennamen in FK-18 bereinigt” aufnehmen.
3. FK-42 nicht als “Code autoritativ” behandeln. Entweder BC-Cut/PROJECT_STRUCTURE als autoritativ setzen und Code-Folgeowner benennen, oder eine explizite PO-Entscheidung zur BC-Cut-Aenderung verlangen.
4. FK-56 als Code-Folgeauftrag an AG3-097 spiegeln; nicht als offene FK-oder-Code-Entscheidung stehen lassen.
5. AC6 mit den konkreten Gate-Commands schaerfen.
