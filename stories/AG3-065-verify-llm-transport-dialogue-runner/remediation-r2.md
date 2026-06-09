# AG3-065 — Remediation R2 (Antwort auf review-r2.md)

**Story:** AG3-065 — Verify-LLM-Transport + DialogueRunner + Timeouts
**Review:** `review-r2.md` (OVERALL: CHANGES-REQUESTED, alle vier Dimensionen FAIL, 4 Must-Fix-ERRORs)
**Ergebnis:** `story.md` editiert; `status.yaml` geprüft (korrekt, keine Änderung); nur `story.md` und diese `remediation-r2.md` geschrieben.
**Scope-Leitplanke:** Index-Schnitt `var/concept-gap-analysis/_STORY_INDEX.md:56` — `FK § = FK-11 §11.2-§11.6`, `depends_on = AG3-043, AG3-075`, Konsument = AG3-079 (`:80`). Kein Scope über diesen Schnitt hinaus hinzugefügt.

---

## Must-Fix-ERRORs

### ERROR 1 — Per-Operation-Timeouts gegen die heutige Hub-Oberfläche nicht implementierbar
**Befund (review-r2):** AC8 verlangt acquire/send/release-spezifische Timeouts; der reale `HubClient`/`UrllibJsonTransport` trägt nur **einen** Konstruktor-Timeout (`client.py:115-122`, `:59`, `:115`). Die Story gab die nötige Protokoll-/Adapter-Änderung nicht an.
**Resolution:** Realer Ist-Zustand verifiziert und in §1 belegt: `HubClient.__init__(timeout=30.0)` → `UrllibJsonTransport(timeout=...)` (`:115-122`/`:59`/`:77`); `JsonTransport.request` (`:47-53`) und `acquire`/`send`/`release` (`:149`/`:168`/`:206`) tragen **keinen** Per-Operation-Timeout. Scope 2.1.7 als **verbindliche Designentscheidung** neu gefasst: additive, rückwärtskompatible Erweiterung um einen **optionalen Per-Request-`timeout`** auf `JsonTransport.request` + `UrllibJsonTransport.request` + `HubClientProtocol`/`HubClient.acquire`/`send`/`release` (Default = Konstruktor-Timeout, keine bestehende Aufrufstelle bricht). `HubLlmClient` setzt damit acquire=30 / send=2400 / release=10; `TOTAL_TIMEOUT_SECONDS=2500` begrenzt den Gesamt-Evaluator-Aufruf. AC8 neu: Tests asserten **distinkte** Timeout-Werte je Operation an der Transport-Schicht **und** Rückwärtskompatibilität bestehender Aufrufer. Keine zweite Transport-Wahrheit.

### ERROR 2 — `llm_roles`/AG3-070-Konflikt nur umbenannt, nicht echt gelöst
**Befund (review-r2):** Story behauptete `HubLlmClient` = produktiver Default, während die produktive Resolver-Implementierung in AG3-070 Out-of-Scope ist und `llm_roles` im Config-Modell heute nicht existiert; ohne AG3-070 oder zweite Routing-Wahrheit kann der Default nicht produktiv sein.
**Resolution:** AG3-070-Story gelesen — sie ist nachweislich der **Owner** des `llm_roles`-Felds + produktiven `RolePoolResolver` (AG3-070 Scope 2.1.3; AG3-070 Ist-Zustand belegt: `llm_roles` existiert heute nicht). Echte (nicht umformulierte) Auflösung: „produktiver Default" **durchgängig entfernt** und ersetzt durch **injizierbarer Adapter, fail-closed bis AG3-070**:
- §1 Konfliktauflösung explizit: `HubLlmClient` ist kein produktiver Default ohne AG3-070; ohne injizierten produktiven Resolver bleibt `FailClosedLlmClient` im Composition-Root aktiv; keine `llm_roles`-Ersatzlogik in AG3-065.
- Scope 2.1.1 (Adapter „injizierbar … erst produktiv aktiv mit produktivem Resolver"), 2.1.9 (Composition-Root „fail-closed bis AG3-070"), 2.2 Out-of-Scope-Note (echte Konfliktauflösung statt Dependency), AC1 (Test: ohne Resolver fail-closed, mit Resolver liefert `HubLlmClient`).
- `depends_on = AG3-043, AG3-075` bleibt damit korrekt zum Index-Schnitt; AG3-070 ist **fachlicher Nachfolger** für die produktive Aktivierung, kein Build-Blocker → keine zweite Routing-Wahrheit, kein Index-Widerspruch.

### ERROR 3 — FK-11 Queued-Acquire-Handling fehlt weiterhin
**Befund (review-r2):** FK-11 §11.2.3 (Zeile 187) verlangt `acquire → queued` → Warten + Re-Acquire mit gleichem Owner; §11.6.1 (Zeile 553/556) max 5 Acquire-Versuche. R1 hatte das fälschlich an FK-75/Hub-Server delegiert. AC3 testete nur Release/Send-Timeout/Send-Fehler.
**Resolution:** Als **diese-Story-Konzept** (FK-11 §11) korrekt eingezogen — die Queued-Warte-Logik ist client-/evaluator-seitig (FK-11 §11.6.1 Zeile 553: „Nicht-blockierend; bei `queued` Retry nach geschätzter Wartezeit"), nicht Hub-Server-Sache:
- Quell-Konzept-Zeilen ergänzt (§11.2.3 Zeile 187; §11.6.1 Zeile 553/556).
- §1 Ist-Zustand: belegt, dass `HubClient.acquire` (`:149-166`) die Antwort direkt als gewährten Lease parst und `queued` heute nicht modelliert.
- Scope 2.1.3 als erster Punkt: Queued-Acquire mit benannter Obergrenze `MAX_ACQUIRE_RETRIES = 5`, Re-Acquire mit gleichem Owner, danach `LlmClientError` (fail-closed); getrennt vom Send-Timeout-Retry-Budget. Minimal nötige `queued`-Erkennung im Verify-Adapter, ohne den Hub-Slot-Pool (FK-75) umzubauen.
- AC3 erweitert um (d) Queued-Acquire-Erfolg innerhalb 5 Versuchen (Owner identisch) und (e) Erschöpfung → fail-closed, Acquire-Call-Count = 5.
- Sub-Agent-Hinweise + FAIL-CLOSED-Guardrail ziehen nach.

### ERROR 4 — Pflicht-Remote-Gate-Befehl fehlt in DoD/AC
**Befund (review-r2):** AGENTS.md verlangt `scripts/ci/check_remote_gates.ps1` (Jenkins/Sonar) vor „fertig"; AC11 listete nur lokale Checks.
**Resolution:** AGENTS.md (Zeile 43-45) verifiziert; Script existiert (`scripts/ci/check_remote_gates.ps1`). AC11 erweitert um den Pflichtbefehl `pwsh -File scripts/ci/check_remote_gates.ps1` mit der Env-Var-Vorbedingung (`SONAR_*`/`JENKINS_*` via `T:\seu\agentkit3-secrets.cmd`) und der harten Sonar-Schwelle (`violations=0`/`critical_violations=0`/`security_hotspots=0`). Sub-Agent-Hinweise + „done"-Belegliste nachgezogen.

---

## Per-Dimension-FAILs (review-r2) — Auflösung

- **Konzept-Vollständigkeit (war FAIL):** FK-11 Queued-Acquire jetzt in Quell-Konzepten, Scope 2.1.3 und AC3 (ERROR 3).
- **AC-Schärfe (war FAIL):** AC8 spezifiziert nun die konkrete Protokoll-/Adapter-Erweiterung (optionaler Per-Request-Timeout) statt eines nicht-implementierbaren „an Transport durchreichen" (ERROR 1).
- **Klarheit/Eindeutigkeit (war FAIL):** AG3-070-Konflikt echt aufgelöst (injizierbarer Adapter / fail-closed bis AG3-070), „produktiver Default" entfernt (ERROR 2).
- **Kontext-Sinnhaftigkeit (war FAIL):** Timeout- und Resolver-Annahmen jetzt an die realen Oberflächen angeglichen — der einzelne Konstruktor-Timeout und das fehlende `llm_roles`-Feld sind belegt und treiben die Designentscheidungen (ERROR 1+2). Die als korrekt bestätigten Anker (`llm_client.py:55`, `structured_evaluator.py:329`/`:358`, `client.py:168`) bleiben unverändert.

---

## Code-Anker (gegen den realen Code verifiziert / präzisiert)

| Thema | Verifiziert |
|---|---|
| Single-Konstruktor-Timeout | `HubClient.__init__` `client.py:115-122`; `UrllibJsonTransport.__init__` `:59`; `urlopen(timeout=self._timeout)` `:77`; `JsonTransport.request` ohne Timeout `:47-53` |
| Per-Op-Timeout fehlt | `acquire` `:149`, `send` `:168`, `release` `:206` — keine Timeout-Parameter |
| Queued-Acquire fehlt | `HubClient.acquire` parst direkt gewährten Lease `:149-166` (`_lease_payload` `:164-166`), kein `queued`-Pfad |
| `send` ohne Datei-Parameter | `HubClientProtocol.send` `:99-107`, `HubClient.send` `:168-204` (unverändert) |
| FK-11 Queued-Quellen | Konzept-Datei Zeile 187 (Tabelle), Zeile 553/556 (Timeout-/Retry-Tabelle) |
| AGENTS-Remote-Gate | AGENTS.md Zeile 43-45 (`check_remote_gates.ps1`, Env-Var-Vorbedingung) |
| AG3-070 = `llm_roles`-Owner | AG3-070 Scope 2.1.3 + Ist-Zustand (`llm_roles` heute nicht vorhanden) |

---

## status.yaml
Geprüft, **keine Änderung**: `depends_on: [AG3-043, AG3-075]` stimmt exakt mit dem Index-Schnitt (`_STORY_INDEX.md:56`). Der AG3-070-Konflikt wurde bewusst durch den injizierbaren-Adapter/fail-closed-Schnitt gelöst (review-r2 ERROR 2 nennt genau diese Option als gültig), nicht durch eine den Index überschreibende Dependency — daher kein Feldfehler. `status: draft` / `phase: review_pending` sind template-konform (AG3-057) korrekt.

## Geschriebene Dateien (nur diese)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/story.md` (editiert)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/remediation-r2.md` (dieser Report)
- `status.yaml`: **nicht** geändert (geprüft, korrekt).

**Keine** Produktionscode-, Test- oder `concept/`-Datei wurde angefasst.
