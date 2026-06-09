# AG3-103: Konzept-Nachzug — Schema-Katalog-Realitaet + Defaults/Schwellwerte + interne FK-Widersprueche

**Typ:** Concept (doc-only)
**Groesse:** M
**Bounded Context:** querschnittlich — `artifacts`/Config (Schema-Katalog FK-90), `governance-and-guards` (Defaults FK-93), `verify-system`/`failure-corpus`/LLM-Pools (Defaults FK-93), `telemetry-and-events` (Event-Katalog FK-68), Foundation-Prosa (FK-01/FK-02), API-Katalog (FK-91). FK-Prosa an die bewusste Pydantic+Contract-Test-Realitaet und die realen Defaults angleichen; interne FK-Widersprueche aufloesen. **Doc-only bedeutet hier: ausschliesslich `concept/`-Prosa wird geaendert (das IST die Lieferung); kein `src/`-/`tests/`-Diff.**
**Quell-Konzepte (autoritativ):**
- `FK-90 §90.1/§90.2` — JSON-Schema-Datei-Katalog (`{stage_id}.schema.json`, ~40 Eintraege; `concept/technical-design/90_schema_katalog.md:33`, `:52-70`, `:90-94`)
- `FK-93 §93.3/§93.5/§93.5a/§93.7/§93.11` — VektorDB-/Governance-/Permission-/LLM-Pool-/Failure-Corpus-Defaults (`concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`)
- `FK-01 §1.6` — Tech-Stack-Tabelle (PostgreSQL vs. "JSONL"/"JSON" interner Widerspruch)
- `FK-02 §2.3.1` — Adversarial-Sandbox `_temp/adversarial/{story_id}/`
- `FK-91 §91.1a` — Planning-Endpunkt-Pfade (vs. FK-72 §72.8.2)
- `FK-72 §72.8.2` — KPI-Modul-Mount (`72_frontend_architektur.md:222`); KPI-Root-Prosa `/kpis` -> `/kpi` (PO-Entscheidung 2026-06-08, Singular; FK-63/AG3-084/AG3-094 sind deckungsgleich)
- `FK-68 §68.2` — Event-Typ-Katalog (Glossar `event-type-id` value-Liste)
- `FK-68 §68.2.2` — Event-Katalog Payload-Field-Row `review_divergence` (Tabelle „Review-Divergenz", `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md:358-362` — abgeloeste `score`/`routing`-Form)
- `FK-34 §34.8.4` — autoritativer `review_divergence`-Feldsatz (`story_id`/`reviewer_a`/`reviewer_b`/`divergent`/`quorum_triggered`/`final_verdict`, `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md:570-582`)
- `concept/_meta/bc-cut-decisions.md` (AUTORITATIV: BC-Schnitt-Hoheiten, Zero-Debt-Policy `:46-50`, FK-68-`authority_over: eventing/telemetry` `:890`); `PROJECT_STRUCTURE.md`, `_STORY_INDEX.md` Schnitt-Frage 3

---

## 1. Kontext / Ist-Zustand (belegt)

**FK-90 (Schema-Katalog, ABWEICHEND durchgaengig):** Im gesamten Repo existiert **keine** `*.schema.json`-Datei (Glob `**/*.schema.json` -> leer). Schemas sind als Pydantic-v2-Modelle + Contract-Tests realisiert (`src/agentkit/artifacts/envelope.py`, `tests/contract/artifacts/test_envelope_schema.py`, `tests/contract/implementation/test_handover_schema.py`, `test_worker_manifest.py`). Das ist die gewollte v3-Linie (typisierte Modelle statt JSON-Wildwuchs); FK-90 §90.2 „Stage-ID = Dateiname" / `{stage_id}.schema.json` (`90_schema_katalog.md:90-94`) und der Datei-Katalog §90.1 (`:52-70`) treffen auf kein Artefakt zu. `_STORY_INDEX.md` Schnitt-Frage 3 bestaetigt: FK-90 bewusst durch Pydantic+Contract-Tests ersetzt; doc-only-Anteil hier.

**FK-93 (Defaults) — gemischter Befund, Owner pro Wert noetig:**
- §93.5a Permission-Request-TTL: FK sagt **1800s** + Config-Pfad `permissions.request_ttl_s` (`93_standardwerte_schwellwerte_timeouts.md:64`). Code-Default ist **600s** (`src/agentkit/governance/ccag/requests.py:42` `DEFAULT_TTL_SECONDS: int = 600`); der in FK deklarierte Config-Pfad `permissions.request_ttl_s` ist im Code **nicht implementiert** (kein Config-Modell-Feld). **Faktor-3-Drift — offen, ob Code auf 1800s oder FK auf 600s gezogen wird; PO-Klaerbedarf, nicht in dieser doc-only-Story entschieden.**
- §93.5/§93.6 Governance-Risikoscore (Schwelle 30, Window 50, Cooldown 300s, Punktevergabe): `src/agentkit/governance/governance_observer/__init__.py` ist **leer (0 Zeilen)**; Grep `risk_threshold|risk_score|window_size|cooldown_s` -> 0. Gesamte Sensorik FEHLT (Code).
- §93.7 LLM-Evaluator (Send-Timeout 2400s, Acquire-Retries 5, "fest im Code"): `src/agentkit/integrations/llm_pools/` ist nur leeres `__init__.py`; Konstanten fehlen (Code FEHLT).
- §93.3 VektorDB (Similarity 0.7, Max LLM-Kandidaten 5): keine Default-Konstanten; VektorDB Default-`false` (UNVOLLSTAENDIG, Code).
- §93.11 Failure-Corpus (Rework 30 Min, Promotion 3x/30 Tage, Deaktivierung 90 Tage / FP>3): `src/agentkit/failure_corpus/pattern.py` liefert laut Docstring (`:16-18`) nur Record + Repository-Skelett; Promotion-Logik/Schwellwerte fehlen (Code). **Zusatzbefund ARCH-55:** `PromotionRule`-Enum-Werte sind deutsch (`wiederholung`/`hohe_schwere`/`checkbarkeit`, `pattern.py:50-52`); ebenso `PatternRiskLevel` (`mittel`/`hoch`/`kritisch`, `pattern.py:58-60`).
- §93.2 Policy/Feedback (Major-Threshold 3, Max-Feedback-Runden 3): **konform** (`verify_system/remediation/loop_counter.py:40`, `policy_engine/engine.py:31`) — kein Nachzug.

**Interne FK-Widersprueche:**
- FK-01 §1.6: P8/§1.4 sagen PostgreSQL kanonisch, die Tech-Stack-Tabelle §1.6 listet "Telemetrie | JSONL | Dateisystem" und "QA-Artefakte | JSON | Dateisystem" — interner Widerspruch; der Code folgt der DB-Variante (`state_backend/postgres_store.py`, `sqlite_store.py`).
- FK-02 §2.3.1: Adversarial-Sandbox `_temp/adversarial/{story_id}/`; FK-10 §10.3.2 + CLAUDE.md **verbieten** `_temp/`-Zustandsverzeichnisse. Interner Konzept-Widerspruch FK-02 vs. FK-10.
- FK-91 §91.1a Planning-Pfade (`/v1/planning/*`, unscoped) kollidieren mit FK-72 §72.8.2 (projekt-skopiert); Code folgt FK-72 (`src/agentkit/execution_planning/http/routes.py:39-52`, `/v1/projects/{key}/planning/...`).
- FK-68 §68.2 Event-Glossar ist weder Ober- noch genaue Teilmenge des Code-Enums (`telemetry/events.py:18-103`): Code traegt Werte ohne FK-Eintrag (z.B. `llm_call_complete`, `review_guard_intervention`, `mandate_classification`), und die BC14/BC15-Werte fehlen im Code (letzteres ist Code-Scope AG3-081/AG3-099).
- **FK-68 §68.2.2 Payload-Field-Row `review_divergence` (Cross-Story-Luecke, AG3-066-Routing):** Die Event-Katalog-Tabelle „Review-Divergenz" (§68.2.2, `68_telemetrie_eventing_workflow_metriken.md:358-362`) listet fuer `review_divergence` noch die Zusatzfelder `reviewer_a`, `reviewer_b`, `score` (LOW/MEDIUM/HIGH), `routing`. **Diese Form ist mit dem aktuell real emittierten Code-Payload deckungsgleich:** der Hook emittiert heute `score=_SCORE_HIGH`/`routing="third_reviewer"` (`src/agentkit/telemetry/hooks/divergence_hook.py:93-94`); `score`/`routing` sind also (noch) **kein** stale-Code-Mismatch, sondern stehen der **autoritativen FK-34-Feldsatz-Definition** entgegen. FK-34 §34.8.4 (`34_llm_bewertungen_adversarial_testing_runtime.md:570-582`) traegt den autoritativen Feldsatz `story_id`, `reviewer_a`, `reviewer_b`, `divergent`, `quorum_triggered`, `final_verdict` und referenziert fuer das Schreiben des Events „Kap. 68" (`:573`). **AG3-066** (review-divergence/quorum, `type: Implementation`) besitzt laut Index-Cut die Telemetrie-Schema-Abloesung und stellt die **eine kanonische** Code-Payload end-to-end auf den FK-34-Feldsatz um (Hook, `MANDATORY_PAYLOAD_FIELDS`, Contract-Pin, Risk-Window-Excerpt) — **und routet die FK-68-PROSE-Angleichung explizit an AG3-103** (`stories/AG3-066-review-divergence-quorum/story.md:14`, `:32`, `:65`, „FK-Prosa-Angleichung an AG3-103 geroutet"). AG3-103s urspruenglicher Scope (Item 4, letzter Bullet) deckte nur die **Glossar**-value-Liste in §68.2 ab, **nicht** die §68.2.2-Payload-Field-Row — d.h. das AG3-066-Routing zeigte auf etwas, das AG3-103 noch nicht besass. Diese Story schliesst die Luecke (siehe `scope-extension-note.md`). Der korrekte Hoheits-Anker ist damit **FK-34 §34.8.4 + das AG3-066-Zielschema**, **nicht** „der aktuell emittierte Code-Payload" (der traegt heute noch `score`/`routing`).

## 2. Scope

### 2.1 In Scope (nur FK-Prosa; Owner pro Wert)

> **Doc-only-Klarstellung:** Die Lieferung dieser Story IST die `concept/`-Prosa-Aenderung an den unten genannten FK-Dokumenten. Es gibt **keinen** `src/`-/`tests/`-Diff. „Spiegeln/Routen" eines Code-Fixes bedeutet: in der FK-Prosa und im Out-of-Scope-Block die zustaendige Code-Story benennen, **ohne** hier Code zu aendern und **ohne** den Code-Wert eigenmaechtig festzulegen.

1. **FK-90 §90.1/§90.2** umschreiben auf die Pydantic-Owner-+-Contract-Test-Realitaet (typisierte Modelle als Schema-Owner, Contract-Tests als Stabilitaetsanker statt `{stage_id}.schema.json`-Dateien); das Namensmuster „Stage-ID = Dateiname" (`90_schema_katalog.md:90-94`) und den Datei-Katalog §90.1 entfernen/umschreiben. **Owner: Code/v3-Linie autoritativ, FK zieht nach** (PO-Frage 3 ist auf doc-only entschieden).
2. **FK-93-Defaults mit Code abgleichen, Owner pro Wert benennen:**
   - **§93.5a Permission-TTL (offen!):** FK 1800s (`93_standardwerte_schwellwerte_timeouts.md:64`) vs. Code 600s (`requests.py:42`) -> **Owner-Entscheidung pro Wert als offener PO-Klaerbedarf in der FK-Prosa markieren:** entweder FK auf 600s nachziehen ODER Code auf 1800s aendern. Da das ein **reiner Code-/Config-Wert-Fix** waere, an die zustaendige Code-Story spiegeln: **AG3-086** (Hook-/Guard-/CCAG-Vollausbau, TTL->ESCALATED; Owner des `DEFAULT_TTL_SECONDS`-Werts) und **AG3-070** (Config-Pfad `permissions.request_ttl_s`). In dieser doc-only-Story den **PO-Klaerbedarf** (welcher Wert gilt) explizit benennen, **nicht** selbst einen Wert codieren oder in der FK festschreiben.
   - §93.5/§93.6, §93.7, §93.3, §93.11: als **noch-nicht-implementierte Defaults** kennzeichnen, Owner-Code-Stories benennen — Governance-Sensorik **AG3-085**, LLM-Pool-Timeouts **AG3-065**, VektorDB-Schwellen **AG3-068**, Failure-Corpus-Schwellen **AG3-078**. FK-93 bleibt normative Sollwert-Quelle; der Code zieht dort nach.
   - §93.2: als konform vermerken (kein Nachzug).
3. **ARCH-55-Code-Fix spiegeln (nicht hier codieren):** die deutschen `PromotionRule`-/`PatternRiskLevel`-Enum-Werte (`pattern.py:50-60`) sind ein reiner Code-Verstoss gegen ARCH-55. **An die zustaendige Code-Story AG3-078 spiegeln** (Failure-Corpus Stufe 2/3 / Pattern-Promotion). In dieser Story nur als Spiegel-Vermerk in der FK-Prosa/im Out-of-Scope-Block; **kein** Code-Diff. (Hinweis: AG3-104 fuehrt denselben Spiegel-Auftrag — Abstimmung: AG3-078 ist der eine Code-Owner; Doppel-Nennung ist nur Redundanz im Doku-Hinweis, kein zweiter Codefix.)
4. **Interne FK-Widersprueche aufloesen (FK-Prosa):**
   - FK-01 §1.6 Tech-Stack-Tabelle auf PostgreSQL-kanonisch korrigieren (JSONL/JSON-Dateisystem-Zeilen entfernen/anpassen), konsistent mit §1.4/P8 und FK-06-Wahrheitsgrenze. **Owner: Code/DB autoritativ.**
   - FK-02 §2.3.1 `_temp/adversarial/...` an FK-10-Verbot angleichen (Sandbox unter erlaubtem `var/`-/`tmp_path`-Pfad statt `_temp/`). **Owner: FK-10 + CLAUDE.md autoritativ; FK-02 zieht nach.**
   - FK-91 §91.1a Planning-Pfade auf die projekt-skopierte FK-72-Form angleichen (Inkonsistenz zugunsten FK-72/Code aufloesen). **Owner: FK-72/Code autoritativ.** Hinweis: die **fehlenden** Endpunkte (execution-input, Frontend-Read-Models) sind Code-Scope **AG3-091** — hier nur die Pfad-Konsistenz, nicht der Endpunkt-Bau.
   - **FK-72 §72.8.2 KPI-Modul-Mount `/kpis` -> `/kpi` angleichen (PO-Entscheidung 2026-06-08):** Der kanonische KPI-Routen-Root ist **Singular `/kpi/{dimension}`** (deckungsgleich FK-63 §63.4 `/api/kpi/*`, AG3-084 AC1, AG3-094). Die FK-72-§72.8.2-Prosa (`72_frontend_architektur.md:222`, Modul-Mount `/v1/projects/{key}/kpis`) ist hier der **Ausreisser** und wird auf `/kpi` korrigiert. **Owner: PO-Entscheidung autoritativ; FK-72-Prosa zieht nach.** FK-63 traegt bereits die Singular-Form (kein Nachzug noetig). Der erreichbare Pfad/Code ist AG3-090 (Mount) + AG3-084 (Endpoints) — hier nur die FK-72-Prosa-Zeile.
   - FK-68 §68.2 Glossar: die Glossar-value-Liste als nicht-deckungsgleich mit dem Code-Enum kennzeichnen und die Owner-Trennung dokumentieren (Code-Enum autoritativ fuer existierende Events; BC14/BC15-Werte als Code-Bedarf AG3-081/AG3-099). Reine Doku-Konsolidierung, keine Event-Implementierung.
   - **FK-68 §68.2.2 Payload-Field-Row `review_divergence` an FK-34 §34.8.4 + das AG3-066-Zielschema angleichen (AG3-066-Routing-Schliessung):** Die Event-Katalog-Zusatzfelder fuer `review_divergence` (Tabelle „Review-Divergenz", §68.2.2, `68_telemetrie_eventing_workflow_metriken.md:362`) werden in der FK-Prosa von der `score` (LOW/MEDIUM/HIGH)/`routing`-Form auf den **autoritativen** FK-34-§34.8.4-Feldsatz (`34_llm_bewertungen_adversarial_testing_runtime.md:580-582`) umgeschrieben: `story_id`, `reviewer_a`, `reviewer_b`, `divergent`, `quorum_triggered`, `final_verdict`. `score` und `routing` entfallen vollstaendig (kein paralleles Format). **Owner: FK-34 autoritativ; FK-68 zieht nach.** Die Begruendung ist **nicht** „der aktuell emittierte Code-Payload ist bereits FK-34-foermig" — das ist er **nicht** (Hook emittiert heute noch `score`/`routing`, `divergence_hook.py:93-94`). Die FK-68-Prosa wird auf **FK-34 §34.8.4 als autoritative Konzept-Quelle** und auf das **AG3-066-Zielschema** (das genau diesen Feldsatz end-to-end im Code herstellt) gezogen. **Sequenzierungs-Hinweis:** Die Code-Schema-Migration auf den FK-34-Feldsatz ist AG3-066; die hier gelieferte FK-68-Prosa-Angleichung ist der parallele Konzept-Nachzug auf dieselbe autoritative FK-34-Quelle (kein Build-Prerequisite zu AG3-066, siehe §2.2 und `scope-extension-note.md`).

### 2.2 Out of Scope (mit Owner)
- Governance-Sensorik-Code (AG3-085), LLM-Pool-Transport/Timeouts (AG3-065), VektorDB-Laufzeit (AG3-068), Failure-Corpus-Promotion + ARCH-55-Enum-Fix (AG3-078), Permission-TTL-Code-Wert (AG3-086) + Config-Pfad `permissions.request_ttl_s`/Config-Modell/`config_version`/Stanzas (AG3-070), BC14/BC15-Events (AG3-081/AG3-099), Execution-Input-/Read-Model-Endpunkte (AG3-091).
- **`review_divergence`-Code-Schema-Migration** (`score`/`routing` -> FK-34-Feldsatz im Hook/`events.py`/Contract-Pin/`normalizer.py`) — **AG3-066** (in-scope dort). Diese Story liefert nur die parallele FK-68-Prosa-Angleichung; **keine** harte `depends_on`-Kante (AG3-066 deklariert kein `depends_on: AG3-103`; beide ziehen unabhaengig auf die autoritative FK-34-Quelle, siehe Cross-Story-Voraussetzungen / `scope-extension-note.md`).
- Jegliche `src/`-/`tests/`-Aenderung.

## 3. Akzeptanzkriterien
1. FK-90 §90.1/§90.2 ist in `concept/technical-design/90_schema_katalog.md` auf die Pydantic-Owner-+-Contract-Test-Realitaet umgeschrieben; kein `{stage_id}.schema.json`-Datei-Katalog/„Stage-ID = Dateiname" verbleibt.
2. Jeder FK-93-Default-Wert ist mit Code abgeglichen und traegt in der FK-Prosa **Owner pro Wert**: konform / FK-Soll mit Code-Nachzug-Story / offener PO-Klaerbedarf (Permission-TTL 600 vs. 1800). Keine stillschweigende Behauptung „implementiert". Der Permission-TTL-Konflikt ist als offener PO-Klaerbedarf mit Code-/Config-Owner AG3-086/AG3-070 markiert; AG3-103 setzt **keinen** Wert.
3. Die deutschen `PromotionRule`/`PatternRiskLevel`-Enum-Werte sind als ARCH-55-Code-Fix an **AG3-078** gespiegelt (Vermerk in der FK-Prosa/Out-of-Scope), nicht hier codiert.
4. Die vier internen FK-Widersprueche (FK-01 §1.6, FK-02 §2.3.1, FK-91 §91.1a, FK-68 §68.2) sind in der FK-Prosa aufgeloest, jeweils mit benannter autoritativer Quelle.
4b. **FK-72 §72.8.2 KPI-Modul-Mount ist auf `/kpi` korrigiert** (`/kpis` -> `/kpi`, `72_frontend_architektur.md:222`); kein `/kpis` (Plural) verbleibt fuer den KPI-Root. Die Prosa ist deckungsgleich mit FK-63 §63.4 (`/kpi/*`), AG3-084 AC1 und AG3-094; benannte autoritative Quelle = PO-Entscheidung 2026-06-08 (Singular `/kpi/{dimension}`).
4a. **FK-68 §68.2.2 `review_divergence`-Payload-Field-Row ist auf den FK-34-§34.8.4-Feldsatz angeglichen:** die Event-Katalog-Zusatzfelder tragen **exakt** `story_id`, `reviewer_a`, `reviewer_b`, `divergent`, `quorum_triggered`, `final_verdict`; **kein** `score`/`routing` (LOW/MEDIUM/HIGH) verbleibt. Die autoritative Quelle in der Prosa ist als **FK-34 §34.8.4 + AG3-066-Zielschema** benannt (FK-68 zieht nach) — **nicht** als „aktuell emittierter Code-Payload" (der traegt heute noch `score`/`routing`). Damit ist das AG3-066-Routing der FK-68-PROSE-Angleichung erfuellt (kein verwaistes Cross-Story-Routing mehr).
5. Kein deutscher Code-Identifier/Key in der FK-Prosa eingefuehrt (ARCH-55).
6. **Konzept-Gates gruen + Frontmatter-Check gruen + KEIN `src/`-/`tests/`-Diff** (`git diff` zeigt nur `concept/`-Aenderungen — der `concept/`-Diff IST fuer diese doc-only-Story erwartet und gewollt).

## 4. Definition of Done
- AK 1-6 (inkl. 4a + 4b) erfuellt; giftige Codex-Review PASS; `concept/`-Prosa-Aenderung committed erst nach Execution-Plan-Freigabe (kein `src/`/`tests/`-Diff).

## 5. Guardrail-Referenzen
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** ein Schema-Owner (Pydantic) statt Datei-Katalog-Parallelwahrheit; ein Default-Wert pro Schwelle, klar verortet.
- **FAIL-CLOSED / SEVERITY:** offene Default-Drift (Permission-TTL 600 vs. 1800) ist ein aktiver Handlungsauftrag (PO-Klaerung), kein still liegengelassener Warning; AG3-103 entscheidet den Wert nicht.
- **ARCH-55:** deutsche Enum-Werte sind ein Code-Verstoss -> an AG3-078 gespiegelt, nicht in der FK kaschiert.
- **NO ERROR BYPASSING:** echte Code-Luecken (AG3-065/068/070/078/081/085/086/091/099) werden nicht in dieser doc-only-Story versteckt.
- **FK-PROSA FOLGT AUTORITATIVER KONZEPT-QUELLE (FK-68 §68.2.2):** der autoritative `review_divergence`-Feldsatz ist FK-34 §34.8.4; die FK-68-§68.2.2-Prosa wird darauf nachgezogen (`score`/`routing` -> FK-34-Feldsatz). Kein paralleles Divergenz-Format in der Prosa. Schliesst das AG3-066-Cross-Story-Routing (verwaistes Routing waere ein still liegengelassener Befund -> ZERO DEBT). Die Begruendung stuetzt sich auf FK-34 + das AG3-066-Zielschema, **nicht** auf den aktuell noch `score`/`routing` emittierenden Code (`divergence_hook.py:93-94`).

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Doc-only heisst hier: die `concept/`-FK-Dokumente WERDEN editiert (das ist die Lieferung).** Verboten ist ausschliesslich ein `src/`-/`tests/`-Diff. Editierte Dateien: `concept/technical-design/90_schema_katalog.md`, `93_standardwerte_schwellwerte_timeouts.md`, `01_*` (§1.6), `02_*` (§2.3.1), `91_*` (§91.1a), `68_telemetrie_eventing_workflow_metriken.md` (§68.2 + §68.2.2), `72_frontend_architektur.md` (**ausschliesslich** die §72.8.2 KPI-Mount-Zeile `:222`, `/kpis` -> `/kpi`). Keine anderen `concept/`-Dateien und **keine anderen FK-72-Stellen** anfassen (FK-34/FK-10 bleiben autoritative Quellen, nicht zu aendern; FK-72 ist autoritativ ausser der einen entschiedenen KPI-Mount-Zeile §72.8.2).
- Permission-TTL: NICHT eigenmaechtig einen Wert setzen — als offenen PO-Klaerbedarf in der FK-Prosa benennen und an AG3-086 (Code-Wert) / AG3-070 (Config-Pfad) spiegeln.
- ARCH-55-Enum-Fix gehoert in AG3-078 (Code), nicht in diese doc-only-Story; nur als Spiegel-Vermerk.
- FK-68 §68.2.2 `review_divergence`-Payload-Field-Row (`68_telemetrie_eventing_workflow_metriken.md:362`): den FK-34-§34.8.4-Feldsatz (`34_*.md:580-582`) exakt uebernehmen; `score`/`routing` ersatzlos streichen. Quelle in der Prosa als FK-34 §34.8.4 + AG3-066-Zielschema benennen — **nicht** behaupten, der aktuell emittierte Code-Payload sei schon FK-34-foermig (er traegt heute noch `score`/`routing`, `divergence_hook.py:93-94`). Die Code-Schema-Migration ist AG3-066, nicht hier.
- NICHT `pattern.py`/`requests.py`/`events.py`/`divergence_hook.py`/`normalizer.py`/Config-Modelle/Routes anfassen (das sind die gespiegelten Code-Owner-Pfade, kein Scope dieser Story).
- AK2 NICHT veraendern, `.mcp.json` NICHT anfassen, **kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung der geaenderten `concept/`-Dateien; gruene Konzept-Gates + Frontmatter-Check + leerer `src/`/`tests/`-Diff.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
