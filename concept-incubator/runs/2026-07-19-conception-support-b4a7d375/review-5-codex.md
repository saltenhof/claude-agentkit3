Keine P0, aber mehrere P1 verhindern die Freigabe.

1. **P1 – Das Projection-Manifest ist weder schema- noch scope-vollständig.**  
   **Beleg:** Alle `assertion_source.digest` sind `null`, obwohl FK-78 dort keinen Nullwert erlaubt ([projection-manifest.json:5](/T:/codebase/claude-agentkit3/concept/_meta/projection-manifest.json:5), [FK-78 §78.12](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:579)). Von zehn neuen `authority_over`-Scopes besitzen nur drei einen Eintrag: Es fehlen unter anderem `incubator-artifact-schemas`, `promotion-closure`, `projection-manifest-format`, `concept-toolchain`, `concept-incubation-domain`, `council-roles` und `projection-status-semantics`. Auch CLAUDE, PROJECT_STRUCTURE, bounded-contexts, module-/policy-registry und concept-governance fehlen in den Pflichtprojektionsmengen.  
   Der Blocker zeigt nur auf eine Datei, nicht auf einen stabilen Abschnittsanker ([projection-manifest.json:19](/T:/codebase/claude-agentkit3/concept/_meta/projection-manifest.json:19)). Zudem ist `assertion-authority → projection-manifest.json` als Ganzdatei-Digest selbstreferenziell und damit nicht aktivierbar.  
   **Empfehlung:**

   - Genau ein Entry je `authority_over.scope` oder ein formal definiertes `covered_scope_ids[]`, dessen Vereinigungsmenge exakt den neuen Authority-Scopes entspricht.
   - Nicht-null Source-Digests vor Landung.
   - `lifecycle_source` mit Decision-ID, Pfad, Digest und Status ergänzen.
   - Alle tatsächlichen Pflichtprojektionen aufnehmen.
   - Blocker auf `README.md#sichtbare-blocker-...` verankern.
   - Selbstprojektion auf einen kanonischen Entry-Digest beziehen, der abgeleitete Felder und das eigene Digestfeld ausschließt – nicht auf den Digest der gesamten Manifestdatei.
   - `last_run_id` auf den Gründungslauf setzen; `last_promotion_manifest=null` kann wegen des dokumentierten Bootstrap-Sonderfalls bleiben.

2. **P1 – Der zweistufige Source-Freeze hat noch eine Digest- und Gate-Lücke.**  
   **Beleg:** Derived-Units dürfen neue Claims erzeugen, während `claims_inventory` bereits als Input-Digest eingefroren ist. `RUN.register_digests` enthält weder `source_units_final` noch einen Digest der Derived-Claims ([FK-78 §78.4](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:294), [§78.7](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:388)).  
   Außerdem verlangt §78.4 Coverage-Abschluss bereits vor Eintritt in PROMOTING, während §78.8 und die Formal-Invariante ihn korrekt erst vor dem Verlassen von PROMOTING verlangen ([FK-78:284](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:284), [FK-78:457](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:457)). Der Command `enter-promotion` übernimmt die falsche Eintrittsbedingung ([commands.md:101](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/commands.md:101)).  
   **Empfehlung:**

   - `claims_inventory_input`, `source_units_input`, `derived_claims` und `source_units_final` getrennt pinnen; alternativ eigenes `derived-claims.tsv`.
   - Vor PROMOTING: finaler Source-/Unit-/Claim-/Disposition-Stand, Findings-Routing und Locks.
   - Erst vor `PROMOTING → CLOSED`: normative Coverage über `baseline ∪ current`.
   - Coverage-Invariante aus `enter-promotion` entfernen und ausschließlich an `complete-promotion` binden.

3. **P1 – State-Machine und Szenarien sind formal nicht total beziehungsweise nicht ausführbar präzise.**  
   **Beleg:**

   - BLOCKED-Resume ist formal `BLOCKED → FRAMING`, während eine Compound Rule dynamische Rückkehr zu `blocked.since_state` behauptet ([state-machine.md:104](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/state-machine.md:104)). Das ist keine eindeutige Maschine.
   - Der Drift-Check vor SYNTHESIZING findet in CONVERGING statt, aber `CONVERGING → RECHECK` fehlt.
   - `gate-red-then-remediation` enthält weder Remediation noch Retry; nach `fail-promotion` folgt direkt `complete-promotion` ([scenarios.md:104](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/scenarios.md:104)).
   - Command-Effekte sind nicht an konkrete Transitionen gebunden. Der bestehende Compiler akzeptiert nach jedem Command irgendeinen transitiv erreichbaren Zustand; dadurch beweist ein grüner Trace nicht den beschriebenen Ablauf.
   - Lock-Release hat korrekte CAS-Mechanik, aber keinen Lifecycle: kein Release-Command/-Event und keine Regel für CLOSED, RECHECK, BLOCKED, PROMOTION_FAILED oder ABORTED.
   - Die geforderten Negativszenarien Renew-vs-Takeover, stale Release und Crash mit Takeover-Intent fehlen.

   **Empfehlung:**

   - Explizite `BLOCKED → <origin>`-Transitionen mit `since_state`-Guards.
   - `CONVERGING → RECHECK` ergänzen.
   - Commands mit `transition_id` beziehungsweise eindeutigem Result-State versehen; Szenarioschritte um `expected_status_after` erweitern.
   - `retry-promotion` mit Remediation-, Drift-, Lock- und Gate-Guards.
   - `release-scope-locks` plus Event und CAS-Invariante; Release-Timing je Ausgang aus PROMOTING normieren.
   - Negative CAS-/Intent-/stale-Writer-Szenarien ergänzen und den Compiler auf schrittgenaue Transitionen verschärfen.

4. **P1 – Single-Assertion und Formal-Meta-Contract sind noch verletzt.**  
   **Beleg:** Der Assertion-Vertrag ist Authority-Owner, enthält aber die Lifecycle-Vorrangregel nicht; seine Ableitung kann weiterhin `deprecated` oder `superseded` zu `active` überschreiben ([assertion-authority.md:82](/T:/codebase/claude-agentkit3/concept/_meta/assertion-authority.md:82)). FK-78 paraphrasiert diese Ableitung vollständig ([FK-78:591](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:591)). Ebenso dupliziert FK-78 vollständige Zustands-/Gate- und Closure-Listen, obwohl der Meta-Contract solche diskreten Aussagen dem Formal-Layer zuweist. DK-16 bleibt `prose-only`, enthält aber einen normativen Sieben-Schritte-Prozess und Promotion-Invarianten.  
   Die Formal-README erklärt ausgerechnet die deterministische Projection-Statusableitung für out of scope ([README.md:33](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/README.md:33)).  
   Zusätzlich sagt der Syntax-Contract weiterhin pauschal `concept/ = Markdown-only` ([syntax-contract.md:16](/T:/codebase/claude-agentkit3/concept/formal-spec/00_meta/syntax-contract.md:16)), und Meta-Contract §10 verbietet weiterhin alle abgeleiteten Artefakte unter `concept/` ([meta-contract.md:194](/T:/codebase/claude-agentkit3/concept/formal-spec/00_meta/meta-contract.md:194)).  
   **Empfehlung:**

   - Lifecycle-first ausschließlich in `assertion-authority.md` normieren.
   - Formal-Invarianten für ProjectionManifest/Lifecycle/Statusableitung ergänzen; FK-78 referenziert diese statt sie normativ zu kopieren.
   - FK-78 behält Schema-/CLI-/Checker-Mapping; Formal besitzt Zustände, Transitionen und maschinenprüfbare Invarianten.
   - DK-16 entweder auf Motivation/Rollenabgrenzung reduzieren oder auf `formal_refs` plus Anker umstellen.
   - Syntax- und Meta-Contract um die enge Ausnahme für schema-validierte, verifier-geprüfte `_meta`-Manifestmaterialisierungen ergänzen.

5. **P1 – Die Versionierung des Gründungslaufs verletzt die neue Klassifikationspolicy.**  
   **Beleg:** Der Lauf ist wegen seines Sonderstatus ohne Artifact-Register oder Declassification-Receipts versioniert ([Run-README:9](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/README.md:9)). Die eigene Policy sagt jedoch „unklassifiziert = sensitive, sensitive = local“. Insbesondere `review-1-codex.md` enthält umfangreiche Pfade und Tooltranskripte aus `P:\_private-img2img`.  
   **Empfehlung:** Vor Commit jedes migrierte Werkstattartefakt klassifizieren. Private Pfade/Transkripte sanitieren und per Bootstrap-Declassification-Receipt freigeben oder lokal/ignored halten; versioniert genügt die Findings-/Reviewfassung ohne Tooltranskript. Den Bootstrap-Ausnahmeentscheid im Decision Record ausdrücklich als einmalig und nicht präzedenzbildend dokumentieren.

6. **P1 – Der Wiederaufnahme-Cursor ist widersprüchlich und veraltet.**  
   **Beleg:** `STATE.md` meldet oben die Landung nach Review 4, bezeichnet später aber Design v3 als maßgeblich, Review 4 als laufend, Review 3 als offen und Task 4 als nächste Aktion ([STATE.md:3](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:3), [STATE.md:40](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:40), [STATE.md:57](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:57)). Das unterläuft genau die Resume-/Compaction-Garantie des Vorhabens.  
   **Empfehlung:** Cursor auf Review 5, aktuellen Normstand, offene Findings und nächste Toolchain-Aktion konsolidieren; historische Pläne aus dem aktiven Cursor entfernen oder klar als Historie markieren. Den LIGHT-Sonderstatus gegenüber den eigentlich erfüllten FULL_ATOM-Triggern als explizite Bootstrap-Ausnahme begründen.

7. **P1 – Der aktuelle Diff ist rot; die Decision-Matrix ist deshalb noch nicht promotionsfähig.**  
   Der read-only Lauf bestätigt:

   - Frontmatter: grün.
   - Formal-Compile: grün.
   - Decision-Record-Checker: grün.
   - Referenzintegrität: **3 ERROR** für Toolchain- und Skill-Pfade.

   Der vorhandene Baseline-Eintrag zeigt zudem auf FK-78 Zeile 638 statt 639 und begründet den Pfad fälschlich nur als Installer-Zielpfad, obwohl dort ausdrücklich die noch fehlende Bundle-Quelle genannt wird ([reference-integrity-baseline.yaml:268](/T:/codebase/claude-agentkit3/concept/_meta/reference-integrity-baseline.yaml:268)).  
   **Empfehlung:** Nicht committen, solange das Gate rot ist. Bevorzugt Toolchain-/Skill-Roots im selben atomaren Vorhaben anlegen; andernfalls alle drei Einträge mit korrekter Fundstelle, ehrlichem Zukunftsstatus, Owner und Auflösungs-Trigger baselinen. Die Betroffenheitsmatrix zusätzlich um Syntax-Contract, Meta-Contract §10, Formal-Compiler-Szenariosemantik und Bootstrap-Klassifikation ergänzen.

8. **P2 – Kleine Härtungen.**

   - `.gitignore` ergänzt Secrets und Locks, aber nicht `RUN.mutex`, Takeover-Intents und `artifact-register.local.tsv` ([.gitignore:76](/T:/codebase/claude-agentkit3/.gitignore:76)).
   - Für `N_A`-Coverage fehlt ein Pflichtgrund.
   - `artifact-register.input_refs` sollte typisiert werden (`source:<id>`/`artifact:<path>`) und einen azyklischen Provenienzgraphen bilden.
   - Semantik-Receipt-`findings[]` braucht einen eigenen Feldkatalog.
   - Die Tag-Datei ist jetzt tatsächlich vollständig sortiert; Registry- und Authority-Disjunktheitschecks sind grün.

## Gesamturteil

**Rework.**

Der architektonische Schnitt ist stabil und Review 4 wurde in den Hauptmechanismen gut umgesetzt. Vor Freigabe müssen aber Projection-Manifest, Source-Freeze-Digests, Formal-State-Machine/Szenarien, Authority-SSOT und Bootstrap-Klassifikation korrigiert sowie das Referenz-Gate grün werden. Es ist kein neuer BC- oder Skill-Grundsatzentwurf nötig, sondern eine gezielte normative Reparaturrunde.
