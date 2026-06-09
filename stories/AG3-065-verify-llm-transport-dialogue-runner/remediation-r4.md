# AG3-065 — Remediation R4 (Antwort auf review-r4.md)

**Story:** AG3-065 — Verify-LLM-Transport + DialogueRunner + Timeouts
**Review:** `review-r4.md` (OVERALL: CHANGES-REQUESTED; 3 verbleibende/neue Must-Fix-ERRORs; Round-3-RESOLVED: Queued-Acquire, DialogueRunner-Transcript-Logging bestätigt)
**Ergebnis:** `story.md` editiert; `status.yaml` geprüft (korrekt, keine Änderung); nur `story.md` und diese `remediation-r4.md` geschrieben.
**Scope-Leitplanke:** Index-Schnitt `_STORY_INDEX.md:65` — `FK § = FK-11 §11.2-§11.6`, `depends_on = AG3-043, AG3-075`, Konsument = AG3-079 (`:79`). Kein Scope über diesen Schnitt hinaus. AG3-057-Template (§1-§6) beibehalten; §7 als klar markierter WARNING-/Gap-Abschnitt ergänzt (CLAUDE.md SEVERITY-SEMANTIK: ein Befund, für den niemand sonst Zeit bekommt, muss gespiegelt werden). ARCH-55 (Englisch) für alle neuen Identifier eingehalten.

---

## Verbleibende / neue Must-Fix-ERRORs (review-r4)

### ERROR 1 — Login-required ist über den realen Hub-Client nicht zuverlässig erkennbar
**Befund (review-r4):** Story verlangte `HubLlmClient` wirft `LoginRequiredError` für `send → 500`, aber `client.py:238-254` mappt **jeden** 5xx pauschal auf `HubUnavailableError`. Zusätzlich Wire-Key-Mismatch: Routes emittieren den getypten Code unter `error_code` (`routes.py:364-366`), der Client liest aber `payload.get("error")` (`client.py:245`) — also die Nachricht. Getypter Error-Code-Dispatch ist damit nicht verfügbar. Fix-Vorgabe: getypte Hub-Login-Oberfläche (`HubLoginRequiredError` o.ä. / strukturierter `HubHttpError`) + Tests auf HubClient- **und** HubLlmClient-Ebene.

**Realer Code verifiziert:**
- `_hub_error_from_http_error` (`client.py:238-254`): liest `payload.get("error")` (`:245` = Nachricht, **nicht** Code), einzige getypte Regel `code == "unknown_session"` (`:247`) greift nie gegen reale Route-Codes; jeder 5xx → `HubUnavailableError` (`:249-250`/`:252-253`).
- Routes (`http/routes.py:356-371`): `error_code` (Code) **und** `error` (Nachricht) im Payload; reale Codes `hub_session_not_found` (`:341`), `hub_unavailable` (`:332`), `hub_error` (`:350`).

**Resolution (in-story, im Cut):**
- §1 neuer belegter Ist-Zustand-Punkt „Hub-Fehler-Oberfläche kollabiert distinkte Ausgänge" (5xx-Pauschal-Mapping + `error_code`/`error`-Mismatch, mit Ankern `client.py:245/247/249-250/252-253`, `routes.py:332/341/350/364-366`).
- Scope 2.1.3 neue verbindliche Designentscheidung „Benötigte Hub-Fehler-Code-Oberfläche" mit **kanonischer Code-Tabelle**: `_hub_error_from_http_error` liest den getypten `error_code`; `hub_session_not_found` → `HubSessionNotFoundError` (bestehend); Login-Code (HTTP 500) → **neue `HubLoginRequiredError`** (Subklasse von `MultiLlmHubError` in `multi_llm_hub/errors.py`, getrennt von `HubUnavailableError`); unbekannter/fehlender Code → bisheriges Verhalten (rückwärtskompatibel). Fehlt ein Login-`error_code` in den Routes, wird er **minimal** ergänzt (ARCH-55, Wire-Key `error_code`) — analog zur minimalen `llm_call`-EventType-Ergänzung. Rückgabetypen acquire/send/release unverändert → AG3-079-Port stabil.
- AC10 aufgeteilt: (b) **Hub-Ebene** (Login-`error_code` → `HubLoginRequiredError` statt pauschalem `HubUnavailableError`, Fake-`HTTPError`) **und** (c) **HubLlmClient-Ebene** (`HubLoginRequiredError` → distinkte `LoginRequiredError` mit `operator_hint` + Rückwärtskompatibilität bestehender `LlmClientError`-Catches). Tests damit auf **beiden** geforderten Ebenen.
- §5/§6-Hinweise + ARCH-55-Liste (`HubLoginRequiredError`, `error_code`) nachgezogen; Sub-Agent-Hinweis „Hub-Fehler-Code-Oberfläche zuerst reparieren".

### ERROR 2 — FK-11-Login-Pause bleibt ohne Owner (Fehl-Routing an AG3-059 korrigiert)
**Befund (review-r4):** Story routet die Pause-Verdrahtung an AG3-059, aber AG3-059-Scope deckt nur das `pause_reason`-Feld/Schema (`stories/AG3-059.../story.md:29-35`), **nicht** einen Login-Pause-Wert oder Phase-Runner-Verhalten. Fix-Vorgabe: entweder Pause-Handoff in AG3-065-AC holen, oder Owner-Story explizit aktualisieren/anlegen mit `PauseReason`/Phase-Runner-Pause + Dependency/AC.

**Verifiziert:**
- AG3-059 story.md §2.1.2/§2.2: ownt **nur** Wire-Key/Feldsatz/Schema-Ownership; neue Enum-**Werte** werden explizit weggeroutet (`escalation_reason`-Wert → AG3-058).
- `PauseReason` ist eine **geschlossene** 3-Wert-StrEnum (`core_types/pause_reason.py:46-60`); FK-39 §39.2.2 (`39_phase_state_persistenz.md:255-260`): „Jeder andere String ist ungültig". Enum-Owner FK-39 / AG3-021 (`completed`).
- Ein Login-Pause-Member + Phase-Runner-Pause ist in **keinem** Index-Schnitt geführt → echte, ungeschnittene Konzept-Lücke (Konzept-Änderung in FK-39 + Phase-Runner-Verhalten).

**Resolution (Fehl-Routing korrigiert + Gap korrekt gespiegelt, kein erfundener Scope):**
- §2.2-Out-of-Scope-Zeile umgeschrieben: **„OFFENE, UNGESCHNITTENE KONZEPT-LÜCKE (kein existierender Owner)"** statt „AG3-059". Begründet, warum AG3-059 der falsche Owner ist (nur Schema/Wire-Key, routet Werte weg), und dass FK-39-Konzept-Änderung + Phase-Runner-Verdrahtung in keinem Cut liegen.
- §1, Scope 2.1.3, §5, §6 durchgängig von „Owner AG3-059" auf „offene Konzept-Lücke (§7)" korrigiert; AG3-059 nur noch als Wire-Key/Schema-Owner referenziert (sachlich korrekt).
- **Neuer §7 „Offene Konzept-Lücke (WARNING — Spiegelung an Auftraggeber)"**: benennt die Lücke (FK-39-Member + Phase-Runner-Pause), warum kein Owner existiert, und den aufschiebenden Handlungsauftrag (neue Story/Scope-Erweiterung) — konform CLAUDE.md SEVERITY-SEMANTIK statt stillem Liegenlassen. AG3-065 bleibt strikt im Transport-Cut und liefert nur den getypten Ausgang `LoginRequiredError` mit `operator_hint`.

### ERROR 3 — `lease_expired`/Session-not-found-Retry ist spezifiziert, aber nicht gegen die reale Hub-Oberfläche acceptance-getestet
**Befund (review-r4):** FK-11 fordert neuen Acquire bei `lease_expired` (`11_...:190`); Story §2.1.3 nennt es, aber AC3 (`story.md:85`) hat keinen Test dafür. Reales HTTP-Parsing mappt nur `payload.get("error") == "unknown_session"` (`client.py:245-248`) auf `HubSessionNotFoundError`, während Routes `error_code="hub_session_not_found"` (`routes.py:338-342`) emittieren. Fix-Vorgabe: kanonisches Hub-Error-Code-Mapping für session expired/not found + HubClient- und HubLlmClient-Retry-Tests.

**Resolution (in-story, im Cut — teilt die Wurzel mit ERROR 1):**
- Die kanonische Code-Tabelle (Scope 2.1.3, ERROR 1) deckt `hub_session_not_found` → `HubSessionNotFoundError` über den getypten `error_code`-Pfad ab — die heutige Code/Nachricht-Verwechslung ist damit behoben.
- Scope 2.1.3 `lease_expired`-Bullet präzisiert: `HubLlmClient` fängt den (jetzt zuverlässigen) `HubSessionNotFoundError` und führt **einen** neuen Acquire + zweiten `send` aus (unter der Send-Max-1-Grenze), danach fail-closed.
- AC3 erweitert um (g) **Hub-Ebene** (`error_code="hub_session_not_found"` → `HubSessionNotFoundError`, Fake-`HTTPError`; belegt behobenen `client.py:245`-Bug) und (h) **HubLlmClient-Ebene** (Re-Acquire-Retry: ein neuer Acquire + zweiter Send, Call-Count-Assertionen; zweiter Fehler → fail-closed).
- §5 (FAIL CLOSED) + §6-„done"-Belegliste + Sub-Agent-Hinweis um `lease_expired`/Re-Acquire ergänzt.

---

## Round-3-RESOLVED-Status (review-r4 bestätigt, unverändert übernommen)
- Queued-Acquire: **RESOLVED** (`HubAcquireQueuedError` + Tests beide Ebenen) — unverändert.
- DialogueRunner-Transcript-Logging: **RESOLVED** (persistiertes Transcript inkl. Prompt+Response pro Turn, `skipped`-Pfad) — unverändert.
- Per-Operation-Timeouts / AG3-070-`llm_roles` / Remote-Gate: weiterhin RESOLVED — unverändert.

## Per-Dimension-FAILs (review-r4) — Auflösung
- **Konzept-Vollständigkeit (war FAIL):** FK-11-Login-Pause jetzt end-to-end behandelt — Transport-Ausgang in-story (getypt, Hub- + Verify-Ebene), Pause-Verdrahtung als explizite, korrekt benannte Konzept-Lücke (§7) statt Fehl-Routing.
- **AC-Schärfe (war FAIL):** AC10 prüft jetzt den realen `HubClient`-Login-Pfad (getypter `error_code`, nicht nur `HubLlmClient`); AC3 trägt den `lease_expired`/Session-not-found-Retry auf beiden Ebenen.
- **Klarheit/Eindeutigkeit (war WEAK):** kanonische Hub-Fehler-Code-Tabelle definiert die geforderte Error-Surface; Login/Session/Unavailable sind getrennt benannt.
- **Kontext-Sinnhaftigkeit (war FAIL):** Designentscheidung am realen `_hub_error_from_http_error`-Mismatch (`error_code` vs. `error`, 5xx-Pauschal-Mapping) ausgerichtet; die kollabierten Ausgänge sind jetzt unterscheidbar modelliert.

---

## Code-Anker (gegen den realen Code verifiziert / präzisiert)

| Thema | Verifiziert |
|---|---|
| 5xx-Pauschal-Mapping + Code/Nachricht-Mismatch | `_hub_error_from_http_error` `client.py:238-254`: `payload.get("error")` `:245` (Nachricht), Regel `code == "unknown_session"` `:247`, `5xx → HubUnavailableError` `:249-250`/`:252-253` |
| Reale Route-Fehlercodes | `http/routes.py:356-371` (`error_code` + `error` im Payload); `hub_unavailable` `:332`, `hub_session_not_found` `:341`, `hub_error` `:350` |
| Hub-Error-Basis | `multi_llm_hub/errors.py:8-17` — `MultiLlmHubError` (Basis), `HubUnavailableError`/`HubSessionNotFoundError`; neue `HubLoginRequiredError` als Geschwister |
| PauseReason geschlossen | `core_types/pause_reason.py:46-60` (3 Werte); FK-39 §39.2.2 `concept/technical-design/39_phase_state_persistenz.md:255-260` („jeder andere String ist ungültig") |
| Login-Pause-Owner-Lage | Enum-Owner FK-39/AG3-021 (`completed`); AG3-059 ownt nur Wire-Key/Schema (AG3-059 story.md §2.1.2/§2.2, `_STORY_INDEX.md:45`); neuer Member + Phase-Runner-Pause = **kein** existierender Owner |
| LlmClient-Port/Error | `LlmClient`-Port `llm_client.py:42-74`; `LlmClientError` `:29-38` (Basis für `LoginRequiredError`); `FailClosedLlmClient` `:77-112` |
| FK-11 Login-/lease_expired-Quelle | `11_llm_provider_browser_pools_prompt_execution.md:190` (`lease_expired` → neuer Acquire), `:191` (Login-Fehler → Pause mit Hinweis) |
| Index-Schnitt AG3-065 | `_STORY_INDEX.md:65` (`FK-11 §11.2-§11.6`, `depends_on: AG3-043, AG3-075`); Konsument AG3-079 `:79` |

---

## status.yaml
Geprüft, **keine Änderung**: `depends_on: [AG3-043, AG3-075]` stimmt exakt mit dem Index-Schnitt (`_STORY_INDEX.md:65`). Die korrigierte Login-Pause-Lücke ist ein **fachlicher Nachfolger** (neue Story/Konzept-Erweiterung), kein Build-Blocker für die hier gelieferten Transport-Artefakte — daher kein Index-überschreibendes Dependency-Feld. `status: draft` / `phase: review_pending` sind template-konform (AG3-057) korrekt.

## Geschriebene Dateien (nur diese)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/story.md` (editiert)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/remediation-r4.md` (dieser Report)
- `status.yaml`: **nicht** geändert (geprüft, korrekt).

**Keine** Produktionscode-, Test- oder `concept/`-Datei wurde angefasst.
