# AG3-003: SSE-Streaming fuer Live-Updates

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-002 (Auth-Middleware)
**Quell-Konzept:** FK-72 §72.12, FK-91 §91.8

---

## Kontext

Frontend und BFF kommunizieren Live-Updates ueber **Server-Sent
Events (SSE)** als einheitlichen Mechanismus (keine Polling). Die
fachliche Mechanik (FK-72 §72.12):

- Pattern: Initial-GET (Snapshot) + SSE-Subscribe (Updates)
- Lossy mit Re-Sync bei Reconnect (kein Sequence-Cursor)
- Single-Producer fuer projekt-skopierten Stream: `telemetry`
- Hub-Stream als Ausnahme, vom `multi_llm_hub`-Adapter bedient

Endpoints (FK-91 §91.8):

| Methode | Pfad | Inhalt |
|---|---|---|
| `GET` | `/v1/projects/{project_key}/events` | projekt-skopierter Stream, Topics aus FK-91 §91.8.3 |
| `GET` | `/v1/events/hub` | Hub-Stream (projektneutral), Topics aus §91.8.4 |

## Scope

### In Scope

- SSE-Endpoint `/v1/projects/{project_key}/events` in `agentkit.telemetry.http`
  - Query-Parameter `?topics=stories,phases,gates,governance,closure,artifacts,telemetry,kpi,planning,failure_corpus,coverage`
  - Server filtert serverseitig pro `project_key` und Topics
  - SSE-Format: `event:`, `data:` (JSON), Heartbeat alle 30 Sekunden
  - Lossy: bei Backpressure Events droppen (kein Buffering ohne Limit)
- SSE-Endpoint `/v1/events/hub` in `agentkit.multi_llm_hub.http`
  - Query-Parameter `?topics=backend_status,sessions,session_messages`
  - Same Lossy-Verhalten
- Telemetry-Producer-Mechanik:
  - Event-Quelle ist die existierende `execution_events`-Tabelle
  - Subscribe-Mechanik: SSE-Stream pollt mit kurzem Intervall die letzten Events seit dem Open-Zeitpunkt (oder LISTEN/NOTIFY in Postgres, falls einfacher umzusetzen — Detail im Implementer-Ermessen)
- Auth-Integration: SSE-Endpoint erbt Auth aus AG3-002-Middleware (UI-BFF: Cookie; Project-API: Token)
- Tests:
  - SSE-Verbindung wird geoeffnet, Heartbeat funktioniert
  - Topics-Filter wirkt
  - Reconnect funktioniert (Browser-Standard)
  - Bei fehlendem Auth: 401
  - Cross-Projekt: kein Event-Leak (Projekt A sieht keine Events aus Projekt B)

### Out of Scope

- Frontend-Konsument (Frontend-Story spaeter)
- Sequence-IDs/Cursor-Mechanik (lossy ist die Linie)
- Per-User-Subscription-Limits
- WebSocket (SSE bleibt der Mechanismus)
- Hub-Producer-Implementierung (das ist Bestandteil von `multi_llm_hub`-Erweiterung; hier nur Endpoint-Skelett)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|--------------|--------------|
| `src/agentkit/telemetry/http/__init__.py` | Modifiziert/Neu | Routes-Package |
| `src/agentkit/telemetry/http/routes.py` | Modifiziert/Neu | SSE-Endpoint `/v1/projects/{key}/events` |
| `src/agentkit/telemetry/sse_stream.py` | Neu | SSE-Stream-Komposition (Topics-Filter, Heartbeat, Lossy) |
| `src/agentkit/multi_llm_hub/http/routes.py` | Modifiziert | SSE-Endpoint `/v1/events/hub` |
| `src/agentkit/multi_llm_hub/sse_stream.py` | Neu | Hub-spezifische SSE-Stream-Komposition |
| `tests/unit/telemetry/test_sse_stream.py` | Neu | Stream-Komposition, Topics-Filter, Heartbeat |
| `tests/unit/telemetry/http/test_sse_routes.py` | Neu | Endpoint-Tests, Auth-Verhalten |
| `tests/unit/multi_llm_hub/test_sse_stream.py` | Neu | Hub-Stream-Tests |
| `tests/integration/sse/test_sse_e2e.py` | Neu | End-to-End: Event in DB → Subscriber bekommt es |

## Akzeptanzkriterien

1. **SSE-Endpoint `/v1/projects/{key}/events`** ist erreichbar, liefert Events im SSE-Format mit `event:`-Topic-Marker und JSON-Payload.
2. **Topics-Filter** funktioniert: nur die in `?topics=` angefragten Events werden geliefert.
3. **Heartbeat** alle 30 Sekunden, damit der Browser die Connection nicht abbricht.
4. **Hub-Endpoint `/v1/events/hub`** ist erreichbar, projektneutral, gleiche Topics-Filter-Konvention.
5. **Auth wirkt**: ohne Cookie/Token → 401. Mit ungueltigem Auth → 401.
6. **Cross-Project-Isolation**: ein Stream auf Projekt A liefert keine Events aus Projekt B.
7. **Lossy**: bei Backpressure droppt der Server, der Client bekommt keine "Stau"-Errors. Beim Reconnect macht der Client einen frischen Initial-GET, der Server hat keine Cursor-Logik.
8. **Tests gruen**, ruff, mypy strict, alle drei concept-lints, audit clean.

## Definition of Done

- Build kompiliert
- `pytest tests/unit` plus `pytest tests/integration/sse` gruen
- ruff, mypy strict, concept-lints, audit clean
- SSE-Endpoint manuell getestet (via `curl -N` mit gueltigem Cookie/Token)

## Konzept-Referenzen

- FK-72 (`concept/technical-design/72_frontend_architektur.md`) §72.12 — Live-Updates-Mechanik
- FK-91 (`concept/technical-design/91_api_event_katalog.md`) §91.8 — SSE-Endpoints und Topics
- FK-15 §15.10 — Auth-Bezug

## Guardrail-Referenzen

- ZERO DEBT, FAIL CLOSED
- SINGLE SOURCE OF TRUTH: telemetry bleibt Single-Producer fuer projekt-skopierte Events
