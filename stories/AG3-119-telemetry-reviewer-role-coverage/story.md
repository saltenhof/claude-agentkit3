# AG3-119: Telemetry-Contract Review-Rollen-Coverage auf `reviewer_role` ausrichten

**Typ:** Implementation (Bugfix mit reproduzierendem Test)
**Groesse:** S
**Bounded Context:** `telemetry` / Contract-Layer (FK-68 Integrity-/Contract-Gate). Korrigiert eine Payload-Key-Divergenz in der Review-Rollen-Coverage-Pruefung: der Contract liest `payload["role"]`, die Review-Producer emittieren aber `reviewer_role`. Dadurch greift die Pruefung in der Produktion ins Leere; nur Tests, die kuenstlich `role` seeden, lassen sie scheinbar funktionieren.

**Quell-Konzepte (autoritativ):**
- `FK-68 §68.4 / §68.4.2` — Integrity-/Contract-Gate: pro konfigurierter Pflicht-Reviewer-Rolle muss mindestens ein `review_request` vorliegen; strikte 1:1-Paarung `review_request` ↔ `review_compliant`.
- `AG3-036 AC4` (umgesetzt) — Pflicht-Payload-Felder der Review-Events: `reviewer_role`, `review_round`, … (siehe `telemetry/hooks/review_sentinel_hook.py:6`).
- Kanonische Payload-Key-Wahrheit (bereits etabliert in AG3-117): `state_backend/store/analytics_source.py:73-75` mappt `REVIEW_REQUEST`/`REVIEW_RESPONSE`/`REVIEW_COMPLIANT` → `reviewer_role`.

---

## 1. Kontext / Ist-Zustand (belegt)

- `src/agentkit/telemetry/contract/telemetry_contract.py:388-392` `_roles()` liest `event.payload.get("role")`.
- `_roles()` hat **genau einen** Aufrufer: `check_review_compliant_coverage` (`telemetry_contract.py:181` `present_roles = _roles(requests)`, wobei `requests = _by_type(events, EventType.REVIEW_REQUEST)`).
- Die Review-Producer emittieren die Rolle ausschliesslich unter `reviewer_role`, nicht `role`:
  - `telemetry/hooks/review_guard.py:166` (`_reviewer_role` liest `payload.get("reviewer_role")`),
  - `telemetry/hooks/review_sentinel_hook.py:80` (`"reviewer_role": str(context.payload.get("reviewer_role", ""))`),
  - `telemetry/hooks/divergence_hook.py:113,117` (`payload.get("reviewer_role")`),
  - kanonisches Mapping `analytics_source.py:73-75` (`REVIEW_* -> "reviewer_role"`).
- **Folge in Produktion:** `present_roles` ist fuer echte `review_request`-Events immer leer (die tragen `reviewer_role`, nicht `role`). Die Rollen-Coverage-Teilpruefung (`required_roles - present_roles`) ist damit unwirksam: bei nicht-leerem `required_roles` meldet sie faelschlich „missing role(s)" (false-positive FAIL), bei leerem `required_roles` prueft sie nichts (laeuft ins Leere). Die Schwester-Pruefung der LLM-Rollen ist **nicht** betroffen — `check_llm_call_role_coverage` (`telemetry_contract.py:230-259`) nutzt `_pools()` über `payload["pool"]`.
- **Maskierung durch Tests:** `tests/unit/telemetry/contract/test_telemetry_contract.py:48` setzt im Helper `_event(...)` `payload["role"] = role`; die Review-Coverage-Tests (`:113-161`) übergeben `role="qa"`/`"architecture"`. Dadurch findet `_roles()` die Rollen im Test, obwohl Prod-Events sie unter `reviewer_role` tragen — der Bug bleibt verdeckt.
- Dieser Befund stammt aus dem Codex-r4-WARNING zu AG3-117 (telemetry-Contract-Reconciliation, dort bewusst als eigene Folge-Story zurueckgestellt).

## 2. Scope

### 2.1 In Scope
1. **`_roles()` auf den kanonischen Review-Key umstellen:** liest `payload["reviewer_role"]` statt `payload["role"]`. Zur Klarheit umbenennen in `_reviewer_roles()` (ARCH-55, englisch) und den Aufruf in `check_review_compliant_coverage` anpassen. Verhalten ansonsten identisch (Set der nicht-leeren String-Rollen).
2. **Reproduzierender Test + Realignment:** Die Review-Coverage-Tests seeden `review_request`-Events mit `reviewer_role` (echte Producer-Form), nicht `role`. Mindestens:
   - PASS, wenn alle `required_roles` per `reviewer_role` vorhanden sind und `review_compliant == review_request`.
   - FAIL, wenn eine Pflichtrolle (per `reviewer_role`) fehlt.
   - **Regressions-/Fail-closed-Test:** ein `review_request`, das **nur** den alten Key `role` traegt (kein `reviewer_role`), wird **nicht** als Rolle gezaehlt → die Coverage-Pruefung meldet die Pflichtrolle als fehlend. Das pinnt den kanonischen Key und verhindert ein Zurueckfallen auf `role`.
   - Die bestehenden Compliant-Undercount/Overcount-Tests bleiben erhalten (jetzt mit `reviewer_role` geseedet).
3. Falls der Test-Helper `_event(...)` erweitert werden muss (Key-Parameter o. Ae.), minimal und typisiert; bestehende Nicht-Review-Tests (LLM-Coverage über `role`/`pool`) duerfen sich nicht aendern.

### 2.2 Out of Scope (mit Owner)
- LLM-Rollen-/Pool-Coverage (`check_llm_call_role_coverage`, `_pools`) — korrekt über `pool`, nicht anfassen.
- Analytics-Rollups / `analytics_source.py` — bereits korrekt auf `reviewer_role` (AG3-117).
- Producer-Hooks (`review_guard.py`/`review_sentinel_hook.py`/`divergence_hook.py`) — emittieren bereits korrekt `reviewer_role`; keine Aenderung.
- Aenderung des Wire-Keys `reviewer_role` selbst (er ist die Wahrheit; der Contract ist der Ausreisser).

## 3. Akzeptanzkriterien
1. `check_review_compliant_coverage` ermittelt die vorhandenen Reviewer-Rollen aus `review_request.payload["reviewer_role"]`; `payload["role"]` wird fuer die Review-Coverage **nicht** mehr gelesen.
2. Ein reproduzierender Unit-Test belegt: bei `review_request`-Events in echter Producer-Form (`reviewer_role` gesetzt, kein `role`) wird die jeweilige Pflichtrolle als **present** erkannt (vor dem Fix war sie fehlend → der Test faellt gegen den unkorrigierten Code).
3. Fail-closed-Regressionstest: ein `review_request` mit ausschliesslich `role` (ohne `reviewer_role`) zaehlt **nicht** als Rolle (Pflichtrolle gilt als fehlend).
4. Die strikte 1:1-Paarung `review_compliant == review_request` (FK-68 §68.4) bleibt unveraendert geprueft; Undercount- und Overcount-Tests bleiben gruen (mit `reviewer_role` geseedet).
5. LLM-Rollen-/Pool-Coverage-Tests bleiben unveraendert gruen (keine Kollateralaenderung an `_pools`/`role`/`pool`).
6. ARCH-55: alle Bezeichner englisch. Keine `noqa`/`type: ignore` ohne Begruendung.
7. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates (GAC-1); Coverage >= 85 %.

## 4. Definition of Done
- AK 1–7 erfuellt; QA-Gate ist die Codex-Review (alleiniges Code-Gate) **PASS** + Standard-Pflichtbefehle + Jenkins + Sonar.

## 5. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM / SINGLE SOURCE OF TRUTH:** `reviewer_role` ist die kanonische Review-Rollen-Payload-Wahrheit (Producer + analytics_source + AG3-036). Der Contract wird daran ausgerichtet; es wird **keine** zweite Schreibung `role` parallel toleriert.
- **NO ERROR BYPASSING / FAIL CLOSED:** die Coverage-Pruefung muss real greifen; der Regressionstest verhindert ein stilles Zurueckfallen auf den falschen Key.
- **Bugfix braucht reproduzierenden Test** (Testing-Guardrails): AK2 macht das verbindlich.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Minimaler, chirurgischer Fix: `_roles()` → `_reviewer_roles()` liest `reviewer_role`; nur der eine Aufrufer (`telemetry_contract.py:181`) ist betroffen (vorab verifizieren, dass es keinen weiteren `_roles(`-Aufruf gibt).
- Review-Coverage-Tests in `tests/unit/telemetry/contract/test_telemetry_contract.py` auf `reviewer_role` umstellen + Fail-closed-Regressionstest ergaenzen. LLM-Coverage-Tests nicht anfassen.
- Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Test-Namen (inkl. des reproduzierenden + des fail-closed-Tests), gruene Pflichtbefehle.

## 7. Vorbedingungen
- Keine offenen Abhaengigkeiten (AG3-117 abgeschlossen; `reviewer_role` ist bereits die Producer-/Analytics-Wahrheit).
- `unblocks`: keine.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed).
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
