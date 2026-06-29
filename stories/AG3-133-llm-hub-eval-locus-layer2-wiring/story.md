# AG3-133: LLM-Hub-Eval-Locus in den Kern + produktive Verify-Layer-2-Anbindung (I2)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `story-creation` (Conflict-Adjudication) + `verify-system` (QA-Subflow Layer 2) + `implementation`/Worker-Health, querschnittlich gegen die Multi-LLM-Hub-Foundation (`integration_clients/multi_llm_hub`). Fachlich geht es um den **Ausfuehrungsort kanonischer LLM-Bewertungs-/Adjudication-Vorgaenge**: AK3 darf den Hub nur ueber den FK-75-REST-Adapter und nur **vom Kern getrieben** nutzen; dev-seitige/in-process-Hub-Evals sind eine direkte Dev→Hub-Kante und damit ein I2-Verstoss. Zusaetzlich ist Verify-Layer-2 heute produktiv inaktiv (Fail-Closed-Stub-Default) und muss real angebunden werden.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.4` — LLM-Nutzung ueber den LLM-Hub (Unified REST): „AK3 nutzt den LLM-Hub ausschliesslich ueber den FK-75-REST-Adapter." Der Hub wird fuer kanonische AK3-Bewertungs-/Adjudication-Vorgaenge **vom AK3-Kern** ueber REST getrieben (I2); **„Es gibt keine direkte Dev→Hub-Kante"**. Ausdruecklich genannte LLM-getriebene AK3-Fachlogik ueber genau diesen Pfad: **QA-Schicht-2-Bewertungen, Conflict-Adjudication, Governance-Adjudikator, Exploration-Fine-Design** (zentral auditierbar).
- `FK-10 §10.1.0` — Invariante **I2** (Drittsystem-Hoheit, Hub als Drittsystem-Werkzeug, vom Kern getrieben; fail-closed).
- `FK-11 §11.2` (LLM-Hub-Abstraktion) — §11.2.1: AK3 nutzt LLMs als **Bewertungs-, Review- und Adjudication-Funktion**; der technische Zugriff laeuft immer ueber den FK-75-REST-Adapter (`LlmEvaluator`). §11.2.3: fachlicher LLM-Aufruf + fail-closed-Fehlerbehandlung (Auth/Timeout/Adapterfehler). `FK-11 §11.5.1` (`StructuredEvaluator`, CheckResult-basiert) und `§11.5.2` (`DialogueRunner`) — die konkreten Eval-Bauformen hinter Layer-2/Conflict-Adjudication.
- `FK-75 §75.1 / §75.3 / §75.5` — Multi-LLM-Hub ist Foundation-Adapter (Bluttyp R); FK-75 ist die **einzige** normative Hub-Zugriffsquelle. `/v1/hub/*` ist die AK3-Adapter-/Cockpit-Surface (FK-75 §75.5, Frontend-Sicht §75.7), **kein** Eval-Gateway. Der **Transport** (`HubClient`) ist konform.
- `FK-27 §27.5 / §27.6a`, `FK-34` — Verify-Layer-2 (LLM-Evaluations) im QA-Subflow; `FK-35 §35.2` — Integrity-Gate prueft Vorhandensein der Layer-2-Artefakte.

---

## 1. Kontext / Ist-Zustand (belegt)

Der **Transport** ist konform (`HubClient` *ist* der FK-75-Adapter, `src/agentkit/integration_clients/multi_llm_hub/`); der Verstoss ist der **Ausfuehrungsort**:

- **C1 — Story-Creation Conflict-Adjudication (direkte Dev→Hub-Kante):**
  `src/agentkit/backend/story_creation/runtime_factory.py:221` — `hub = HubClient(load_multi_llm_hub_config().base_url)` (Import `:218`), getrieben aus dem dev-seitigen CLI-Story-Creation-Prozess. Kanonische Adjudication laeuft dev-seitig statt im Kern → I2-Verstoss (FK-10 §10.1.4).
- **C3 — Worker-Health-Sidecar (direkte Dev→Hub-Kante):**
  `src/agentkit/backend/implementation/worker_health/sidecar.py:48` — `self._hub_client = hub_client or HubClient(config.base_url)` (Import `:23`), gestartet als dev-seitiger Sidecar-Prozess via CLI `watch-worker`. Health-Assessment-Hub-Aufruf am Kern vorbei → I2-Verstoss.
- **C5 — Verify-Layer-2 nicht produktiv verdrahtet (PO-Mandat):**
  `src/agentkit/backend/bootstrap/composition_root.py:1128` — `resolved_llm_client = layer2_llm_client or FailClosedLlmClient()` in `build_verify_system` (`:1048`). Default ist der Fail-Closed-Stub; ohne realen `HubLlmClient` faellt jeder Layer-2-`complete`-Aufruf fail-closed → Layer 2 ist **produktiv inaktiv** (drei parallele LLM-Evaluations laufen nicht produktiv). Laut Docstring (`:1095`-`:1103`) ist das ein bewusster Zwischenstand bis zum FK-11-Pool-Adapter; **PO-Vorgabe: muss produktiv + fehlerfrei (fail-closed-korrekt) angebunden werden.**

- **C2 — Exploration-Fine-Design Hub-Eval-Locus:** `src/agentkit/backend/bootstrap/composition_root.py:839` (`HubClient(...)` im `build_exploration_drafting`-Pfad) ist eine weitere code-getriebene Hub-Bewertung. **Diese Story uebernimmt sie** (Owner-Konflikt aufgeloest, siehe §2.1.3b); die allgemeine Phase-Server-Ausfuehrung bleibt WP-D.

> Korrektur ggue. erster Kartenfassung: Verify-Layer-2 und der Governance-Adjudikator instanziieren `HubClient` **nicht** selbst (Port-Injektion, Fail-Closed-Default). Echte Dev→Hub-Kanten sind ausschliesslich C1 und C3.

> Hinweis: Alle `pfad:zeile` gegen aktuellen `main` re-verifiziert (Code unter `src/agentkit/backend/`). Vor Umsetzung erneut per Grep/Read bestaetigen.

## 2. Scope

### 2.1 In Scope

1. **C1 in den Kern verlagern:** die Story-Creation Conflict-Adjudication (`runtime_factory.py:221`) laeuft als kanonischer Bewertungsvorgang **kern-getrieben** ueber den FK-75-REST-Pfad; die direkte Dev→Hub-Kante aus dem CLI-Story-Creation-Prozess entfaellt. Der CLI-/Dev-Pfad ruft die Adjudication ueber den Kern an (REST), instanziiert selbst keinen `HubClient` mehr.
2. **C3 in den Kern verlagern:** das Worker-Health-Assessment (`sidecar.py:48`) wird **kern-getrieben**; der Hub-Aufruf wandert in den Kern. Ein verbleibender Sidecar bleibt ein duenner REST-Client des Kerns (kein eigener Hub-Edge). Die direkte Dev→Hub-Kante entfaellt.
3. **C5 — Verify-Layer-2 produktiv anbinden (eigene Arbeit dieser Story):** den Fail-Closed-Default in `build_verify_system` (`composition_root.py:1128`) durch einen **realen, produktiven `HubLlmClient`** ersetzen (der `HubLlmClient` existiert bereits in `verify_system/llm_evaluator/llm_client.py` als FK-75-Adapter-Wrapper). Layer 2 laeuft im Hauptpfad **produktiv** (drei parallele LLM-Evaluations) und bricht bei Hub-/Adapterfehlern **fail-closed-korrekt** ab (FK-11 §11.2.3, FK-34). **Klarstellung:** das Bauen/Verdrahten des `HubLlmClient` ist Arbeit **dieser** Story — AG3-129 liefert **nicht** den FK-11-Layer-2-Transport (AG3-129 = Hook/Worker-Health/Telemetrie-REST). Die FK-11-Rollen-Aufloesung (`llm_roles` → Hub-Modelle) wird aus der bestehenden Projekt-Config gelesen.
3b. **C2 — Exploration-Fine-Design Hub-Eval-Locus in den Kern:** der Hub-Eval-Aufruf in `composition_root.py:839` (`build_exploration_drafting`) ist — wie C1/C3 — eine code-getriebene Hub-Bewertung und wird **kern-getrieben** statt in-process. **Owner-Aufloesung (Codex-Befund):** AG3-125 schob C2 zu AG3-133, AG3-133 schob C2 zu AG3-125 — diese Story **uebernimmt den Hub-Eval-Locus von C2** (konsistent mit C1/C3); die allgemeine Server-Ausfuehrung der Exploration-Phase (Dispatch) bleibt WP-D (AG3-123/124). Kein Doppel-Owner mehr.
4. **Transport unveraendert:** der FK-75-Adapter (`HubClient`/`HubLlmClient`) bleibt der einzige Hub-Zugriff; kein Bypass am Adapter vorbei, keine modellindividuellen Endpunkte. Fail-closed-Fehlerbehandlung gemaess FK-11 §11.2.3.
5. **Negativpfad-/Locus-Tests:** (a) C1/C3 instanziieren keinen `HubClient` mehr dev-seitig (Architektur-/Import-Beleg, keine Dev→Hub-Kante); (b) Verify-Layer-2 laeuft mit realem `HubLlmClient` produktiv und bricht bei Adapterfehler fail-closed ab (kein stiller Skip, FK-34/FK-27 §27.5).

### 2.2 Out of Scope (mit Owner)

- **Allgemeine In-Process→Server-Verlagerung der Exploration-Phase (Dispatch/Capability)** — **AG3-123/AG3-124/AG3-125** (WP-D). Diese Story verlagert nur den **Hub-Eval-Locus** von C2, nicht die Phasen-Dispatch-Maschinerie.
- **FK-75-Adapter-Interna / Transport** (`integration_clients/multi_llm_hub`) — bereits konform; bleibt unveraendert.
- **`/v1/hub`-Cockpit-Surface** (FK-75 §75.5/§75.7) — Frontend-Lesesicht, **kein** Eval-Pfad; nicht beruehrt.
- **Governance-Adjudikator** — bereits port-injiziert mit Fail-Closed-Default (keine Dev→Hub-Kante); nicht Gegenstand dieser Story.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/story_creation/runtime_factory.py` (`:221`) | Aendern (C1 kern-getrieben; kein Dev-`HubClient`) |
| `src/agentkit/backend/implementation/worker_health/sidecar.py` (`:48`) | Aendern (C3 kern-getrieben; nur REST-Client) |
| `src/agentkit/backend/bootstrap/composition_root.py` (`:1128` C5, `:839` C2) | Aendern (produktiver `HubLlmClient` statt FailClosed; C2-Eval kern-getrieben) |
| `src/agentkit/backend/verify_system/llm_evaluator/llm_client.py` | Pruefen/Nutzen (bestehender `HubLlmClient`-Wrapper) |
| `src/agentkit/backend/control_plane_http/` (+ ggf. FK-91, falls neue Eval-Anforderungsroute) | Neu/Aendern |
| `tests/integration/verify_system/test_layer2_e2e.py`, `tests/integration/story_creation/**`, `tests/unit/**` | Neu/Aendern (Fake-Hub-e2e, Static-Import-Reachability, fail-closed) |

## 3. Akzeptanzkriterien

1. Die Story-Creation Conflict-Adjudication (C1) wird **kern-getrieben** ausgefuehrt; `story_creation/runtime_factory.py:221` instanziiert keinen `HubClient` mehr auf der Dev-Seite. **Statischer Import-Reachability-Check (kein Mock-only):** aus dem dev-/CLI-Story-Creation-Pfad ist **kein** `HubClient` mehr erreichbar (keine direkte Dev→Hub-Kante). Analog fuer C2 (`composition_root.py:839`) und C3.
2. Das Worker-Health-Assessment (C3) wird **kern-getrieben**; `implementation/worker_health/sidecar.py:48` haelt keinen direkten Hub-Edge mehr (ggf. nur noch REST-Client des Kerns). Belegt durch Test/Architektur-Check.
3. **Verify-Layer-2 laeuft produktiv:** `build_verify_system` verdrahtet im Hauptpfad einen realen `HubLlmClient` statt `FailClosedLlmClient`. **Echter e2e-Test gegen einen Fake-Hub-HTTP-Server (kein `FailClosedLlmClient`, kein Mock des Evaluators):** Layer 2 fuehrt die drei parallelen LLM-Evaluations produktiv aus und bricht bei Hub-/Adapterfehler **fail-closed** ab (kein stiller Skip, kein Rueckfall auf den Stub im Hauptpfad). Der bestehende `test_layer2_e2e.py`-Default, der `FailClosedLlmClient` assertet, wird auf den produktiven Pfad gezogen.
4. **Transport-Konformitaet:** der Hub-Zugriff laeuft ausschliesslich ueber den FK-75-Adapter; kein Bypass, kein modellindividueller Endpunkt (Architektur-Beleg).
5. **ARCH-55:** alle neuen Bezeichner/Routen/Wire-Keys englisch; keine unerklaerten `noqa`/`type: ignore`.
6. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest` (unit/integration/contract, `-n0`); Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–6 erfuellt; QA-Gate (Codex-Review) **PASS** + Standard-Pflichtbefehle + Remote-Gates (Jenkins + Sonar) gruen.
- Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Testnamen (C1/C3 kein Dev→Hub-Edge mehr; Layer-2 produktiv + fail-closed-korrekt).
- Implementierung/Commit erst nach Freigabe; `depends_on` (AG3-125, AG3-129) muessen `completed` sein.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** der **Ausfuehrungsort** wird korrigiert (Kern treibt die Evals), nicht der bereits konforme Transport. Keine zweite Hub-Zugriffsheimat.
- **SINGLE SOURCE OF TRUTH:** FK-75-Adapter ist der einzige Hub-Zugriff; keine parallele Dev→Hub-Kante bleibt erreichbar.
- **FAIL CLOSED:** Verify-Layer-2 bricht bei Hub-/Adapterfehler fail-closed ab; kein stiller Skip, kein Rueckfall auf den deterministischen Stub im Hauptpfad.
- **NO ERROR BYPASSING:** keine Umgehung des Kerns fuer kanonische Bewertungs-/Adjudication-Vorgaenge.
- **ARCH-55:** englische Bezeichner/Pfade/Keys.
- **GAC-2 / ARCH-NN:** Architektur-Guardrails verbindlich; `integration_clients/` bleiben duenne Adapter. Konflikt = hart stoppen und melden.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Drei Ist-Loci re-verifizieren (Zeilen koennen wandern): C1 `story_creation/runtime_factory.py:221`, C3 `implementation/worker_health/sidecar.py:48`, C5 `bootstrap/composition_root.py:1128` (`build_verify_system`).
- **Transport nicht anfassen:** `HubClient`/FK-75-Adapter bleibt; nur der **Locus** wandert in den Kern. Hub-Zugriff ausschliesslich ueber FK-75 (FK-10 §10.1.4 „keine direkte Dev→Hub-Kante").
- **Layer-2-Anbindung ist eigene Arbeit:** den bestehenden `HubLlmClient` (`verify_system/llm_evaluator/llm_client.py`, FK-75-Adapter-Wrapper) in `build_verify_system` produktiv verdrahten (statt `FailClosedLlmClient`-Default). AG3-129 liefert **nicht** diesen Transport; nicht darauf warten.
- **C2 (`composition_root.py:839`) GEHOERT zu dieser Story** (Hub-Eval-Locus). Nur die allgemeine Exploration-Phase-Dispatch-Verlagerung bleibt WP-D (AG3-123/124).
- `/v1/hub` ist Frontend-Cockpit (FK-75 §75.5/§75.7), kein Eval-Gateway — nicht als Eval-Pfad missbrauchen.
- Kein Commit ohne Auftrag; „done" nur mit Beleg (Diff, Tests, gruene Pflichtbefehle).

## 7. Vorbedingungen

- `depends_on`: **AG3-125** (Kern-seitige In-Process→Server-Mediation der verify/closure-Capability — Aufsatzpunkt fuer kern-getriebene C1/C2/C3-Evals) **und** **AG3-129** (Worker-Health-REST-Mediation — Fundament fuer den C3-Locus; liefert **nicht** den Layer-2-`HubLlmClient`). Beide `completed`-Pflicht; solange offen: `status: blocked`.
- `unblocks`: keine.
- Konzept-Aenderung minimal: ggf. FK-91/Formal-Contract fuer eine kern-seitige Eval-Anforderungsroute (C1/C3), falls eine neue Route noetig ist; sonst keine `concept/`-Aenderung. Bei FK-Aenderung Konzept-Gates mitziehen.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
