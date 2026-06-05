# AG3-056: Pre-Merge-Verification-Runner — Build/Test + Sonar-Scan auf dem integrierten Kandidaten (commit-gebunden, via CI), Vorbedingung fuer AG3-053 Closure

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:**
- AG3-052 (SonarQube-Gate-Capability: Attestation-Modell, Green-Definition, Accepted-Ledger-Reconciler, Applicability — dieser Runner ERZEUGT die Analyse und liefert die von Sonar an den Commit gebundene `SonarAttestation`, die AG3-052 bewertet; **kein Neubau** der Green-/Reconciler-Logik)
- FK-03-Config-Modell (`sonarqube`-Stanza via AG3-052 vorhanden) — neue `ci`/`jenkins`-Stanza (`available`/`base_url`/`token_env`/`pipeline`)
- (verwandt, keine harte Dependency) AG3-018 (Fast-Modus / Live-Test-Runner-Boundary) — dieselbe Runner-Klasse, fast vs. standard

**Unblocks:**
- AG3-053 (Closure-Pre-Merge-Barriere kann ihre `PreMergeScanPort` + `BuildTestPort` an **echte, commit-gebundene** Runner anschliessen, statt an einen fail-open Lese-Stub bzw. einen reinen fail-closed Build/Test-Stub)

**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-29 §29.1a.3` (Closure-Pre-Merge: integrate-latest-main → Build/Test → Scan **auf dem integrierten Kandidaten**; die Attestation muss den gemergten Stand betreffen, `tree_hash(scan)==tree_hash(merge)`)
- `FK-33 §33.6.3` (commit-gebundene Sonar-Attestation, Community-Branch-Plugin, Green-Definition; **kein Live-`projectKey`-Read**, Bindung an die konkrete Analyse via `analysisId`/`ceTaskId`, `sonar.qualitygate.wait=true`)
- `FK-33 §33.6.5` (3-Zustands-Applicability)
- `FK-35 §35.2.4a` (Dim 9 verifiziert die frische, commit-gebundene Attestation — nachgelagerter Konsument)
- `DK-04 §4` (Mehrstufige QS / Trust-Klassen)
- `CLAUDE.md` (FAIL-CLOSED; `integrations/` = duenne Adapter, keine Fachlogik)

---

## 1. Kontext

Die Closure-Pre-Merge-Barriere (AG3-053, FK-29 §29.1a.3) muss vor dem Merge den
**integrierten Kandidaten** (Story-Branch mit frisch eingearbeitetem `main`)
bauen, testen und per Sonar pruefen — und nur bei einem **grünen, an genau
diesen Commit gebundenen** Ergebnis mergen. Heute ist genau dieser **Ausfuehrungs-
und Bindungs-Schritt nicht implementiert**:

- **AG3-052** baute die Sonar-**Gate-Capability** (Attestation-Modell, Green-Definition,
  Reconciler, Applicability) — aber **keinen Scan-Runner**: der vorhandene Pfad
  (`build_sonar_gate_port_for_run().resolve_inputs()`) **liest nur ein bereits
  vorhandenes `report-task.txt`** und leitet `commit_sha`/`tree_hash` separat aus
  `git rev-parse HEAD` ab. Damit kann ein **stale** Analyse-Artefakt lokal an den
  aktuellen HEAD „angeklebt" werden → die Bindung ist **nicht von Sonar bewiesen**
  (fail-open).
- Es gibt **keinen in-repo Build/Test-Runner**: Layer-1/AG3-042 prueft nur
  Artefakte/Snapshots/State, kein Build, kein Testlauf.

Folge (durch unabhaengiges Review belegt): AG3-053 kann den Positivfall „grüner
Scan auf dem gemergten Stand → merge" produktiv **weder ausführen noch testen** —
nur den Negativfall. Diese Story baut die **fehlende Runner-Capability**: einen
**Pre-Merge-Verification-Runner**, der Build/Test **und** Sonar-Scan für einen
gegebenen integrierten-Kandidaten-Commit **ausführt bzw. via CI anstößt, abwartet
und ein von Sonar/CI an genau diesen Commit gebundenes Ergebnis** liefert. AG3-053
bleibt **Owner/Orchestrator** und ruft diesen Runner nur auf.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 CI-Trigger-Adapter (`integrations/<ci>/`) — duenner, fail-closed Client
- Thin Adapter ueber die CI-API (Jenkins; SSOT der Build/Test/Sonar-Ausfuehrung im
  Projekt): einen Pipeline-Lauf fuer **einen konkreten Commit/Branch** (integrierter
  Kandidat) **auslösen**, den Lauf **abfragen/abwarten** (poll bis terminal), und das
  Ergebnis + die erzeugte Sonar-Analyse-Referenz (`ceTaskId`/`analysisId`) zurueckgeben.
- **Keine Fachlogik** im Adapter. Auth/Token aus FK-03-Config. Erreichbarkeit/
  Pipeline-Existenz/Timeout werden **fail-closed** behandelt (konfiguriert-aber-
  unerreichbar ≠ deklariert-nicht-verfuegbar).

#### 2.1.2 Build/Test-Runner (commit-gebunden) — erfuellt `BuildTestPort`
- Fuehrt Build + Test fuer den integrierten-Kandidaten-Commit aus bzw. stößt den
  CI-Lauf dafuer an und wartet; liefert `(green: bool, reason: str | None, commit_sha)`.
- Das Ergebnis ist **an den Commit gebunden** (das Gebaute/Getestete IST der
  integrierte Kandidat). Rot/Abbruch → fail-closed.
- Schnittstelle ist **exakt** die von AG3-053 konsumierte `BuildTestPort`-Form
  (Protocol), produktiver Adapter + fakebare Naht.

#### 2.1.3 Sonar-Scan-Runner (commit-gebunden, Branch-Plugin) — erfuellt `PreMergeScanPort`
- Stellt sicher, dass tatsaechlich **eine Analyse für den integrierten Kandidaten
  ausgeführt** wird (Scanner auf dem integrierten Branch mit
  `sonar.qualitygate.wait=true`, bzw. CI-getriggert), und liefert die **AG3-052-
  `SonarAttestation`**, deren `last_analyzed_revision` **== dem integrierten-
  Kandidaten-Commit** ist (Bindung **von Sonar bewiesen**, nicht lokal gestempelt).
- Green-Definition/Attestation/Reconciler stammen aus AG3-052 (konsumiert, nicht
  neu gebaut). Ergebnis ist eine `ScanOutcome` mit `produced` + `commit_sha` +
  `tree_hash`, die **aus der geprueften Analyse** stammen.

#### 2.1.4 Bindungs-Beweis + FAIL-CLOSED (Kern dieser Story)
- Ein Ergebnis wird **nur** akzeptiert, wenn (a) Sonar `last_analyzed_revision ==
  candidate.commit_sha` für den gemessenen Branch meldet **und** (b) Build/Test
  nachweislich für denselben Commit lief.
- **Niemals fail-open:** stale `report-task.txt`, abweichende `last_analyzed_revision`,
  falscher Branch, fehlender/abgebrochener CI-Lauf, Unerreichbarkeit → **fail-closed**
  (der Runner liefert ein „nicht produziert/ungebunden"-Ergebnis; die Barriere in
  AG3-053 eskaliert). Es wird **kein** Commit lokal an eine fremde Analyse geklebt.

#### 2.1.5 Vertrag/Ports fuer AG3-053
- Die Capability exponiert genau die Port-Formen, die AG3-053 konsumiert
  (`PreMergeScanPort.produce_attestation(...) -> ScanOutcome`,
  `BuildTestPort.run(...) -> (green, reason)`), mit commit-/tree-gebundenen
  Ergebnissen. Die Naht ist **fakebar** (Protocol), sodass sowohl diese Story als
  auch AG3-053 den **Positiv- UND Negativfall** im Unit-/Integrationstest
  abdecken; der **produktive Adapter** wird gegen reales Jenkins/Sonar verifiziert.

#### 2.1.6 Config (FK-03) + Installer-Checkpoint
- `ci`/`jenkins`-Stanza (`available`/`enabled`/`base_url`/`token_env`/`pipeline`/
  `poll_timeout`), `extra="forbid"`, Cross-Field-Validierung analog AG3-052
  (`available:true` + fehlende `base_url`/`token_env` → `ValueError`).
- Installer-Vorbedingung applicability-konditional: `available:false` → SKIPPED
  (`reason="not_applicable"`, nicht FAILED); `available:true` fail-closed:
  Erreichbarkeit + Token-Rolle + Pipeline existiert.

#### 2.1.7 Tests
- **Unit:** Bindungs-Beweis (`last_analyzed_revision == commit` → ok;
  mismatch/stale/falscher Branch → fail-closed), Build/Test green/red commit-gebunden,
  Applicability, Config-Cross-Field.
- **Integration:** Runner end-to-end gegen einen **gestubbten** CI-/Sonar-Client
  (echte Runner-/Bindungs-Logik, nur die HTTP-Grenze gestubbt — MOCKS-Ausnahme:
  externes System im Test nicht verfuegbar): **Positivfall** (CI grün + Analyse für
  den Commit → produced+bound) **UND** Negativfaelle (kein Lauf, stale Analyse,
  Revisions-Mismatch, rot, unerreichbar → fail-closed).
- **E2E (opt-in, nicht Standard-CI):** echter Jenkins/Sonar-Lauf auf einem
  Wegwerf-Commit — beweist den produktiven Adapter end-to-end.

### 2.2 Out of Scope (bewusst, mit Owner)
- **Closure-Pre-Merge-Barriere-Orchestrierung** (integrate-latest-main, `tree_hash(scan)==tree_hash(merge)`-Check, CAS/lease gegen `locked_sha`, Checkpoints, Saga-Push/Merge) — **AG3-053** (Konsument; diese Story liefert nur die Runner).
- **Sonar-Green-Definition / Attestation-Modell / Reconciler / Applicability** — **AG3-052** (konsumiert).
- **Fast-Modus Sanity-Gate + Live-Test-Runner für fast** — **AG3-018** (verwandt; hier der Standard-Modus-Runner auf dem integrierten Kandidaten).
- **Live-Jenkins-/Sonar-Server-Provisionierung** — Betriebs-/Installer-Thema; Unit/Integration laufen gegen den gestubbten Client.

## 3. Betroffene Dateien (Richtwert)
| Datei | Art | Beschreibung |
|---|---|---|
| `src/agentkit/integrations/<ci>/` (`__init__.py`, `client.py`) | Neu | Duenner CI/Jenkins-Adapter (Lauf auslösen, abwarten, Ergebnis + Sonar-Analyse-Referenz), fail-closed |
| `src/agentkit/verify_system/pre_merge_runner/` (`__init__.py`, `scan_runner.py`, `build_test_runner.py`, `binding.py`) | Neu | Pre-Merge-Verification-Runner: Ausfuehrung + Bindungs-Beweis; liefert `PreMergeScanPort`/`BuildTestPort`-konforme, commit-gebundene Ergebnisse (konsumiert AG3-052) |
| `src/agentkit/core_types/` (Config) + FK-03-Config-Modell | Modifiziert | `ci`/`jenkins`-Stanza + Cross-Field-Regel |
| `src/agentkit/.../installer` | Modifiziert | Applicability-konditionaler CI-Checkpoint (SKIPPED vs FAILED) |
| `tests/unit/verify_system/pre_merge_runner/*` | Neu | Bindungs-Beweis, Build/Test, Applicability, Config |
| `tests/integration/verify_system/test_pre_merge_runner.py` | Neu | Runner end-to-end gegen gestubbten CI/Sonar-Client (Positiv + Negativ) |
| `tests/e2e/...` (opt-in) | Neu | Echter Jenkins/Sonar-Lauf (nicht Standard-CI) |

## 4. Akzeptanzkriterien
1. **Scan wird AUSGEFUEHRT, nicht abgelesen:** Der Scan-Runner stellt sicher, dass für den integrierten-Kandidaten-Commit tatsaechlich eine Analyse laeuft (Scanner mit `qualitygate.wait` bzw. CI-getriggert + abgewartet). Test belegt: ohne passendes, frisches Analyse-Ergebnis für den Commit → **kein** „produced", **kein** Stale-Read. (behebt Review-ERROR-1)
2. **Bindung von Sonar bewiesen:** Eine Attestation wird **nur** akzeptiert, wenn `last_analyzed_revision == candidate.commit_sha` (und Branch == Kandidaten-Branch); `tree_hash` wird **aus dem geprueften Commit** abgeleitet, nicht lokal an `HEAD` geklebt. Mismatch/stale → fail-closed. (behebt Review-ERROR-2)
3. **Build/Test commit-gebunden:** Build+Test laufen für genau den Kandidaten-Commit; Ergebnis traegt den `commit_sha`; rot/Abbruch → fail-closed.
4. **FAIL-CLOSED ueberall:** unerreichbares CI/Sonar, fehlender/abgebrochener Lauf, Revisions-Mismatch, falscher Branch → „nicht produziert/ungebunden" (Barriere eskaliert). **Niemals** fail-open, **niemals** lokales Anstempeln.
5. **Port-Vertrag = AG3-053:** Die Runner erfuellen exakt `PreMergeScanPort.produce_attestation` und `BuildTestPort.run`; `ScanOutcome` traegt `produced` + `commit_sha` + `tree_hash` aus der geprueften Analyse. AG3-053 kann sie ohne weitere Aenderung konsumieren (dokumentierter Vertrag).
6. **Testbarkeit Positiv UND Negativ:** Fakebare Naht → Unit/Integration decken den **Positivfall** (grün + commit-gebunden → produced) und die Negativfaelle ab; ein **produktiver Adapter** existiert; **opt-in E2E** beweist den Adapter gegen reales Jenkins/Sonar.
7. **Config/Installer** applicability-konditional (FK-03 + Installer-CP): `available:false` → SKIP; `available:true` fail-closed (Erreichbarkeit/Token/Pipeline). Tests belegen SKIPPED vs FAILED.
8. **Architecture-Conformance:** `integrations/<ci>` duenn (keine Fachlogik); Runner in `verify_system`; **keine zweite Sonar-/Green-Wahrheit** (AG3-052 wiederverwendet); ggf. `entities.md`-Registrierung der neuen Module.
9. **Pflichtbefehle grün:** pytest unit+integration (+ contract falls Schemas); mypy strict; ruff; Coverage ≥ 85%; vier CI-Konzept-Gates grün.

## 5. Definition of Done
- AK 1-9 erfuellt; `.venv\Scripts\python -m pytest` (unit+integration) grün; mypy/ruff grün; Konzept-Gates grün.
- Giftige Codex-Review (+ ggf. Grok) → PASS; Jenkins SUCCESS; Sonar Quality Gate OK.
- Aenderungen committed auf `main`; **AG3-053 als unblockt vermerkt** (Closure-Barriere kann `PreMergeScanPort`/`BuildTestPort` an die echten Runner anschliessen).

## 6. Konzept-Referenzen (autoritativ)
- **FK-29 §29.1a.3** — Closure-Pre-Merge-Reihenfolge + integrierter Kandidat + `tree_hash(scan)==tree_hash(merge)` (Konsumkontext)
- **FK-33 §33.6.3 / §33.6.5** — commit-gebundene Attestation / Branch-Plugin / Green-Definition / Applicability
- **FK-35 §35.2.4a** — Dim 9 verifiziert die frische Attestation (Downstream)
- **DK-04 §4** — Mehrstufige QS / Trust-Klassen

## 7. Guardrail-Referenzen
- **FAIL CLOSED:** konfiguriert-aber-unerreichbar/rot/stale/Revisions-Mismatch → BLOCK; `available:false` ist deklarierte Nicht-Anwendbarkeit (SKIP), kein fail-open.
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** Green-Definition + Attestation NUR aus AG3-052; keine zweite Wahrheit; Bindung von Sonar bewiesen, nicht lokal erzeugt.
- **MOCKS NUR IM AUSNAHMEFALL:** nur die externe CI/Sonar-HTTP-Grenze gestubbt; Runner-/Bindungs-Logik echt getestet; echter Lauf in opt-in E2E.
- **integrations = duenne Adapter:** keine Fachlogik in `integrations/<ci>`.

## 8. Hinweise fuer den Sub-Agent
- Diese Story ist **Vorbedingung** für die AG3-053-#1-Remediation: AG3-053 hat die Barriere-Struktur bereits (lock/integrate/clean/capture/CAS/tree-check), aber ihre Scan-/Build-Test-Ports haengen mangels echtem Runner in der Luft. Hier wird genau dieser Runner gebaut.
- **Bindung ist der Kern:** Closure darf nur mergen, wenn das Gepruefte beweisbar = das zu Mergende ist. Verlasse dich für die Bindung auf das, was **Sonar/CI selbst** über den analysierten Commit meldet — niemals auf lokales `git rev-parse HEAD`-Anstempeln einer fremden Analyse.
- AG3-052 liefert Attestation/Green-Definition/Reconciler — **wiederverwenden**, nicht neu bauen.
- Echtes Jenkins/Sonar ist im Unit/Integrationstest NICHT verfuegbar — gegen gestubbten Client testen; den echten Adapter via opt-in E2E.
- Verwandt, aber getrennt: AG3-018 (fast-Modus-Test-Runner). Wenn dort bereits eine wiederverwendbare Test-Runner-Naht existiert, konsumieren statt duplizieren; sonst sauber abgrenzen.
- AK2 NICHT veraendern.
