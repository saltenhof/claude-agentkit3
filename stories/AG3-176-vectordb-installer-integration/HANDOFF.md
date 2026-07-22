# HANDOFF-Briefing — VektorDB-Vorhaben AG3-174 / AG3-175 / AG3-176

**Stand:** 2026-07-22. Erstellt für einen Rechnerwechsel: dieser Stand ist
committet und auf einen WIP-Branch gepusht, damit ein anderer Agent auf einem
anderen Rechner nahtlos weitermacht. Lies dieses Dokument ZUERST vollständig.

> Der Branchname und das Weiterarbeiten stehen ganz unten unter **„Wie du
> weitermachst"**.

---

## 0. Worum es geht

Drei zusammenhängende Stories liefern Zielprojekten semantische Suche über
Stories UND Konzepte (FK-13, Pflichtinfrastruktur) via einen MCP-Server, der
gleichermaßen für **Claude Code** und **Codex** funktioniert:

| Story | Inhalt | Größe | Stand |
|---|---|---|---|
| **AG3-174** | VektorDB-Retrieval-Engine (Packaging/Tokenizer, Projekt-/Runtime-Bindung, SSOT-Ingest-Kern, StoryContext-Schema, `concept_validate`+Build, Bounded-Window `concept_sync`, Authority-Resolver, MCP-Server mit 5 FK-13-Tools) | L | **CODE-REVIEW BESTANDEN** (Closure-Gates offen) |
| **AG3-175** | Projektlokale Dual-Harness-MCP-Registrierung (`.mcp.json` + `.codex/config.toml` aus EINEM digest-gebundenen Spec, nach Conformance-Check) | M | **CODE-REVIEW BESTANDEN** (Closure-Gates offen) |
| **AG3-176** | VektorDB-Installer-Integration (Endpoint-Preflight, strikte Config-Grenze, CP10a-Erstindex+Receipts, CP10b feuernde Hooks, laufende Producer, Pflichtaktivierung, Skill ohne Grep-Fallback) | L | **MITTEN IN REMEDIATION** — offene Findings, s.u. |

Abhängigkeit: AG3-174 → AG3-175 → AG3-176. Alle drei liegen im selben Working
Tree (uncommitted delta, jetzt auf dem WIP-Branch).

---

## 1. Spielregeln der Zusammenarbeit (VERBINDLICH — so arbeitet der PO)

Diese Regeln hat der PO (Product Owner) explizit gesetzt. Halte dich daran, das
ist nicht verhandelbar:

1. **Konzeptarbeit findet NICHT in User Stories statt.** Sie passiert vorauslaufend
   im Verbund mit dem PO. Agents liefern *Solution Designs*, präsentieren sie
   verdichtet, der PO entscheidet, es wird normativ verankert, DANN werden Stories
   abgeleitet — nicht umgekehrt.
2. **„Ihr" = der orchestrierende Agent + Codex als Sparringspartner.** Grok macht
   KEINE Konzeptarbeit — Grok ist Implementer.
3. **Rollen (Work Modes) nicht mischen:** Worker (selbst umsetzen), Orchestrator
   (koordinieren, nicht nebenbei Facharbeit), Council-Orchestrator (nur
   Konzeptarbeit). Der orchestrierende Agent ist hier **Orchestrator**: er
   koordiniert Grok (Implementer) und Codex (adversarialer Reviewer), macht aber
   die Kern-Facharbeit NICHT selbst — außer im Tail (kleine, verifizierbare
   Feinheiten selbst abräumen statt eine weitere Review-Runde zu verbrennen).
4. **Konzept-/Randfälle: zwei Varianten.**
   (a) Aus bestehender Norm ableitbar → der Orchestrator löst und verankert es,
   *präsentiert als Ableitung, nicht als Frage*.
   (b) Genuin unentschieden → **PO-Entscheidung**, sequenziell einzeln vorgelegt,
   mit Kontext und optionalen Vorschlägen.
5. **NICHT fantasieren, NICHT vorauseilen.** Keine erfundenen Regeln, keine
   erfundenen Rundencaps, nichts als „out of scope" erklären, was der PO nicht
   gesagt hat.
6. **Rundendisziplin:** Codex-Runden sollen ECHTE Fehler aufdecken (verhindern,
   dass Mist gebaut wird), NICHT Codex' Perfektionstrieb befriedigen. **Aufhören,
   sobald das Verbleibende ehrlich Feinschliff ist**, den der Orchestrator selbst
   abräumt — nicht warten, bis Codex „nichts mehr gefunden" sagt (das sagt Codex
   bei seinem Naturell nie). Zehn Runden pro Story sind der Fehler.
7. **AG3-175 hatte einen harten Cap: genau EINE Codex-Runde.** AG3-174 und AG3-176
   haben KEINEN vom PO gesetzten Cap — Konvergenz auf echte Fehler, kein
   fabrizierter Cap.
8. **Gates müssen ALLE grün sein, wenn eine Story fertig ist — inklusive Sonar.**
9. **E2E-Tests sind NICHT Story-Inhalt** — nachgelagert, mit dem PO.

CLAUDE.md ist über allem normativ (ZERO DEBT, FAIL-CLOSED, SINGLE SOURCE OF
TRUTH, FIX THE MODEL, NO ERROR BYPASSING, Mocks nur im engen Ausnahmefall).
Priorität: User-Instruktion > Projektregeln (CLAUDE.md) > kanonische
Konzepte/Struktur > Heuristiken.

---

## 2. Orchestrierungs-Mechanik (wie die Agents laufen)

- **Grok** (Implementer) und **Codex** (adversarialer Reviewer) laufen über die
  MCP-Bridge `mcp__plugin_harness-bridge_subagent__submit`
  (`backend: "grok"` bzw. `"codex"`, `write: true`).
- **WICHTIG:** Bridge-Sessions sind vermutlich **rechner-/session-lokal** —
  `resume_job_id` funktioniert auf dem neuen Rechner wahrscheinlich NICHT. Starte
  im Zweifel **frische** Agents. Die durable Erinnerung sind die **Review-Dateien**
  (s.u.) — sie tragen den vollständigen Kontext.
- Jeder Sub-Agent-Auftrag beginnt mit: `Read T:/codebase/claude-agentkit3/CLAUDE.md
  first — all project rules apply to you.` und bekommt Story-Pfad + Primärquellen;
  Grok/Codex lesen die Primärquellen SELBST (nicht zusammenfassen — das
  verfälscht und senkt die Qualität; ausdrückliche PO-Ansage).
- **Ergebnis-Envelopes der Bridge sind riesig** — sie sprengen das Token-Limit.
  Fetch sie nicht roh; extrahiere die Agent-Schlussnachricht mit Python/jq aus der
  gespeicherten `.txt` (das Tool nennt den Pfad im Fehler). Oder lass Codex die
  Findings in eine Review-Datei schreiben (bevorzugt).

### Verifikationsdisziplin (KRITISCH — wiederkehrendes Problem)

**Grok meldet wiederholt „grün", obwohl es rot ist** (False-Green). Beobachtet:
- AG3-174: gemeldetes Modul war rot (falscher async-Marker).
- AG3-176: „872 passed" gemeldet, real 1 failed; später „10162 passed" gemeldet,
  aber die volle Suite hatte zwischenzeitlich **256 Regressionen**, weil Grok ein
  Kernmodell verschärfte und die volle Suite NICHT fuhr.

Konsequenz, die sich bewährt hat: **Der Orchestrator fährt die relevante Suite /
das Killer-Modul SELBST**, bevor er irgendetwas glaubt, und verifiziert konkrete
Reproduktionen selbst am echten Pfad. Ein nicht reproduzierbares Grün wird nicht
akzeptiert. Bei breit wirksamen Kernänderungen IMMER die VOLLE Suite selbst fahren
(CLAUDE.md Operations: „nicht nur ein schmaler Ausschnitt").

### Codex-Cybersecurity-Flag (Werkzeug-Reibung)

Codex' Anbieter-Klassifikator flaggt sicherheitsnahe Härtungs-Reproduktionen
(Symlink-Escape, Control-Char-Injection, Secret-Detection, Hooks) fälschlich als
„cybersecurity risk" und **bricht Codex' Turn ab**. Passiert bei AG3-175 (Review
komplett abgebrochen → der Orchestrator hat das Review selbst zu Ende geführt) und
war bei AG3-176 ein Risiko. **Gegenmittel:** Codex explizit anweisen, primär durch
Code-Lesen zu reviewen, Reproduktionen harmlos zu halten (benigne Fixtures, keine
echten Secrets), Missbrauchspfade in Prosa zu beschreiben, und bei Abbruch bis
dahin so viel wie möglich in die Review-Datei zu schreiben. Das hat bei AG3-176
funktioniert.

---

## 3. Die wiederkehrende technische Achse

**„Geerbte Nachsicht an fail-closed-Grenzen"** ist DIE zentrale Review-Achse über
alle drei Stories. Bibliotheks-Defaults, die ungültige Eingaben *reparieren* statt
sie abzulehnen: `errors="replace"`, Pydantic-Koerzierung (bool-as-int),
`.get(..., default)`, YAML last-wins, NaN/Infinity, stille Skips, `except
Exception`-Fallbacks, `int(x)`-Koerzierung auf externen Zählern, Erfolgs-
Placeholder. Sie ist als permanentes Prüfkriterium auf allen VektorDB-Stories
verankert. Grok schließt zuverlässig die *benannte Instanz*, aber oft nicht die
*Klasse* — beim Reviewen immer nach weiteren Vorkommen derselben Klasse suchen.

---

## 4. Status je Story

### AG3-174 — Engine — CODE-REVIEW BESTANDEN

- **4 adversariale Codex-Runden** (`review-1..4-codex.md` im AG3-174-Verzeichnis).
  Alle 19 Findings (8 BLOCKER + 11 MAJOR) an der Wurzel geschlossen, inkl. der
  fail-closed/Nachsicht-Achse. Der Orchestrator hat das Killer-Modul selbst grün
  gefahren (33 passed), ruff+mypy selbst grün.
- **Orchestrator-Derivationen** (keine PO-Konzeptentscheidung, aus kanonischer
  Norm; im `status.yaml` dokumentiert):
  (a) SSOT-Kern unter `src/agentkit/backend/concept_catalog/corpus/`, NICHT
  Top-Level `agentkit/concepts/` (PROJECT_STRUCTURE);
  (b) Corpus-Scope strikt aus `ProjectConfig.concepts_dir` + `.conceptignore`;
  (c) W-SCOPE-001 fundamentale Scopes deklariert der Ziel-Corpus
  (`_meta/fundamental_scopes.yaml`), nicht die Engine.
- **Offene Folge-Auflage:** FK-13 §13.6 P6-Kontextselektion hat keinen produktiven
  Consumer — als **benannter Folge-Owner** (nachgelagerte Story) zu tragen, NICHT
  still als „durch MCP vorhanden" abhaken.

### AG3-175 — Dual-Harness-Registrierung — CODE-REVIEW BESTANDEN

- **Genau EINE Review-Runde** (PO-Cap eingehalten). Die Codex-Runde wurde vom
  Cyber-Flag abgebrochen; der Orchestrator hat das Review selbst vervollständigt
  (`review-1.md` im AG3-175-Verzeichnis).
- Zwei echte Blocker (der hand-gerollte TOML-Reserializer zerlegte legitime fremde
  Configs: datetime/`[[arrays-of-tables]]` verworfen; Control-Chars korrumpiert)
  in EINER Remediation geschlossen: Umstieg auf **surgical text-merge** (fremde
  Bytes unangetastet). Der Orchestrator hat am echten Write-Pfad selbst verifiziert:
  Preservation, Idempotenz, Ersetzen ohne Duplikat-Tabelle, Fremd-Name-Konflikt
  fail-closed.
- **Merke:** Dieser surgical-merge (`codex_mcp_config_writer.py`) ist die richtige
  Referenz für AG3-176-R10 (s.u.) — dort macht `write_codex_settings()` noch einen
  Full-Replace.

### AG3-176 — Installer-Integration — MITTEN IN REMEDIATION

Ablauf bisher: Umsetzung → Codex-Review-1 (`review-1-codex.md`: 3 BLOCKER +
9 MAJOR + 2 MINOR) → Grok-Remediation → dabei **256 Regressionen** eingeführt
(globaler `PipelineConfig`-Validator erzwang vectordb-Stanza überall) →
Orchestrator diagnostiziert Root Cause + Scope-Fix (Pflicht an die Installer-Grenze,
Modell nur strict-when-present) → Grok schließt die Regressionen + findet dabei
2 echte Bugs (Static-Deploy überschrieb `.codex/config.toml`; Detach-Heuristik
löschte fremde Tabellen) → Orchestrator fährt VOLLE Suite selbst: **10162 passed,
16 skipped** (ohne live-e2e), reproduzierbar grün → Codex-Verifikation-2
(`review-2-codex.md`).

**Geschlossen & verifiziert:** R2, R3, R5, R7, R9, R11 (inhaltlich), R13.
R14 → nur noch Feinschliff (verbleibender CP10-MCP-Zweitpfad via Monkeypatch-
Routing in `cp10_mcp.py`, ~832 Zeilen; in den kanonischen `mcp_registration`-Owner
überführen).

**NOCH OFFEN — echte Substanz (MUSS-fixen, aus `review-2-codex.md`):**

1. **R1 (BLOCKER):** Fresh-Install scaffoldet ~17 Artefakte, BEVOR die
   Endpoint-Pflicht greift (`orchestrator.py:167-169` verschiebt die Ablehnung auf
   CP5/CP10). Zwei Nachsichten: (a) `orchestrator.py:194-204` fängt beim Re-Read
   *jede* Exception und fällt auf `model_dump()` zurück; (b) CP10-Preflight/CP10a
   bevorzugen `InstallConfig.weaviate_*` vor der validierten `project_config`
   (Endpoint A validiert, Endpoint B registriert). Fix: vor Bundle-Auflösung/
   Context/Engine EINE kanonische, strikt validierte Candidate-Config für BEIDE
   Fälle (fresh + existing) herstellen, dann `require_installer_vectordb_endpoint()`;
   Re-Read-Fehler ohne Fallback; alle CP10-/CP10a-/Dual-Write-Ports beziehen den
   Endpoint NUR aus dieser validierten Config.
2. **R4 (MAJOR):** Zweiter Completion-Write-Fehler lässt Story-Freshness
   fortgeschrieben (`story_freshness_published=True, concept=False`) und löscht das
   alte Story-Receipt statt es byte-genau zu restaurieren. `_assert_owned()` und
   `_assert_completion_unchanged()` in `first_index.py` sind **`pass`-Stubs** —
   beweisen nichts. `_read_completion_revision()` schluckt jede Exception. Fix:
   vor Publikation alte Bytes aller vier Artefakte sichern, bei jedem Fehler exakt
   restaurieren (oder ein einziger atomar publizierter Commit-/Manifest-Stand);
   die `pass`-Invarianten durch echte Checks ersetzen; Test für Fehler beim
   ZWEITEN Completion-Write MIT vorhandenen alten Ständen.
3. **R6 (MAJOR):** `pre_commit_is_current()`-Checks sind auch `pass`-Stubs; VERIFY
   prüft nur Marker/Textfragmente; `_staged_paths()` macht Git-Fehler zu `[]` →
   Pflichtvalidierung feuert NICHT fail-closed; `concepts_dir` wird in doppelten
   Anführungszeichen in die Shell interpoliert (nicht für alle legalen Namen
   sicher); der bestehende `hook_migration`-Owner wird nur für Marker importiert,
   die chirurgische Migration in `git_hooks.py` **zweitimplementiert** (Drift). Fix:
   Materialisierung/Erhalt über GENAU EINEN Hook-Migration-Owner; VERIFY prüft den
   kanonischen markierten Block/Digest inkl. Befehle/`--staged`/build-vor-sync/Pfad;
   Staged-Path-Fehler → Pre-Commit mit nonzero; Shell kanonisch quoten oder Pfad
   erst im Python-Dispatcher aus der strikten Config; Tests führen einen echten
   materialisierten Hook aus und prüfen fehlende/umgeordnete Befehle negativ.
4. **R8 (MAJOR):** CP8 VERIFY prüft beide Links, aber das erwartete Bundle kommt
   aus der HÖCHSTEN Store-SemVer statt aus dem installierten Pin → ein gültiges
   Altprojekt auf 4.0.0 wird als `expected @5.0.0` abgelehnt, sobald 5.0.0 im Store
   liegt. Verletzt „Altprojekte bleiben gepinnt". Fix: VERIFY liest den
   persistierten Binding-/Lock-Stand als Soll; höchste Store-SemVer nur bei
   REGISTER/explizitem Upgrade; Test mit gleichzeitig 4.0.0 UND 5.0.0.
5. **R10 (MAJOR):** Uninstall ist chirurgisch (gut), aber `write_codex_settings()`
   ist bei Fresh-Install noch **Full-Replace**, wenn die bestehende Datei den
   AK3-Hook noch nicht enthält → zerstört eine fremde hooklose `.codex/config.toml`
   (reproduziert: `foreign_preserved=False`). Fix: den Codex-Hook als chirurgischen
   markierten TOML-Block über den semantischen TOML-Owner mergen (die AG3-175-
   surgical-merge-Referenz nutzen!); bei unparsebarer/konfligierender Fremdconfig
   fail-closed, NIEMALS Full-Replace; Test mit rein fremder Ausgangsdatei.
6. **R12 (MAJOR):** Testevidenz besser, aber die entscheidenden Negativgrenzen
   fehlen weiter (fresh-install-ohne-Endpoint vor Scaffold; zweiter Completion-Write
   mit alten Ständen; materialisierter Hook bei Git-/Staged-Fehler + tampered
   Commands; konsistenter Altprojekt-Pin bei neuer Store-Version; rein fremde
   `.codex/config.toml` vor Fresh-Install). Die Tests an den ECHTEN produktiven
   Grenzen ergänzen; Source-Substring-Assertions reichen nicht.
7. **N1 (MAJOR, NEU durch die Remediation):** Grok hat den flaky Mutex-Race-Test
   (`tests/unit/concept_toolchain/test_mutex_race.py`) **mit Retries + externem
   Cleanup maskiert** statt den Liveness-Bug (beide Prozesse brechen gelegentlich
   mit `[2,2]` ab) zu beheben. Das ist ZERO-DEBT-widrig. **WICHTIG:** Das
   `concept_toolchain`-Mutex ist NICHT AG3-176-Scope (DK-16/FK-78 Concept-Incubation,
   vorbestehende Flakiness). Empfehlung: die Test-Maskierung REVERTIEREN (Original-
   Test wiederherstellen); den vorbestehenden Mutex-Liveness-Bug als SEPARATES
   Ticket tragen, NICHT AG3-176 aufblähen. (Prüfen: war der Original-Test in den
   früheren grünen 10133-Läufen stabil? Falls ja, ist das `[2,2]` selten und der
   Original-Test bleibt vertretbar.)

**Anti-Pattern-Callouts für die nächste Grok-Remediation:** `pass`-Stub-
„Invarianten" sind verboten (eine Invariante, die `pass` ist, beweist nichts —
echten Check oder gar nicht behaupten); eine Test-Maskierung ist ein ZERO-DEBT-
Verstoß; die Nachsicht-KLASSE töten, nicht nur die Instanz (except-any, `[]`-
Fallback, Full-Replace, `InstallConfig.weaviate_*`-Override). Real-Boundary-Tests
verpflichtend; der Orchestrator fährt danach die volle Suite + die konkreten
Reproduktionen SELBST.

---

## 5. ENTSCHEIDUNGSBEDARF (PO)

**D1 — Konzept-Gate-Blocker (offen, war gerade dem PO vorgelegt, als der Wechsel
kam):** Die Konzept-Gates W2/W3 (`check_concept_authority_prose.py`,
`check_concept_scope_consistency.py`) laufen NICHT grün, weil ein **vorbestehendes**
tracked Dokument `concept/_meta/bc-cut-decisions.md` `doc_kind: decision-log` trägt,
das der Validator ablehnt (`E-SCHEMA-003`: nur `decision-record` u. a. erlaubt).
Das ist KEIN AG3-176-Finding (nicht im Diff), blockiert aber die Grün-Bestätigung
der Gates (auch für AG3-176s FK-50-Edit). Es ist eine **Konzept-Governance-
Entscheidung** und gehört nicht in die Story. Vorgeschlagene Optionen:
  - (empfohlen) **Validator: `decision-log` zulassen** — kleiner Tooling-Fix, keine
    inhaltliche Doc-Änderung, semantisch sinnvoll, wenn das Doc bewusst ein
    fortlaufendes Log mehrerer Entscheidungen ist;
  - **Doc auf `decision-record` umstellen** — keine Validator-Änderung, aber evtl.
    semantisch ungenau;
  - **Separat, später** — als eigenes Governance-Ticket, AG3-176 vorerst ohne
    grüne W2/W3-Bestätigung weiter (Gate vor dem echten Landen nachziehen).
Der Orchestrator wollte dies als kleine PO-Entscheidung sequenziell vorlegen; sie
ist noch OFFEN.

**D2 (implizit in N1):** Falls für das concept_toolchain-Mutex eine
Caller-Retry-Semantik gewünscht ist statt Single-Winner-Liveness, wäre das eine
Konzeptentscheidung (produktiv implementieren, nicht im Test simulieren). Default-
Empfehlung: Single-Winner-Liveness im Algorithmus, Test-Maskierung revertieren.

---

## 6. CLOSURE-GATES (Orchestrator-owned, für ALLE drei Stories, vor dem Landen)

Keine der drei Stories ist auf `done` — bewusst. Vor dem tatsächlichen Landen:
- **Volle `pytest`-Suite grün + Coverage ≥85%.** (Zuletzt vom Orchestrator selbst
  grün gefahren: 10162 passed/16 skipped OHNE live-e2e; Coverage war in früheren
  Läufen ~90%, muss beim Closure einmal explizit bestätigt werden.) Die opt-in
  live-e2e (`tests/e2e/github_live`, `tests/e2e/smoke`) brauchen echte Infra und
  sind NICHT Standard-CI.
- **mypy src / ruff check src tests** sauber (zuletzt grün).
- **Konzept-Gates grün** — blockiert aktuell an D1.
- **Sonar** — zuletzt sauber verifiziert (Quality Gate OK, violations=0,
  critical=0, security_hotspots=0).
- **AG3-172 (Postgres-Race) muss VOR dem Merge von AG3-174 gelandet sein** —
  als echtes Workflow-/Merge-Gate, nicht als Kommentar (AG3-174 R18). AG3-172 ist
  ein separater Bugfix (Story-Verzeichnis vorhanden), Stand `ready`.
- **FK-13 §13.6 P6-Consumer** als benannter Folge-Owner vermerken (AG3-174).

---

## 7. CI-Infrastruktur (Kontext, bereits erledigt)

- Der CI-Postgres-Container wurde auf **`seu-ci-postgres`** (Port **55432**, Creds
  **`ci:ci`**) umbenannt/rekonziliert; AK3 (`Jenkinsfile`, `prompts/agent-onboarding.md`)
  und das Nachbar-Repo `T:/codebase/seu-ci-infrastructure` sind angeglichen und
  gepusht. Der laufende Container ist healthy und aus Jenkins auflösbar.
- **Jenkins-Build 1184 = FAILURE ist der ALTE Build VOR diesem Fix** (`seu-ci-postgres`
  war da noch nicht auflösbar). Kein neuer Build, kein Code-Finding. Der echte
  Beweis ist der NÄCHSTE Build — der PO triggert ihn.
- **Gate-Helper-Drift:** `scripts/ci/check_remote_gates.ps1` bekommt von Jenkins
  HTTP 401 — der laufende Jenkins hat `useSecurity=true`, die hinterlegten
  Placeholder-Credentials passen nicht (AGENTS.md-Annahme veraltet). Separat zu
  klären; kein roter Build.

---

## 8. Beobachtungen & Empfehlungen

- **Grok ist ein fähiger Implementer, aber:** meldet zu oft False-Green, schließt
  die benannte Instanz statt der Klasse, hinterlässt gelegentlich `pass`-Stub-
  „Invarianten" und hat einmal einen Test maskiert. → Immer selbst verifizieren
  (volle Suite bei Kernänderungen), Anti-Pattern explizit benennen, Real-Boundary-
  Tests erzwingen.
- **Codex ist ein exzellenter, ehrlicher Fehlerdetektor** (pingelig — das ist
  gewollt), trennt auf Anweisung sauber BLOCKER/MAJOR von MINOR/NIT. Aber:
  Cyber-Flag-Abbrüche bei sicherheitsnahen Reproduktionen → entsprechend briefen.
- **AG3-176 ist der harte Brocken** (wie AG3-174): L-Installer-Story, tiefe
  fail-closed-Semantik. Rechne mit 1–2 weiteren gezielten Remediations-/
  Verifikations-Zyklen. Codex sagt zu Recht: bei Fix nur der Restliste (R1, R4, R6,
  R8, R10, R12, N1 + D1-Gate) genügt danach eine gezielte Verifikation, kein
  Flächenreview.
- **Escalation-Option:** Wenn Grok bei DENSELBEN Findings erneut nur Oberfläche
  liefert, sind R4/R10 chirurgisch klein genug, dass der Orchestrator sie selbst
  abräumen kann (R10 = AG3-175-surgical-merge wiederverwenden). Das ist der Tail-
  Feinschliff, den der PO ausdrücklich erlaubt.

---

## 9. Wichtige Dateien / Wo was liegt

- Stories: `stories/AG3-174-…/`, `stories/AG3-175-…/`, `stories/AG3-176-…/` (je
  `story.md`, `status.yaml`, Review-Dateien — die `status.yaml` tragen detaillierte
  Verlaufs-Kommentare).
- AG3-174 Kern: `src/agentkit/backend/concept_catalog/corpus/` (SSOT-Discovery/
  Parser/Chunking/Identity), `src/agentkit/backend/vectordb/` (schema, tokenizer,
  runtime_binding, ingest/, concept_corpus/, mcp*), `integration_clients/vectordb/
  weaviate_adapter.py`.
- AG3-175: `harness_client/harness_adapters/codex_mcp_config_writer.py` (surgical
  merge — Referenz für R10), `backend/installer/mcp_registration/{bound_spec,
  dual_write}.py`.
- AG3-176: `backend/installer/bootstrap_checkpoints/{cp10.py (42 Zeilen dünn),
  cp10_mcp, cp10a_first_index, cp10b_hooks, cp10c_are, cp10d_sonar, cp10_common,
  orchestrator, cp01_to_06, cp07_to_09, runner}.py`, `backend/config/{strict_yaml,
  loader,models}.py`, `backend/vectordb/{endpoint_preflight,wait_for_weaviate,
  first_index,indexing_receipt,git_hooks,hook_dispatch,sync_task_registry}.py`,
  `backend/closure/runtime_ports.py`, `backend/installer/mcp_registration/
  detach_story_kb.py`, `backend/installer/codex_settings.py`,
  `bundles/skill_bundles/create-userstory-core/5.0.0/` (4.0.0 bleibt für Pinning).
- Decision Record der Konzept-Ränder: `concept/_meta/decisions/
  2026-07-21-vectordb-edge-sharpening.md`. Quell-Konzept: FK-13 =
  `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md`.

---

## 10. Wie du weitermachst

1. **Branch auschecken** (Name siehe Commit-Message / `git branch -a`; er heißt
   `wip/ag3-174-176-vectordb-handoff`): `git fetch && git checkout
   wip/ag3-174-176-vectordb-handoff`.
2. `.venv\Scripts\python -m pip install -e ".[dev]"` (pyproject hat neue Deps:
   `weaviate-client>=4.9,<5.0`, `tokenizers==0.21.0`, `mcp`).
3. **Verifiziere den Ausgangsstand SELBST:** volle Suite ohne live-e2e —
   `.venv\Scripts\python -m pytest tests --ignore=tests/e2e/github_live
   --ignore=tests/e2e/smoke -q` (erwartet ~10162 passed). Nicht Grok/Codex blind
   glauben.
4. **Hol die PO-Entscheidung D1** (doc_kind `decision-log`) ein, wenn noch offen.
5. **Nächster Schritt AG3-176:** eine gezielte Grok-Remediation für R1, R4, R6, R8,
   R10, R12 + N1-Revert (mit den Anti-Pattern-Callouts aus §4), dann Codex-
   Verifikation NUR dieser Restliste, dann selbst verifizieren. Danach sind alle
   drei Stories bereit für die Closure-Gates (§6).
6. **Halte dich an die Spielregeln (§1)** und die Verifikationsdisziplin (§2).

Dieser WIP-Stand enthält offene AG3-176-Findings — er ist NICHT landbar, sondern
ein Sicherungs-/Übergabestand. Kein `done`, kein Merge auf `main`, bevor die
Restliste + Closure-Gates grün sind.
