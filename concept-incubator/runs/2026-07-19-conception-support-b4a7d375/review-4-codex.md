## R3-Status

| Punkt | Urteil |
|---|---|
| R3-1 Verlustfreiheit | teilweise geschlossen |
| R3-2 Selbsttragend | Design ja, Schema nein |
| R3-3 Status/Authority | teilweise geschlossen |
| R3-4 Reverse Trace/Receipts | weitgehend geschlossen |
| R3-5 Lock/Lease | teilweise geschlossen |
| R3-6 Klassifikation | weitgehend geschlossen |
| R3-7 CLI/Feldkataloge | teilweise geschlossen |
| R3-8 IDs/Tombstones | geschlossen |

## Findings

1. **P1 – Quellen-Freeze und Claim-Closure sind zeitlich widersprüchlich.**  
   Das Design registriert nach der letzten Runde auch Synthesen, Dissent-Map und PO-Entscheidungen als Quellen, verlangt das Claim-Inventar aber vor der Synthese ([DESIGN.md:201](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:201), [DESIGN.md:212](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:212)). Gleichzeitig wird nur ein Source-/Unit-Digest gepinnt.  
   **Auflage für FK-78/Formal-Spec:**

   - `source_phase=input|derived`.
   - Vor `SYNTHESIZING`: Freeze von Briefing, allen Proposal-Runden und bisherigen PO-Inputs als `input_source_set`; eigener Register-/Unit-/Inventar-Digest.
   - Nach Synthese/Entscheidung: Synthese, Dissent und PO-Entscheidungen als `derived_source_set` ergänzen.
   - Jede materielle Derived-Unit referenziert entweder upstream Claims oder erzeugt einen neuen Claim, der vor PROMOTING disponiert wird.
   - Zweiter `final_source_set_digest` vor Promotion-Closure; der erste Freeze darf nicht überschrieben werden.

   Zusätzlich braucht `normative-coverage.tsv` `current_sha256`, `change_kind=unchanged|modified|added|removed` und Coverage über `baseline ∪ current`, nicht nur Baseline-Dateien ([schemas-draft.md:149](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:149)).

2. **P1 – Die Schemas sind noch nicht vollständig selbsttragend beziehungsweise implementierbar.**  
   `ROUND.json` und `coverage-plan.json` verweisen weiterhin auf v1 ([schemas-draft.md:123](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:123), [schemas-draft.md:157](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:157)). Für W2/W3 fehlen Request-Pack- und Receipt-Schemas komplett.  
   **Auflage:**

   - ROUND- und Coverage-Plan-Feldkatalog vollständig inline aufnehmen.
   - Semantik-Request-Schema: Gate, Scope, Base-Revision, Template-ID/Digest, geordnete Chunks mit Pfad/Locator/Digest, Request-Digest.
   - Semantik-Receipt: Request-Digest, Modell, Principal/Session, Befunde, Status, Zeit und vollständige Chunk-Digest-Rückbindung.
   - `required_registry_edges` und `required_test_oracles` als strukturierte Objekte statt unbestimmter Strings.
   - `source_id`-Grammatik ergänzen.
   - Unit-Partition exakt normieren: nicht überlappende Heading-Blöcke, Preamble-Regel, ATX/Setext, Fences, doppelte Überschriften und Absatz-Fallback.
   - `blocked`/`recheck` explizit als `object|null` typisieren.
   - `findings.tsv` ergänzen; `PASS_WITH_GAPS`/`FAIL` müssen Finding-Refs besitzen, und unresolved Findings müssen Promotion blockieren.

3. **P1 – Projection-Manifest kollidiert noch mit Status- und Repo-Metaverträgen.**  
   Die Ableitung „alle equivalent → active, sonst blocked“ würde auch `draft`, `deprecated` und `superseded` überschreiben ([schemas-draft.md:270](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:270)). Zudem verlangt v4 JSON unter `concept/`, während PROJECT_STRUCTURE weiterhin „concept = nur Markdown“ sagt ([PROJECT_STRUCTURE.md:36](/T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md:36)). Der Meta-Contract erklärt abgeleitete Artefakte generell für nicht autoritativ und verweist sie nach `var/` ([meta-contract.md:194](/T:/codebase/claude-agentkit3/concept/formal-spec/00_meta/meta-contract.md:194)).  
   **Auflage:**

   - Lifecycle zuerst aus Decision/Supersession bestimmen: `draft|deprecated|superseded` bleiben Lifecycle-Zustände; nur eine aktuelle akzeptierte Assertion wird zu `active|blocked_projection` abgeleitet.
   - Manifest um `blockers[]` und `last_promotion_manifest {path,digest}` ergänzen.
   - Festlegen, dass deklarierte Pflichtprojektionen normative Eingaben sind; abgeleitete Statusfelder sind verifier-geprüfte Materialisierungen, keine unabhängige Autorität.
   - PROJECT_STRUCTURE und `syntax-contract.md` um eine enge Ausnahme für schema-validierte `_meta/*.json|yaml` ergänzen – oder das Manifest als Structured Markdown führen.

4. **P1 – Fencing verhindert stale Writes noch nicht vollständig.**  
   Vorprüfung plus atomarer Rename ist kein atomarer CAS: Zwei Writer können dieselbe Revision lesen und nacheinander ersetzen. Außerdem sind Lock-Releases nicht explizit an erwarteten Token/OID gebunden ([schemas-draft.md:77](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:77), [schemas-draft.md:98](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:98)).  
   **Auflage:**

   - RUN-Mutation unter separatem O_EXCL-Mutationsmutex; darin Lease, Token und Revision erneut lesen, erst dann Replace.
   - Filesystem-Release nur nach Owner-/Token-Recheck unter Intent/Mutex.
   - Git-Release ausschließlich CAS gegen erwartete Ref-OID; stale Owner darf keinen übernommenen Lock löschen.
   - Formal-Szenarien für Renew-vs-Takeover, stale Write, stale Release, Crash mit Intent und Drift unmittelbar vor Landung.

5. **P1 – Der aktuelle normative Zwischenstand ist noch nicht gatefähig.**  
   Der angekündigte Manifest-Verweis ist bereits vorhanden ([assertion-authority.md:107](/T:/codebase/claude-agentkit3/concept/_meta/assertion-authority.md:107)); es fehlt das referenzierte `projection-manifest.json` selbst. Außerdem referenzieren DK-16 und die Domain-Registry das noch nicht vorhandene FK-78. Der read-only Frontmatter-Check meldet deshalb drei Fehler. Der Formal-Compiler ist dagegen grün.  
   **Auflage für den atomaren Norm-Diff:**

   - FK-78, technischer Indexeintrag, Formal-Kontext, initiales Projection-Manifest und `concept-governance` gemeinsam ergänzen.
   - Decision Record samt Impact-Sweep/Betroffenheitsmatrix in denselben Diff.
   - DK-16 darf `prose-only` bleiben, wenn alle diskreten Mechaniken ausschließlich FK-78/Formal gehören; andernfalls DK-16 auf `formal_refs` plus Anker umstellen.
   - Vor Abschluss W1/W4 sowie W2/W3 für die betroffenen Scopes ausführen.

6. **P2 – Restliche Schema-/Registry-Härtung.**  

   - Assertion-Authority fordert anderen Principal **und andere Session**, das Schema erzwingt nur Principal-Ungleichheit ([assertion-authority.md:121](/T:/codebase/claude-agentkit3/concept/_meta/assertion-authority.md:121), [schemas-draft.md:238](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/schemas-draft.md:238)). Beide Ungleichheiten angleichen.
   - `source-register.tsv` braucht `author_principal_id`, sonst ist die Source-Review-Unabhängigkeit nicht prüfbar.
   - Declassification muss exakt festlegen, dass ein digestgebundenes Receipt die sonstige Max-Klassen-Regel für genau das Output-Artefakt überschreibt.
   - Sensitive Pfade/Digests im Artifact-Register dürfen nicht über ein versioniertes Register lecken: lokales Overlay oder sanitisiertes öffentliches Register normieren.
   - BC-Ownership um SourceUnit, Coverage-Register, ArtifactRegister, DeclassificationReceipt, ProjectionManifest und Finding ergänzen.
   - Die neuen Tags wurden erneut am unsortierten Dateiende ergänzt; der normative Alphabetisierungsvertrag bleibt verletzt.

## Gesamturteil

**Freigegeben mit Auflagen.**

Der BC-, Rollen-, Skill- und Promotion-Grundschnitt ist tragfähig; kein weiterer Architektur-Designzyklus ist nötig. Die obigen Auflagen müssen aber beim Schreiben von FK-78 und der Formal-Spec ausdrücklich normiert werden, bevor Checker-Code entsteht. Besonders bindend sind der zweistufige Source-Freeze, die Projection-Lifecycle-Regel und echtes CAS/Fencing.

Keine Dateien wurden verändert. Read-only geprüft: Formal-Compiler grün; Frontmatter aktuell erwartungsgemäß rot wegen des noch fehlenden FK-78.
