OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit — FAIL**
- **ERROR:** Telemetrie/Event-Pflicht aus FK-32 fehlt in Scope/AC. FK-32 verlangt in `check_fidelity()` Schritt 5 ein Telemetrie-Event (`concept/technical-design/32_dokumententreue_conformance_service.md:123-135`) und beschreibt `llm_call`-Nachweise (`:518-534`); die formale Spec verlangt `assessment.started`, `level.evaluated`, `assessment.completed` (`concept/formal-spec/conformance/events.md:24-52`), FK-91 nennt die API-Events (`concept/technical-design/91_api_event_katalog.md:252-254`). Story AC 1-8 decken das nicht ab (`stories/AG3-063-conformance-service-fidelity/story.md:48-56`). **Fix:** Event-Emission und Contract-Tests mit exakten Payloads aufnehmen; falls `llm_call`, `doc_fidelity_check` und `conformance_*` bewusst zu mappen sind, diese Mapping-Entscheidung explizit machen.
- **ERROR:** Manifest-Index-Schreibauftrag ist konzeptuell unscharf bis widerspruechlich. Die Story verlangt `persistiert/liest` und `liest/schreibt _guardrails/manifest-index.json` (`story.md:37`, `:52`), FK-32 sagt aber: Index wird nicht automatisch generiert, ist kuratiert, Pflege obliegt Menschen (`concept/technical-design/32_dokumententreue_conformance_service.md:260-271`). **Fix:** ConformanceService als read/validate/resolve-Consumer schneiden; Schreibpfad nur als Installer/Admin-Indexer oder klar separater Owner, nicht waehrend Assessment.

**2) AC-Schaerfe — FAIL**
- **ERROR:** DoD/Pflichtbefehle sind unvollstaendig. Story nennt lokale pytest/mypy/ruff/Konzept-Gates (`story.md:56`), lokale Agent-Regel verlangt zusaetzlich Jenkins und Sonar inkl. `scripts/ci/check_remote_gates.ps1` (`AGENTS.md:31-45`) und verbietet roten Gate-Zustand (`AGENTS.md:52-53`). **Fix:** AC8 um Remote-Gate-Script und strikte Sonar-Metriken erweitern.
- **ERROR:** ACs pruefen nicht, dass bestehende Exploration-Doc-Fidelity wirklich in `check_fidelity(design)` aufgeht. Es gibt bereits `DocFidelityChecker.check()` fuer FK-32 §32.6 (`src/agentkit/exploration/review/doc_fidelity.py:1-16`, `:84-119`) und er ist gewired (`src/agentkit/bootstrap/composition_root.py:217-245`). AC3/AC7 nennen nur Layer-2/Closure bzw. `verify_system/doc_fidelity` (`story.md:51`, `:55`). **Fix:** AC ergaenzen: `ExplorationReview` darf keinen parallelen Design-Fidelity-Einstieg behalten; vorhandener Checker delegiert an `ConformanceService` oder wird abgeloest.

**3) Klarheit — WEAK**
- **WARNING:** Ist-Zustand ist faktisch falsch formuliert: „Ebene 1 und Ebene 2 fehlen komplett“ (`story.md:22`) widerspricht vorhandener Ebene-2-Exploration-Pruefung (`src/agentkit/exploration/review/doc_fidelity.py:1-16`). Der Gap-Befund sagt enger: Ebene 1/2 fehlen „als gemeinsamer ConformanceService“ (`var/concept-gap-analysis/gap-fk-26-35.md:289-293`). **Fix:** Storytext auf „nicht im gemeinsamen `ConformanceService` konsolidiert“ aendern.
- **WARNING:** Ebene 4 wird als „gebaut und produktiv“ beschrieben (`story.md:26`, auch Hinweis `:70`), real ist der produktive Port ein verpflichtender Warning-Stub ohne Callable (`src/agentkit/closure/runtime_ports.py:197-218`; Composition Root `:2165-2175`). **Fix:** Als vorhandenen Closure-Seam/Warning-Port beschreiben; Produktiv-Evaluator klar AG3-067 zuordnen oder Scope neu entscheiden.
- **NIT:** Anchor-Genauigkeit: `verify_system/doc_fidelity/__init__.py` ist nicht „1 Zeile“, sondern 0 Bytes/0 Zeilen; die Story-Aussage steht in `story.md:19`. **Fix:** „leere Datei/0 Zeilen“ schreiben. Das Grep „FidelityResult → 0 Treffer“ ist repo-weit ebenfalls nicht wahr, da `DocFidelityResult` existiert (`src/agentkit/exploration/review/doc_fidelity.py:41`); Suchscope praezisieren.

**4) Kontext-Sinnhaftigkeit — FAIL**
- **ERROR:** Aktueller Scope wuerde sehr wahrscheinlich eine zweite Wahrheit fuer Design-Fidelity erzeugen: Story fordert „Ebenen 1 + 2 neu implementieren“ (`story.md:35`), waehrend `ExplorationReview` Stage 1 bereits Doc-Fidelity ausfuehrt und bei FAIL stoppt (`src/agentkit/exploration/review/review.py:136-147`). **Fix:** Nicht neu parallel bauen; vorhandene Exploration-Mechanik hinter `ConformanceService.check_fidelity(level=design)` konsolidieren und alten Einstieg eindeutig stilllegen/delegieren.
- **WARNING:** `status.yaml` ist formal plausibel (`status.yaml:1-10`), aber `unblocks: []` bleibt fraglich, weil AG3-063 laut Index Teil der Verify/Closure-Welle ist und AG3-064/067 fachlich daran angrenzen (`var/concept-gap-analysis/_STORY_INDEX.md:54-58`). **Fix:** Abhaengigkeits-/Unblock-Beziehung zu AG3-064/067 zumindest explizit begruenden.

**Must-Fix**
1. Ist-Zustand fuer Ebene 2 und Ebene 4 korrigieren.
2. Scope/AC so umschneiden, dass bestehende Exploration- und Closure-Pfade delegieren/konsolidieren statt parallel ersetzt werden.
3. Telemetrie/formale Conformance-Events mit Tests aufnehmen.
4. Manifest-Index-Owner klaeren: kuratierter Index, kein unkontrollierter Runtime-Schreibpfad.
5. AC8 um Jenkins/Sonar Remote-Gates erweitern.
6. Anchor-/Grep-Aussagen praezisieren.
