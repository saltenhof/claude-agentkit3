# Orchestrator-Handover — Session-Ownership-Strang (Stand 2026-07-07)

> Für den **nachfolgenden Orchestrator** auf einem anderen Rechner ohne den Kontext der Vorsession.
> Autoritativer Repo-Stand bei Übergabe: `origin/main` = **`7ca17bad`**.
> Dieses Dokument liegt bewusst im AG3-148-Ordner, weil AG3-148 der nächste kritische Pfad ist —
> es beschreibt aber den **gesamten** Arbeitsstand, nicht nur AG3-148.

---

## 0. TL;DR — was als Nächstes zu tun ist
1. `git pull` auf `origin/main` (`7ca17bad`). AG3-147 ist **geschlossen** (grün).
2. **AG3-148 ist `ready`** (kritischer Pfad). Starte dafür einen Codex-Worker mit dem in §7 eingebetteten, fertig ausgearbeiteten Auftrag.
3. Danach Codex-Review (read-only). Bei Konvergenz Deckel-Regel → schließen. Dann die Ownership-Kette weiter (149→…→156, mit 152/156 parallel).
4. Unabhängige Blätter (131/132/133/134/157) sind Füllmaterial; 157-Auftrag ist in §7 ebenfalls eingebettet.

---

## 1. Rolle & Arbeitsmodell (verbindlich — vom PO gesetzt)

- **Orchestrator, nicht Worker.** Du koordinierst, editierst **keinen Python-/Produktivcode selbst**. Deine Lane: `status.yaml`, `stories/README.md`-Snapshot, Design-Markdowns, Dispatch von Workern + Reviews, Adjudikation.
- **Jeder Implementierungs- oder Bugfix-Task → Codex-Subworker** über die harness-bridge (`mcp__plugin_harness-bridge_subagent__submit`, `backend: "codex"`, `write: true`).
  - Codex **besitzt die volle Schleife bis grün-auf-main**: implementieren → lokale Gates → push → Jenkins SUCCESS → Sonar-Gate grün → bei rot in-Code remediieren → **erst zurückkommen wenn wirklich grün auf main**. Gib ihm „green-on-main in CI" explizit als Akzeptanzkriterium.
  - Codex hat **kein 10-Minuten-Timeout-Problem**. Sag ihm, dass Suiten teils >20 min laufen, damit er command-timeouts **≥2400 s** setzt.
- **QS-Reviews:** read-only (`write: false`).
  - **KEINE Fable-Reviews mehr** (ausdrückliche PO-Anweisung vom 2026-07-07). Vorher lief Codex+GLM, dann Fable+Codex — **beides Geschichte für Fable**. Nutze **Codex** als Reviewer (bei Bedarf zusätzlich GLM/Kimi über die harness-bridge-Backends). Historische Warnung: **GLM hatte einen kostspieligen False-APPROVE** (übersah eine stale-evidence-CRITICAL, weil es dem Happy-Path-Test vertraute) — Review-Ergebnisse daher **immer per Code-Lesung adjudizieren**, nicht blind übernehmen.
- **Deckel-Regel:** Gibt eine Re-Review **nur noch kosmetische/stilistische Reste** zurück (kein Funktions-/fail-open-/AC-/Konzept-/Guardrail-Befund), **fixe sie selbst** (bzw. via kleinem Worker) und **schließe ohne weitere QS-Runde**. Flagge es explizit, wenn du die Regel anwendest.
- **Hard-Stop / Eskalation:** Bei **Oszillation** (dieselbe Fehlerklasse überlebt mehrere Runden, Fixes patchen nur Symptome) → **keine weitere Runde**, sondern **an den PO eskalieren** mit Root-Cause. Das ist dann ein Architektur-/Design-Entscheidungsproblem, kein Worker-Kapazitätsproblem. (Genau das ist bei AG3-147 passiert — siehe §5.)
- **Parallelisierungs-Trigger (wichtig, PO-präzisiert):** **Nicht** von Projektbeginn an mehrere write-Worker parallel. Den nächsten Task erst starten, wenn der laufende **konvergiert** ist — d.h. nach Review-Runde 2/3, Stand stabil, nur noch kleine überschaubare Reste, **kein großes Refactoring mehr zu erwarten**. Read-only Feasibility/Analyse darf man vorziehen.
- **Serielle Checkout-Realität (harte technische Grenze):** Alle Codex-write-Worker teilen sich **einen** Repo-Checkout, **ein** venv und **eine** CI-Pipeline (Jenkins/Sonar auf `main`). Zwei gleichzeitige write-Worker zerschießen sich Arbeitsbaum und Commits (`git add -A` erfasst fremde Änderungen; Push-Race). → **write-Worker laufen seriell.** Read-only Reviews/Analysen laufen problemlos parallel.

---

## 2. Tooling & Zugänge (auf dem neuen Rechner prüfen!)

- **harness-bridge** (MCP-Plugin): `...__doctor` zuerst laufen lassen — erwartet `ok:true`, Codex-CLI vorhanden, Daemon erreichbar mit Backends `codex, grok, kimi, glm`. In der Vorsession: Codex-CLI 0.142.5.
  - Dispatch: `...__submit {backend:"codex", write:true|false, title, prompt}` → gibt `job_id`.
  - Fortschritt: `...__status {job_id}`, `...__tail {job_id, since_seq, rendered:true}`, `...__wait {job_ids, timeout_ms}`, Ergebnis: `...__result {job_id}`.
  - **Achtung:** `result`/`tail`-Ausgaben sind oft riesig (Prompt-Echo je Event) und überschreiten das Token-Limit. Sie werden dann in eine Datei gespeichert; hol dir gezielt `jq -r '.result.summary'` bzw. `.result.exit_status` heraus statt die ganze Datei zu lesen. Der finale Verdict/Report steht in `.result.summary`.
  - Der Harness benachrichtigt dich bei Job-Abschluss automatisch (Channel-Message) — **nicht** eng pollen.
- **venv (Pflicht):** `.venv\Scripts\python -m ...`. **NIEMALS global `pip install`** — AK3 und AK2 teilen den Package-Namen `agentkit`; ein globaler Install überschreibt AK2 und zerstört dessen Claude-Code-Hooks.
- **Gates vor jedem Merge:** `.venv\Scripts\python -m ruff check src tests`, `... -m mypy src` (und `--platform linux`), `... -m pytest` (Coverage ≥ **85 %**), plus 4 Konzept-Gates (concept-frontmatter, formal-specs, concept-code-contracts, architecture-conformance).
- **Jenkins:** Der Job `claude-agentkit3` ist **unparametrisiert** → CI-Trigger ist **`POST /job/claude-agentkit3/build?delay=0sec`** (+ CSRF-Crumb aus `/crumbIssuer/api/json`); `buildWithParameters` gibt hier **400**. Jenkins läuft mit `SecurityRealm=None`/`Unsecured` (kein Login, anonym = Vollzugriff, kein Token nötig). Details in **`AGENTS.md`** (Repo-Root). Codex kennt AGENTS.md und fährt den CI-Loop selbst. *(Aktualisiert 2026-07-07 nach Rechner-Wechsel; die frühere parametrisierte Form galt für den alten Rechner.)*
- **Sonar-Host:** `localhost:9901` (Docker-Container `seu-sonarqube`). Der alte Rechner adressierte denselben Host über die LAN-IP `192.168.0.20`; portabel ist `localhost`. Gate muss OK sein: 0 violations / 0 critical / 0 hotspots, coverage ≥ 85 %.
- **git-Workflow:** Fix-/Close-Commits landen im etablierten Workflow **direkt auf `main`** (Worker pushen auf `main`). Vor Push `git fetch` + rebase auf aktuellen grünen `main`.
- **Concept-MCP** (`agentkit3-concepts`): `concept_search`/`concept_get`/`concept_glossary_search` statt grep über `concept/`. FK-/DK-/formal-Layer filterbar.

---

## 3. Guardrails (die wichtigsten — vollständig in `CLAUDE.md`)

ZERO DEBT (keine stillen Restlücken; Befunde explizit spiegeln) · FAIL-CLOSED · SINGLE SOURCE OF TRUTH · NO ERROR BYPASSING (keine Gate-Umgehung, kein LOC-Gate-Gaming via Shims/`# ruff: noqa`/Re-Export-Tricks) · **ARCH-55** (Code/Bezeichner/JSON-Keys/Kommentare **ausnahmslos Englisch**; nur deutschsprachige UI-Labels + Konzept-Prosa dürfen deutsch bleiben) · ARCH-02/04 (eine autoritative Stelle je Business-Regel) · ARCH-32 (CQS) · ARCH-43 (Timeouts an Distribution-Boundaries) · K5 (Control-Plane Postgres-only) · Blutgruppen A/R/T/0 (`concept/methodology/software-blutgruppen.md`). Mocks/Stubs nur im engen Ausnahmefall.

---

## 4. Backlog-Stand (bei Übergabe, gegen autoritative `status.yaml` abgeglichen)

- **145/159 completed.** Ketten AG3-001→147 im Wesentlichen geschlossen.
- **AG3-147 = completed** (siehe §5).
- **`ready` (sofort startbar):**
  - Ownership-Strang: **AG3-148** (kritischer Pfad), **AG3-152** (merge_local-Umzug), **AG3-156** (Verify-Evidenz-Ausführungsort). Alle depends_on jetzt completed.
  - Unabhängige Blätter (kein Ownership-Bezug): **AG3-131** (CCAG-Permission/Mode-Lock zentral), **AG3-132** (Backend-Erreichbarkeitsprüfung), **AG3-133** (LLM-Hub-Eval-Locus + Verify-Layer-2 produktiv), **AG3-134** (Skill-Bundle execute-userstory-core auf REST), **AG3-157** (Konzept-Referenz-Integritäts-Gate W1, entblockt 158→159→160).
- **blocked** (Deps offen): AG3-149→155 (Kette hinter 148), AG3-153/154/155.
- **131–134 sind VERIFIZIERT NICHT umgesetzt** (nicht Status-Drift) — read-only geprüft am 2026-07-07: 0 Umsetzungs-Commits, IST-Verletzung an jedem Locus präsent (131: lokale SQLite-Owner `ccag/requests.py:111`+`ccag/leases.py:81`, kein Postgres-Owner; 132: Installer instanziiert Sonar/Jenkins dev-seitig `cli/main.py:604/636`; 133: direkte Dev→Hub-Kanten `runtime_factory.py:221`, Layer-2 FailClosedLlmClient-Stub `composition_root.py:1105`; 134: SKILL.md 4.0.0 unmigriert). `ready` ist korrekt, `completed` wäre falsch. → **echte Arbeit**, kein Schnell-Close.

**Empfohlene Reihenfolge:** Kritischer Pfad zuerst — **147✅ → 148 → 149 → 150 → 151 → 153 → 154 → 155**, mit **152 und 156 parallel** (nur an 145/147 bzw. 144/145 gehängt). Blätter (157 zuerst, dann 131/132/133/134) als Füllmaterial, wenn der kritische Pfad wartet. Wegen der seriellen Checkout-Realität (§1) faktisch trotzdem ein write-Worker nach dem anderen.

---

## 5. AG3-147 — Abschluss & hinterlassene Restbefunde (Kontext für Folgearbeit)

**Story:** Sync-Punkte + Push-Gate + Ref-Schutz, „pushed-only-Durchsetzung": *Was nicht auf den Story-Branch committet UND gepusht ist, existiert für AgentKit nicht.* Zweistufige Barriere (Edge-`sync_push`-Report ∧ backend-eigener `ls-remote` Ref-Read) an vier Grenztypen (phase-completion, QA-cycle-boundary, yield-point, closure-entry).

**Verlauf (Kurzfassung der Saga):** Die ursprüngliche Barriere war ein **synchrones Prädikat über „running-latest push-freshness"** → oszillierte über **4 Review-Runden** zwischen fail-open (stale A==A passt) und Deadlock. Root-Cause war ein **Konzept-Verstoß** (FK-10 §10.2.4b: „Frische = Information, nie Entscheidung") + Timing-Mismatch (synchron über asynchrone Push-Evidenz). Nach Eskalation an den PO **Redesign** (design-review-first, SOUND): **Boundary-Lifecycle** (boundary_id/epoch, Mutations-Invalidierung), **V1-gehärteter Edge-Executor** (`rev-parse HEAD` unmittelbar vor Push, Push genau dieses H, Post-Push-Recheck), **persistierter `PushBarrierVerdict` als SSOT** (Postgres/K5, Konsumenten lesen nur), Supersede-/Late-Result-Fence, Closure-Entry ≠ Pre-Merge. Design-Dokumente im **AG3-147-Ordner**: `soll-prozess-push-barriere.md` (Rev.2), `konzept-korrektur-fk10-10.2.4b.md` (Rev.2).

**Letzte Runde (der Grund, warum 147 so lange lief):** Ein Review-Fund zeigte, dass die mechanisch korrekte commit-Invalidierung zwar verdrahtet war, aber die **Claude-Hook-Settings in der falschen Form** geschrieben/ausgeliefert wurden — **flach** `{matcher, command}` statt der von echtem Claude Code geforderten **dreistufigen** Form `hooks → event[] → {matcher, hooks:[{type:"command", command}]}` (verifiziert gegen https://code.claude.com/docs/en/hooks + PO-Praxis-Fehlermeldungen). In einer echten Claude-Installation feuerte damit **kein AK3-Hook** → die Durchsetzung war produktiv inert. **Gefixt** in `be1c364f` (Writer + Bundle + detach-Roundtrip + idempotente Upgrade-Migration + FK-30 §30.3.1/FK-76/FK-31 + Contract-Test + ARCH-55/ARCH-43). Jenkins **#1090 SUCCESS**, Sonar OK (0/0/0, cov 85.0%). Doppel-Review (Codex + Fable) **APPROVED**, 7/7 PASS. Close-Commit **`56a134df`**.

**Offene Minor-Härtungs-Kandidaten (dokumentiert, non-blocking — Kandidaten für eine Folge-/Härtungs-Story, NICHT stillschweigend liegen lassen):**
- **LOW** — detach eines **nie-migrierten** Legacy-Installs (flache AK3-Einträge auf Platte, ohne vorherige Upgrade-Migration) lässt diese inerten flachen Einträge stehen (`installer/lifecycle/detach.py:263`). Fail-safe (kein Datenverlust, kein *ausführbarer* Handler überlebt), aber verletzt den „removes all AK3 bindings"-Vollständigkeitsanspruch. Fix = ein Guard in `_strip_hook_matcher_groups`, der auch dict-Einträge mit top-level `command`, die `_is_ak3_hook_command` erfüllen, strippt.
- **trivial** — `normalize_claude_hooks_section`-Konsolidierung bei pathologischem Sibling-Group-Input; `_merge_handler` re-stampt `type:"command"`.
- **WARNING (out-of-scope aus dem 147-Feature)** — (a) fail-soft Telemetrie-Delivery kann **eine** Invalidierung an einem Zwischen-Wartepunkt still verschlucken (mitigiert: jeder spätere Boundary ist eigene Instanz mit frischem Push+Server-Read; ungepushte Arbeit erreicht Merge nicht); (b) **cwd-shift/cross-repo HEAD-Delta-Blindfleck**: `cd ../other && git commit` oder trailing-`cd`-Compounds werden von der HEAD-Delta-Beobachtung nicht erfasst.

---

## 6. Was in dieser Übergabe-Session zusätzlich passiert ist

- AG3-147 formal geschlossen: `status.yaml` → completed (`56a134df`).
- **Backlog-Drift bereinigt** (`7ca17bad`): README-Snapshot hing der Realität hinterher — AG3-144 (arch-blocked→**completed** 07-05) und AG3-145 (ready→**completed**) waren stale; die durch 144/145/147-Close entblockten **AG3-148/152/156** von `blocked`→`ready` gezogen (status.yaml **und** Snapshot), „Sofort startbar"-Zeile + überholten 144-Prosa-Block korrigiert. Alles gegen die autoritative `status.yaml` abgeglichen.
- Read-only verifiziert, dass **131–134 echt offen** sind (siehe §4).

---

## 7. Startklare Worker-Aufträge (aus dem session-lokalen Scratchpad hierher gerettet)

> Diese Aufträge basieren auf read-only Feasibility-Analysen (Ist-Delta, Konzept-Anker, Andockpunkte, Risiken). Verbatim an Codex geben (`submit`, `write:true`). Der Scratchpad überlebt den Rechnerwechsel nicht — deshalb hier eingebettet.

### 7a. AG3-148 — Ownership-Transfer-Kern (Challenge-Confirm-CAS) — KRITISCHER PFAD

```
Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.

Story: AG3-148 — Ownership-Transfer-Kern (Challenge-Confirm-CAS). Vollständiger Scope aus
stories/AG3-148-ownership-transfer-core/story.md (AC 1–17, Scope 1–11, K5/Blutgruppen).
VORBEDINGUNG: AG3-147 ist completed (erfüllt). Du OWNST die Schleife bis grün-auf-main:
implement → lokale Gates (ruff/mypy(+--platform linux)/pytest -n0, Coverage ≥85, 4 Konzept-Gates)
→ push main → Jenkins SUCCESS → Sonar-Gate grün (0/0/0, cov ≥85) → bei rot in-Code remediieren →
nur zurück wenn wirklich grün. Suiten >20min → command-timeouts ≥2400s. Kein Bypass, kein LOC-Gaming.

Modus: Worker. Blutgruppen strikt: A-Kern (ownership_transfer.py) AT-frei; R = Wire-/SSE-/Event-Mapper;
AT/T = transaktionale Vollzugs-Row-Funktion im state_backend.

Konzept-Anker (nicht abweichen): FK-56 §56.13/§56.13a-c/§56.13e (Challenge-Inhalt, Begründungspflicht,
Confirm=CAS, Befristung=Verfall, agent→human-approval, atomarer Vollzug, Transfer-Record als einziges
Übergabeobjekt, Immobilität, worktree_roots=Edge-Pfade B). FK-91 §91.1a (Endpoints takeover-request/-confirm),
Rule 5/8/13/18, §91.8 governance-Topic. FK-55 §55.5 (admin_transition). FK-17 §17.2c/§17.3a.15-16/§17.5/§17.7.
formal.operating-modes.commands/events/invariants, formal.state-storage.entity.takeover-transfer-record,
formal.frontend-contracts.event.takeover_approval_changed.

Umzusetzen (Reihenfolge):
1. A-core control_plane/ownership_transfer.py (neu): Challenge-Modell+Assembler (AC1-Felder),
   Confirm-CAS-Entscheidung (Echo vs owner_session_id/ownership_epoch/binding_version), Approval-Lifecycle
   (pending/approved/denied/expired), Invalidierungsregeln (Transfer/Exit/Reset/Split/Closure),
   Verlustkorridor-Pflichttext (maschinenadressierbar, englische Keys). Pure Funktionen über injizierte Ports.
2. Records (records.py): TakeoverApprovalRecord (+ ggf. TakeoverChallengeRecord) mit __post_init__.
   TakeoverTransferRecord NUR konsumieren (existiert bereits, alle Zielfelder vorhanden).
3. Schema/Store: additive `takeover_approvals`-Tabelle (K5, Postgres-only, _require_postgres_control_plane_backend-
   Muster) + Repo-Funktionen; EINE transaktionale Row-Funktion commit_takeover_confirm_global(...):
   Record-CAS(B, epoch+1, bleibt active) + A-Bindung-Revoke(ownership_transferred) + B-Bindung(gleicher run_id,
   neue binding_version, Edge-Roots) + Edge-Tombstone(A) + Blocker takeover_reconcile_required + Transfer-Record
   je Repo + 4 Events — EIN Commit, CAS-Verlust=kein Write.
4. Wire (models.py): TakeoverRequest (reason Pflicht, op_id min_length=1, KEIN default_factory), TakeoverChallenge,
   TakeoverChallengeEcho, PendingHumanApprovalResponse, Approval-Wire-Form, 4 Event-Payloads, takeover_approval_changed.
5. Runtime (runtime.py): Request-Handler (Mensch→Challenge/offered; Agent→pending_human_approval + Approval-Insert;
   Serialisierung via acquire_story_claim auf (project_key, story_id)); Confirm-Handler (Attestierung→CAS→
   commit_takeover_confirm_global); Historien-/Challenge-Query aus Owner-BC + AG3-147-Frische. NEUE BLÖCKE SEPARAT,
   nicht in bestehende push-Funktionen einflechten (runtime.py ist der größte Merge-Hotspot mit dem 147-Code).
6. HTTP (control_plane_http/app.py, dispatch.py): Routen POST …/ownership/takeover-request + …/takeover-confirm
   (Project-Edge-Gruppe); eigene Result-Response analog _edge_command_result_response mit pending_human_approval-
   Mapping; _mutation_result_response NICHT umbauen.
7. Attestierung (auth/middleware.py, minimal): menschliche BFF-Session vs Agent-Pfad für Ownership-Endpoints;
   Agent-Confirm→403 fail-closed.
8. SSE (telemetry/sse_stream.py): governance-Topic-Inhalt (ausstehende Freigaben + takeover_approval_changed).

Kopplungs-Gebote (nicht raten): takeover_base_sha AUSSCHLIESSLICH aus verifiziertem gepushtem Head (AG3-147
PushBarrierVerdict.expected_head_sha / verifizierte Ref) — nie lokaler Stand, nie Read-Model. Challenge-Frische
je Repo aus PushFreshnessRecord. Gegen A-core-Typen (push_sync.py) + Store-Facade programmieren, NICHT gegen
push_barrier_lifecycle.py-Helfer. Takeover = In-Place-CAS auf derselben Row → Record bleibt active,
OwnershipStatus.TRANSFERRED NICHT setzen. Kein Snapshot-Code.

Tests (Pflicht): Unit über Ports/Fakes (Assembler/CAS/Approval/Attestierung/Invalidierung). Postgres-Integration:
E2E-Transfer über echten AG3-142-Setup-Pfad (kein präparierter Record), Concurrency-Confirm-Rennen (genau einer
gewinnt, Verlierer kein Write), Approval-Verfall, Neustart-Persistenz, Serialisierung hinter Mutation,
Atomicity-Negativpfad JE Einzelschritt (Fehlerinjektion→kein Teilzustand), pushed-only fail-closed, Immobilität,
Blocker-Negativpfad, E2E-Regression AC15 (Ex-Owner-Mutation→409/403+ownership_transferred, Reads bleiben A erlaubt).
Contract-Pins: Challenge-Form (inkl Pflichttext + SHA/Frische je Repo), pending_human_approval, 4 Events,
takeover_approval_changed, Approval-Statusformen.

Vorhandene Fundamente (nur konsumieren): control_plane/records.py (RunOwnershipRecord, SessionRunBindingRecord,
TakeoverTransferRecord), control_plane/ownership.py (OwnershipStatus/Acquisition/BindingRevocationReason),
control_plane/ownership_fence.py (AG3-142 evaluate_ownership_admission, ERROR_CODE_OWNERSHIP_TRANSFERRED),
control_plane/object_claims.py (AG3-141 acquire_story_claim, STORY_SCOPE), push_sync.py/push_verification.py
(AG3-147 PushBarrierVerdict/PushFreshnessRecord/official_story_ref), store/_public_api_names.py (Facade-Funktionen).
postgres_schema.sql hat takeover_transfer_records bereits; KEINE Approval-Tabelle.

Merge-Hotspots mit 147-Code (heute geändert): runtime.py (größter — neue Handler in abgegrenzte Blöcke),
push_barrier_lifecycle.py (NUR lesen), models.py/schema/store/facade/_public_api_names.py/mappers.py (additiv;
_public_api_names.py LOC-budgetiert), app.py/dispatch.py (additive Routen), sse_stream.py (nur governance-Inhalt).
Vor Push rebase auf aktuellen grünen main.

DoD/Rückgabe (nur wenn main grün): Final-SHA, Jenkins#/Result, Sonar-Gate+cov%, Diff-Summary je AC-Cluster,
Belege für AC5/7/9/11/12 (Concurrency, Atomicity, pushed-only, Attestierung, kein Automatik-Pfad). status.yaml→completed,
README-Backlog-Snapshot nachziehen. Bei Konzept-Konflikt oder echter Design-Ambiguität → STOPP + melden, nicht raten.
```

### 7b. AG3-157 — Konzept-Referenz-Integritäts-Gate (W1) — unabhängiges Blatt, entblockt 158→159→160

```
Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.

Implementiere AG3-157 vollständig (stories/AG3-157-concept-reference-integrity-gate/story.md, alle 9 AC + DoD)
bis grün-auf-main, inkl. des neuen Gates selbst grün in CI. Du OWNST die Schleife bis grün-auf-main. Kein Bypass, kein LOC-Gaming.

VERBINDLICHE DESIGN-ENTSCHEIDUNGEN (nicht neu verhandeln):
1. Dateien: scripts/ci/check_concept_reference_integrity.py (Entry-Point, Bootstrap-Muster wie
   scripts/ci/compile_formal_specs.py: REPO_ROOT/SRC_ROOT/TOOLS_ROOT sys.path, AgentKitError-Subklasse fangen →
   stderr+exit 1) + tools/concept_compiler/reference_integrity.py (Kernlogik, eigene Exception
   ReferenceIntegrityError(AgentKitError)). KEIN Umbau von drift.py / check_concept_frontmatter.py — nur Ergänzung.
2. Korpus-Walk rekursiv (rglob) über concept/domain-design, concept/technical-design (inkl. _meta/** und
   _meta/decisions/**), concept/formal-spec (Prosa, nicht die FORMAL-SPEC-YAML-Blöcke).
3. Vier Verweisklassen, je ERROR bei Nichtauflösung: a) Doc-IDs (FK-NN/DK-NN/META-*/Decision-Record-IDs) gegen
   Bestand (Registry aus concept_id-Frontmatter, NICHT regex-raten); b) "<DOC-ID> §<anchor>" gegen die ECHTEN
   Überschriften des Zieldoks (Heading "## <anchor> <titel>", H2/H3-Sektionsebene wie 71_*.md "## 71.3 ...");
   c) formal.*-IDs gegen compile_formal_specs(root).declared_ids (tools/concept_compiler/compiler.py) — Compile
   zuerst, Ergebnis durchreichen, KEINE zweite Parselogik; d) Backtick-Dateipfade in Prosa gegen das Dateisystem.
4. Abgrenzung (deterministisch, im Docstring dokumentieren): Fenced Code-Blocks vor Extraktion entfernen;
   explizite Ausnahme per HTML-Kommentar `<!-- REF-CHECK:ignore -->` (nur expliziter Marker zählt, keine Heuristik).
   BEKANNT ZU BEHEBEN: concept/_meta/konzept-konsistenz-governance.md ~Z.120 ("FK-71 §67.x") und ~Z.225 ("FK-02
   §67.x") sind ABSICHTLICH tote didaktische Beispiele → Ignore-Marker setzen (minimaler nicht-normativer Edit).
   Vorher Korpus nach weiteren Absichts-Beispielen grep'en und ebenso markieren.
5. defers_to-Zusatzauftrag: Scope-Delegationsgraph aus Frontmatter defers_to (target+scope) + authority_over-Scopes
   ALLER Korpus-Dokumente (nicht domain-registry.yaml). Zyklendetektion pro Scope (DFS analog
   lint_l9_authority_graph_acyclic, auf gleichen Scope gefiltert) → ERROR. Separat: Dokumentebenen-Zyklen (ohne
   Scope-Filter) → Report + Baseline unter concept/_meta/ (jeder Eintrag MUSS "reason" tragen; Eintrag ohne reason
   lässt das Gate selbst fehlschlagen). Baseline muss FK-63<->FK-70, FK-02<->FK-71 + transitive Schleifen über
   FK-20/27/29/54 abdecken.
6. Jenkinsfile: neue Stage "Concept Reference Integrity" direkt nach "Concept Contract Checks" (ca. Z.275-289),
   IDENTISCHES when{}-Gate + dir('agentkit-src')/.venv/PYTHONPATH=src-Muster, Aufruf
   `python scripts/ci/check_concept_reference_integrity.py`.
7. Fixtures/Tests: tests/unit/tools/concept_compiler/test_reference_integrity.py + tests/fixtures/concept_compiler/
   <name>/concept/... (Muster wie concept_classification_missing in test_drift.py). Pflicht: 4 Verweisklassen
   negativ+positiv, gepinnter "FK-71 §67.3 tot / §71.3 löst auf" wörtlich, ein Fund in _meta-Fixture, ein
   Scope-Delegationszyklus (inkl. transitiv), ein Dokumentebenen-Zyklus MIT und einer OHNE Begründung, ein
   Determinismus-Test (zwei Läufe → identische Befundliste/Reihenfolge). Regressionsbeleg: die 4 Bestandsgates
   unverändert grün mitlaufen lassen.
8. Reihenfolge für ersten grünen main-Lauf: ERST Gate an Fixtures fertig + lokal trocken auf realem Korpus laufen,
   ALLE echten Befunde einzeln prüfen (Tippfehler→minimaler Fix; Dokumentebenen-Zyklen→Baseline mit Begründung;
   Lehrbeispiele→Ignore-Marker). ERST DANN Jenkinsfile-Stage einhängen. Kein Schritt überspringen.

Loop: venv-Prefix Pflicht, lokale Gates (ruff/mypy/pytest, Coverage ≥85, alle 4 Konzept-Gates + das neue Gate),
Suiten >20min → timeouts ≥2400s. ARCH-55 (Englisch). Nach lokal grün: push main, Jenkins SUCCESS + Sonar grün.
Kein Datei-Overlap mit dem Ownership-Strang erwartet (157 = scripts/ci + tools/concept_compiler + Jenkinsfile +
concept/). Rückgabe nur wenn main grün: Final-SHA, Jenkins#, Sonar-Gate+cov%, Diff je AC, gesetzte Ignore-Marker/
Baseline-Einträge. Bei echter Ambiguität → STOPP + melden.
```

> Für 131/132/133/134 liegen noch keine ausgearbeiteten Aufträge vor — vor Start je eine read-only Feasibility
> (Ist-Delta, Konzept-Anker, Andockpunkt, Test-Pflichten) fahren, damit der Codex-Lauf oszillationsfrei durchgeht.

---

## 8. Reviewer-Einordnung (Erfahrung aus der Vorsession)

- **Codex:** scharf, entscheidungsfreudig bei funktionaler Korrektheit/Ordering; der jetzt maßgebliche Reviewer.
- **Fable:** war der tiefste Reviewer (fand die Hook-Settings-Form-Fehlerklasse) — **ab jetzt per PO-Anweisung nicht mehr einsetzen.**
- **GLM:** einmal kostspieliger False-APPROVE (stale-evidence übersehen). Wenn eingesetzt: misstrauisch adjudizieren.
- **Grundregel:** Bei Reviewer-Split oder Verdacht → **selbst den Code lesen** und entscheiden. „CI-grün" ≠ „feature-complete" (bei 147 injizierten Unit-Tests Fake-Verdikte an genau den unverdrahteten Nähten → grün, aber kaputt).
