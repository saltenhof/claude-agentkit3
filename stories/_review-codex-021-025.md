# Codex-Review AG3-021 bis AG3-025

> Independent review, Codex, Stand 2026-05-16.
> Geprueft gegen CLAUDE.md, README.md, _priorisierungsempfehlung.md, alle
> zitierten Konzept-Anker und THEME-relevante GAP-Markdowns.

## Gesamtfazit

Die fuenf Stories sind im Schnitt und in der Reihenfolge fachlich plausibel:
AG3-021 ist das richtige Fundament, AG3-022/023 trennen Artefakt-Modell und
Migration sinnvoll, AG3-024/025 trennen PhaseEnvelope und AttemptRecord sauber.
Umsetzungsreif ohne Konzept-Lektuere sind sie aber nicht alle: AG3-021, AG3-023
und AG3-025 lassen an entscheidenden Stellen noch Wertelisten, Migration-
Defaults oder SQL-Details offen; AG3-022 hat eine unklare Validator-Matrix.
Kritisch lueckenhaft ist keine Story, aber vier Stories brauchen vor Start
konkrete Nachschaerfung, damit Worker nicht aus Konzepten raten muessen.

## Pro Story

### AG3-021: Typisierte Kern-Enums

**Gesamturteil:** Nachbesserung erforderlich

**Mapping-Vollstaendigkeit:** Die Story deckt die relevanten THEME-002-Befunde
breit ab: verify-system C1/C2, exploration-and-design A6/B2/C2,
story-lifecycle C1/C2, story-closure A9, execution-planning C1,
implementation-phase A4/C2 sowie die Pipeline-Framework-Enum-Vorarbeiten fuer
PauseReason, AttemptOutcome und FailureCause. Es fehlt kein offensichtlicher
GAP-Befund unter dem Story-Schirm. Schwach ist aber die Anker-Operationalisierung:
die Story nennt viele FK-/DK-Kuerzel, aber nicht die konkreten Konzept-Dateipfade;
FK-27 §27.4.2 fuer Wire-Casing taucht als notwendiger Hinweis auf, ist aber nicht
als zentraler Umsetzungsanker in der Pflichtliste ausgearbeitet.

**Beschreibungs-Adaequanz:** Der Kontext ist stark: die Story erklaert, warum
alle nachfolgenden BCs ein gemeinsames Core-Type-Fundament brauchen. Die
Dateitabellen sind realistisch und erfassen die heutige Topologie nach dem
THEME-001-Schnitt. Out-of-Scope ist nicht pro forma, sondern grenzt Stage-
Registry, AttemptRecord, PhaseEnvelope und Execution-Planning-Logik klar ab.

**Umsetzungsreife:** Nicht vollstaendig. Die Story ist als Migrationsplan gut,
aber ein Worker kann die Enum-Wire-Werte nicht vollstaendig ohne Konzept-Lesen
implementieren. Schwache AKs:

1. AK 2 ist nicht in sich geschlossen, weil die exakten Wire-Strings und das
   Casing an FK-27 §27.4.2 ausgelagert sind.
2. AK 6 fordert FailureCause, nennt aber die 15 Werte nicht.
3. AK 14 fordert einen Contract-Test gegen eine Pflichtliste, legt diese Liste
   aber nicht vollstaendig in der Story ab.
4. Die optionale Formulierung zu `PauseReason.from_yield_status` laesst offen,
   welche alten Yield-Strings auf welche drei PauseReason-Werte gemappt werden.

**Lueckenlose Abdeckung:** Vollstaendig gegen die THEME-002-GAPs; die Luecke
liegt nicht in der Themenabdeckung, sondern in fehlenden Implementierungsdaten.

**Konkrete Nachbesserungen**
1. Alle Enum-Werte inklusive Wire-Strings direkt in die Story aufnehmen,
   mindestens fuer FailureCause, AttemptOutcome, FailureCategory,
   PromotionStatus, QaContext, BlockingCategory und SpawnReason.
2. Eine verbindliche Mapping-Tabelle fuer alte Yield-Status-Strings zu
   `PauseReason` aufnehmen oder den Helper explizit aus dem Scope nehmen.
3. Die Contract-Test-Pflichtliste in der Story selbst ausformulieren.
4. Konzeptanker um konkrete Dateipfade oder eindeutig auffindbare rel_path-
   Angaben ergaenzen, nicht nur FK-/DK-Kuerzel.

### AG3-022: Artefakt-BC Foundation - ArtifactEnvelope, ArtifactReference, ProducerRegistry

**Gesamturteil:** Nachbesserung erforderlich

**Mapping-Vollstaendigkeit:** Die Story deckt artifacts A1, A3, A4, A5, A6, A7
und C3 ab. FK-71 §71.1.1 und §71.2, FK-71-Glossar `ArtifactReference` sowie
BC-Cut §BC 8 sind die richtigen Kernanker. B4 IntegrityGate, Manager-
Persistenz, QA-Migration und Producer-Seeds anderer BCs sind korrekt
ausgeschlossen.

**Beschreibungs-Adaequanz:** Kontext und Schnitt sind klar: erst Modelle und
Registry, keine Persistenz-Migration. Die betroffenen Dateien sind fuer ein
neues `agentkit.artifacts`-Paket realistisch. Out-of-Scope ist konkret und
verhindert Scope-Creep in Richtung AG3-023 und THEME-006.

**Umsetzungsreife:** Fast ausreichend. Die Story enthaelt Modelle,
Pflichtfelder, Pydantic-v2-Konfiguration und das LLM-Status-Mapping konkret.
Unklar bleibt aber die in AK 8 verlangte `status-vs-class`-Konsistenz des
`EnvelopeValidator`: Es wird nur beispielhaft beschrieben, aber keine vollstaendige
Matrix definiert, welcher EnvelopeStatus fuer welche ArtifactClass erlaubt ist.
Falls diese Matrix im Konzept existiert, ist der exakte Anker in der Story nicht
ausreichend operationalisiert; falls sie nicht existiert, erzeugt AK 8 Design-
Spielraum.

**Lueckenlose Abdeckung:** Vollstaendig fuer den Foundation-Teil von THEME-003.
Keine implizit vergessenen artifacts-GAPs unter AG3-022; die offene Validator-
Matrix ist eine Umsetzungsreife-Luecke.

**Konkrete Nachbesserungen**
1. Die vollstaendige `ArtifactClass`-zu-`EnvelopeStatus`-Matrix in die Story
   aufnehmen oder AK 8 auf die tatsaechlich konzeptuell definierten Checks
   reduzieren.
2. Klarstellen, ob AG3-022 eine leere Registry, Test-Producer oder Seed-Daten
   fuer reine Unit-Tests erwartet, da echte verify-system-Producer erst in
   AG3-023 registriert werden.
3. FK-71-Dateipfad bzw. rel_path in den Konzeptreferenzen ergaenzen.

### AG3-023: ArtifactManager + Migration der QA-Persistenz und Protected-Path-Liste

**Gesamturteil:** Nachbesserung erforderlich

**Mapping-Vollstaendigkeit:** Die Story deckt artifacts A2, B1, B2, C1, C2 und
C3 ab. Der Schnitt ist richtig: Manager, Repository, verify-system-Migration,
Protected-Path-Umzug und Heuristik-Entfernung gehoeren zusammen, waehrend
IntegrityGate B4, ARE-Bundles, PromptRuntime-AuditRecords und andere Producer-
Seeds korrekt Out-of-Scope bleiben. FK-71 §71.2, BC-Cut §BC 8, FK-31 §31.2.x
und FK-18 §18.9a sind passende Anker.

**Beschreibungs-Adaequanz:** Die Story erklaert den Ownership-Fehler sauber:
verify-system ist aktuell de-facto Artefakt-Persistenz-Owner und soll nur noch
ueber `ArtifactManager` schreiben. Die Dateiliste ist breit, aber fuer eine L-
Story plausibel. Out-of-Scope ist konkret.

**Umsetzungsreife:** Weitgehend gut, aber nicht startklar ohne eine Praezisierung
der Datenmigration. Die Signaturen fuer Manager/Repository und die neue
Persistenzflaeche sind objektiv pruefbar. Schwach ist AK 7 bzw. der
Migrationsabschnitt: Bei Backfill neuer NOT-NULL-Spalten fehlen konkrete
Default- und Fallback-Werte fuer Alt-Daten, zum Beispiel `producer_type`,
`started_at`, `attempt` oder fehlende Envelope-Pflichtfelder. Genau dort wuerden
verschiedene Worker unterschiedliche Kompatibilitaetsentscheidungen treffen.

**Lueckenlose Abdeckung:** Vollstaendig gegen THEME-003 Teil 2. Keine relevante
GAP-Luecke, aber eine Migrations-Entscheidung ist implizit offen.

**Konkrete Nachbesserungen**
1. Backfill-Regeln fuer jede neu eingefuehrte Envelope-Spalte definieren:
   Quelle, Default, Fehlerfall und ob Alt-Daten fail-closed oder migriert werden.
2. Idempotenzkriterien fuer SQLite und Postgres explizit machen, inklusive
   Verhalten bei bereits teilweise migrierten Tabellen.
3. Protected-Path-Umzug gegen FK-31 mit konkretem Zielmodul und Re-Export-
   Verbot absichern.
4. Klarstellen, ob die vier verify-system-Producer hart in einem Init-Hook,
   Registry-Seed oder Test-Fixture registriert werden.

### AG3-024: PhaseEnvelope + RuntimeMetadata + PauseReason-Typisierung

**Gesamturteil:** umsetzungsreif

**Mapping-Vollstaendigkeit:** Die Story deckt Pipeline-Framework C1
`PhaseEnvelope` und C2 `PauseReason` ab. FK-39 §39.1/39.3, §39.2.2 und §39.4.1
sowie BC-Cut §BC 1 Layer 1 passen zum Scope. AttemptRecord, Write-Ordering,
QA-Zyklusfelder, Registry, Recovery-CLI und Transition-Enforcement sind korrekt
ausgeschlossen.

**Beschreibungs-Adaequanz:** Der Kontext ist klar: durable `PhaseState` und
ephemere `RuntimeMetadata` muessen fuer Crash-Recovery getrennt werden. Die
Dateiliste passt zur Pipeline-Engine-Topologie, inklusive Store/Repository und
Engine/Runner/Handler-Migration. Out-of-Scope ist konkret.

**Umsetzungsreife:** Die AKs sind objektiv pruefbar. `PhaseEnvelope`,
`RuntimeMetadata`, `PhaseOrigin`, `PhaseEnvelopeStore.load/save/exists`,
Persistenzgrenze und `PauseReason`-Fail-Closed-Verhalten sind ausreichend
konkret beschrieben. Die Tests pruefen das zentrale Risiko: Runtime-Daten duerfen
nicht persistiert werden.

**Lueckenlose Abdeckung:** Vollstaendig fuer die AG3-024-relevanten
Pipeline-GAPs C1/C2.

**Konkrete Nachbesserungen**
1. Optional: FK-39-Dateipfad bzw. rel_path in den Konzeptreferenzen ergaenzen.
   Das ist Komfort, kein Startblocker.

### AG3-025: AttemptRecord typisieren + Write-Ordering Crash-Safety + QA-Zyklus-Identitaeten

**Gesamturteil:** Nachbesserung erforderlich

**Mapping-Vollstaendigkeit:** Die Story deckt Pipeline-Framework B2, B4 und C4
ab: typisierte AttemptOutcome/FailureCause, neues AttemptRecord-Schema,
failure_cause-Validator und Write-Ordering `save_attempt` vor `save_phase_state`.
FK-39 §39.4.1-39.4.4, FK-27 §27.2, formal.verify.state-machine und FK-18 §18.9a
sind fachlich passende Anker. C3 Remediation-Loop und C5 Doppel-Facade sind
korrekt nicht Teil dieser Story.

**Beschreibungs-Adaequanz:** Das Warum ist stark: Crash-Safety, konzepttreues
AttemptRecord-Schema und QA-Zyklus-Identitaeten haengen am selben
Persistenzschnitt. Die betroffenen Dateien sind realistisch. Out-of-Scope ist
sauber fuer QA-Zyklus-Mechanik, Stage-Registry, Recovery-CLI und Orchestrator.

**Umsetzungsreife:** Fachlich gut, aber eine zentrale AK-Luecke bleibt: Fuer die
SQL-Migration der Attempts-Tabelle fehlen die exakten SQL-Spaltentypen,
Constraints und Backfill-Regeln. AG3-023 ist hier deutlich konkreter; AG3-025
verweist nur auf neue Spalten und CHECK-Constraints. Das ist riskant, weil
AttemptRecord gleichzeitig alte Felder in `detail` auslagert, neue Enums
erzwingt und Alt-Daten migrieren muss.

**Lueckenlose Abdeckung:** Vollstaendig gegen die AG3-025-relevanten Pipeline-
GAPs B2/B4/C4 und die QA-Zyklus-Datenmodell-Vorarbeit. Keine implizit vergessene
THEME-004-Luecke, aber die Datenbankmigration ist zu wenig spezifiziert.

**Konkrete Nachbesserungen**
1. SQL-Schema fuer SQLite und Postgres konkretisieren: Spaltennamen, SQL-Typen,
   NULL-Regeln, CHECK-Constraints und Indexe.
2. Backfill-Regeln fuer bestehende AttemptRecords definieren, insbesondere fuer
   `failure_cause`, `detail`, `ended_at` und alte freie Outcome-/Yield-Strings.
3. Klarstellen, in welchen drei Handlern die Write-Ordering-Invariante gilt und
   welche Test-Doubles die Reihenfolge beweisen.
4. Die Beziehung zwischen `outcome=YIELDED`, `PauseReason` aus AG3-024 und
   eventuellen Detail-Feldern explizit machen.

## Konzept-Spannungen (uebergreifend)

1. **PASS_WITH_WARNINGS vs. PASS_WITH_CONCERNS:** AG3-021 muss
   `PASS_WITH_WARNINGS` aus dem verify-system entfernen, waehrend AG3-022
   `PASS_WITH_CONCERNS -> WARN` fuer LLM-Status-Mapping einfuehrt. Das ist
   vermutlich korrekt, muss aber sprachlich hart getrennt bleiben, damit kein
   Worker den alten Policy-Verdict-Wert wieder legitimiert.
2. **Fail-Closed ProducerRegistry vor echten Seeds:** AG3-022 verlangt eine
   fail-closed Registry, AG3-023 registriert erst spaeter die verify-system-
   Producer. Die Stories widersprechen sich nicht, aber die Test- und
   Initialisierungsstrategie muss explizit sein, sonst entstehen Dummy-Seeds
   oder nicht-deterministische Tests.
3. **Yield-Information ueber zwei Stories:** AG3-024 typisiert `paused_reason`
   als PauseReason im Phase-Kontext; AG3-025 verlangt `AttemptOutcome.YIELDED`
   im AttemptRecord. Die Stories muessen eindeutig sagen, wo der fachliche Grund
   des Yields persistiert wird und was nur Outcome ist.
4. **Konzeptanker ohne Dateipfade:** Alle Stories arbeiten ueber FK-/DK-Kuerzel,
   nennen aber fast nie den konkreten Markdown-Pfad. Das ist kein inhaltlicher
   Widerspruch, aber ein Review- und Worker-Risiko, weil Kapitelnummern ohne
   rel_path schwerer stichprobenartig verifizierbar sind.

## Prioritaet der Nachbesserungen

**Kritisch vor Story-Start:**
1. AG3-021: vollstaendige Enum-Wertelisten, Wire-Strings und Contract-Test-
   Pflichtliste in die Story aufnehmen.
2. AG3-023: Backfill- und Default-Regeln fuer die Artefakt-Migration festlegen.
3. AG3-025: SQL-Schema, Constraints und Backfill-Regeln fuer AttemptRecords
   konkretisieren.
4. AG3-022: Validator-Matrix oder reduzierte Validator-Semantik festlegen.

**Komfort / Review-Hygiene:**
1. Konzeptreferenzen um konkrete Dateipfade bzw. rel_path-Angaben ergaenzen.
2. AG3-024 kann so starten; nur die FK-39-Referenz sollte fuer bessere
   Nachvollziehbarkeit dateigenau gemacht werden.
3. Die uebergreifende Trennung von Policy-Verdict, LLM-Status und
   EnvelopeStatus in einem kurzen Begriffskasten absichern.
