OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: ERROR**

- AG3-104 erfasst FK-07/FK-76/FK-73/FK-92 grob, aber die BC-Registry ist nicht vollstaendig scharf: [PROJECT_STRUCTURE.md](T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md:89) behauptet weiter “16” BCs, waehrend [bounded-contexts.yaml](T:/codebase/claude-agentkit3/concept/technical-design/_meta/bounded-contexts.yaml:245) `harness-integration` bereits kennt. Die Story muss verlangen, dass Zaehlung, Baum und Verantwortungstabelle konsistent nachgezogen werden.
- ARCH-55 ist unvollstaendig gespiegelt. Die Story nennt nur [pattern.py](T:/codebase/claude-agentkit3/src/agentkit/failure_corpus/pattern.py:50), aber real existieren weitere deutsche Wire-/Schema-Werte, z. B. [check_proposal.py](T:/codebase/claude-agentkit3/src/agentkit/failure_corpus/check_proposal.py:56) und DB-Constraints in [sqlite_store.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/sqlite_store.py:800). Entweder alle Failure-Corpus-Sprachfixes an AG3-078 spiegeln oder Ausnahmen explizit begruenden.
- FK-76-Port-Surface wird in der Story als “optional” behandelt, obwohl FK-76 die oeffentliche Surface nennt ([76_agent_harness_integration.md](T:/codebase/claude-agentkit3/concept/technical-design/76_agent_harness_integration.md:306)). Das braucht einen benannten Code-Owner, keinen optionalen Sammelhinweis.

**AC-Schaerfe: ERROR**

- Die Spiegelung an AG3-078/AG3-070/AG3-068 ist nicht verifizierbar formuliert: “gespiegelt (Vermerk)” sagt nicht, ob `story.md`, `status.yaml`, Story-Index oder ein anderes Backlog-Artefakt geaendert werden muss.
- AC 5 behauptet “kein offener Owner-Konflikt”, waehrend WorktreeManager und harness package/Port-Surface nur “PO/Backlog” bzw. “Code-Folge-Story” haben ([story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:34), [story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:35)).
- Gate-AC ist zu unkonkret. Fuer doc-only Konzeptarbeit sollten die konkreten Checks genannt werden: `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`, plus `scripts/ci/check_remote_gates.ps1` vor “fertig” gemaess lokalen Gates.

**Klarheit: ERROR**

- Harte Scope-Kollision: Zeile 5 sagt “keine `concept/`-/PROJECT_STRUCTURE-Aenderung”, aber Scope/AC verlangen genau FK-/PROJECT_STRUCTURE-Prosa-Aenderungen ([story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:5), [story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:32), [story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:47)).
- Der Sub-Agent-Hinweis verschärft das: “NICHT ... PROJECT_STRUCTURE.md/FK-Dateien anfassen” blockiert die eigene DoD ([story.md](T:/codebase/claude-agentkit3/stories/AG3-104-concept-nachzug-structure-bc-registry-arch55/story.md:67)).

**Kontext-Sinnhaftigkeit: ERROR**

- WorktreeManager ist in [bc-cut-decisions.md](T:/codebase/claude-agentkit3/concept/_meta/bc-cut-decisions.md:275) bereits als shared component mit Owner `StoryContextManager`/story-lifecycle modelliert. Die Story sagt dennoch “kein bestehender Code-Owner im Index” und laesst PO/Backlog stehen. Das ist kein owner-per-value.
- Die Story richtet PROJECT_STRUCTURE zwar gegen Code-Realitaet aus, laesst aber offen, ob `harness_integration` als neuer BC gezählt, als bestehender Registry-Eintrag synchronisiert oder nur im PROJECT_STRUCTURE-Baum nachgetragen wird. Das ist fuer eine BC-Registry-Story zu diffus.
- Positiv abgrenzbar ist: keine stille Code-Implementierung wird gefordert. Aber die offenen Code-Bedarfe sind nicht sauber genug owner- und artefaktgenau gespiegelt.

**Must-Fix**

1. Scope-Kollision entfernen: doc-only muss `concept/` und `PROJECT_STRUCTURE.md`-Prosa aendern duerfen; Code/Test bleiben verboten.
2. Konkrete Zielartefakte fuer jede Spiegelung benennen: wo wird AG3-078/AG3-070/AG3-068 bzw. PO-Eskalation aktualisiert?
3. Owner pro Wert nachschaerfen: WorktreeManager, `harness_integration` package und FK-76-Port-Surface brauchen benannte Owner oder explizite neue Backlog-Story.
4. ARCH-55-Befund auf alle realen failure-corpus enum/schema Werte erweitern oder begruendet begrenzen.
5. AC 7 mit konkreten Checks und Diff-Regel ersetzen: Konzept-Frontmatter, Formal-Spec-Compile, Remote-Gates, `git diff -- src tests` leer.
