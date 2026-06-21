# AG3-002: Auth-Modul fuer Control-Plane (UI-BFF + Project-API)

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** Keine
**Quell-Konzept:** FK-15 §15.10 (`concept/technical-design/15_security_secrets_identity_zugriffsmodell.md`)

---

## Kontext

Die Control-Plane-HTTP-Schicht (`agentkit.backend.control_plane_http`) ist
heute ohne Authentifizierung erreichbar. Mit der Einfuehrung der
UI-BFF (Port 9701) und der Project-API (Port 9702) braucht AK3
eine minimal-pragmatische Auth-Schicht. Konzeptionell festgelegt
(FK-15 §15.10):

- **Single-User, Single-Tenant** — keine Rollen, keine Multi-User-
  Vorbereitung.
- **Strategen-Login**: Cookie-basierte Session nach Login mit lokal
  hinterlegtem Passwort. Schuetzt UI-BFF.
- **Thin-Client-Token**: Bearer-Token im `Authorization`-Header.
  Schuetzt Project-API. Ein Token pro Thin-Client-Registrierung,
  projektgebunden, revozierbar.
- **Worker-Agent**: kein API-Auth (Trusted-Path im selben Prozess).

Auth-Schicht ist **R-Boundary** (kein A-BC), als Middleware vor den
fachlichen Routern.

## Scope

### In Scope

- Neues Boundary-Modul `agentkit.backend.auth` (Bluttyp R, `boundary_kind:
  adapter_boundary`)
- Pydantic-v2-Modelle: `StrategistCredentials`, `ProjectApiToken`,
  `Session`
- Strategen-Login: Endpoint `POST /v1/auth/login`, Logout
  `POST /v1/auth/logout`, Session-Cookie-Setzung (HttpOnly, Secure,
  SameSite-strict)
- Passwort-Storage: Hash in lokaler Konfigurationsdatei
  (`~/.config/agentkit/auth.json` oder OS-Keychain — Detail im
  Implementer-Ermessen, dokumentieren). Argon2id als Hash-Verfahren.
- Session-Storage: server-seitig, in-memory oder file-basiert
  (Detail im Implementer-Ermessen). Lebensdauer 24 Stunden, gleitet
  bei Aktivitaet.
- CSRF-Token pro Session, bei mutierenden Anfragen erwartet
- Project-API-Token-Verwaltung: Endpoint
  `POST /v1/projects/{key}/api-tokens` (erzeugt Token,
  Klartext-Anzeige nur einmal),
  `GET /v1/projects/{key}/api-tokens`,
  `DELETE /v1/projects/{key}/api-tokens/{token_id}`
- Token-Persistenz: gehasht in `project_api_tokens`-Tabelle (FK auf
  `projects.key`)
- Auth-Middleware fuer `control_plane_http`:
  - Erkennt Endpoint-Klasse (UI-BFF vs. Project-API vs. projektneutral
    vs. Login/Health)
  - UI-BFF: Cookie-basiert, 401 bei fehlendem/ungueltigen Cookie
  - Project-API: Bearer-Token, 401/403 (Token gehoert nicht zum Projekt)
  - Login/Health/Hub-Heartbeat: kein Auth
- Tests: Unit-Tests fuer Auth-Modul, Integration-Tests fuer Middleware

### Out of Scope

- OIDC/SSO-Anbindung
- Rollen- und Berechtigungsmodell
- Multi-User (mehrere Strategen-Konten)
- mTLS
- Token-Scopes (read-only vs. read-write)
- Frontend-Login-UI (separate Story; Auth-Backend reicht aus, das
  Frontend kann Mock-Login nutzen, bis Frontend-Story kommt)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|--------------|--------------|
| `src/agentkit/auth/__init__.py` | Neu | Modul-Skelett, Public API |
| `src/agentkit/auth/entities.py` | Neu | Pydantic-Modelle |
| `src/agentkit/auth/errors.py` | Neu | Domain-Errors (`AuthFailedError`, `TokenNotFoundError`, `ProjectMismatchError`) |
| `src/agentkit/auth/credentials.py` | Neu | Strategen-Passwort-Storage (Argon2id-Hash, Konfigurationsdatei) |
| `src/agentkit/auth/sessions.py` | Neu | Session-Lifecycle, CSRF-Token-Erzeugung |
| `src/agentkit/auth/tokens.py` | Neu | Token-Generierung, -Hashing, -Validierung |
| `src/agentkit/auth/middleware.py` | Neu | FastAPI-/Aequivalent-Middleware fuer Auth-Pruefung |
| `src/agentkit/auth/http/__init__.py` | Neu | HTTP-Routes-Package |
| `src/agentkit/auth/http/routes.py` | Neu | Endpunkte: `/v1/auth/login`, `/v1/auth/logout`, `/v1/projects/{key}/api-tokens/...` |
| `src/agentkit/state_backend/store/auth_repository.py` | Neu | Token-Persistenz (Postgres + SQLite) |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Neue Tabelle `project_api_tokens` |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | SQLite-Schema-Ensure fuer `project_api_tokens` |
| `src/agentkit/state_backend/postgres_store.py` | Modifiziert | Postgres-Schema-Ensure fuer `project_api_tokens` |
| `src/agentkit/control_plane/http.py` | Modifiziert | Auth-Middleware vor BC-Routern registrieren |
| `concept/formal-spec/architecture-conformance/entities.md` | Modifiziert | Neues `boundary.auth`-Eintrag (R, adapter_boundary) |
| `tests/unit/auth/test_credentials.py` | Neu | Argon2id-Hash, Passwort-Pruefung |
| `tests/unit/auth/test_sessions.py` | Neu | Session-Lifecycle, CSRF |
| `tests/unit/auth/test_tokens.py` | Neu | Token-Generierung, Validierung |
| `tests/unit/auth/test_middleware.py` | Neu | Middleware-Verhalten pro Endpoint-Klasse |
| `tests/unit/auth/http/test_routes.py` | Neu | Login-/Logout-/Token-Endpunkte |

## Akzeptanzkriterien

1. **`agentkit.backend.auth`-Modul existiert** als R-Boundary in `entities.md` (Bluttyp R, `adapter_boundary`).
2. **Strategen-Login funktioniert**: lokales Passwort (Argon2id), Cookie-Session mit HttpOnly/Secure/SameSite-strict, CSRF-Token.
3. **Session-Verlaengerung** bei Aktivitaet (gleitende 24h-Lebensdauer).
4. **Project-API-Token-Verwaltung**: Tokens werden erzeugt, projektgebunden persistiert, einmal im Klartext angezeigt, danach nur gehasht.
5. **Middleware-Verhalten**:
   - UI-BFF-Endpoints: 401 bei fehlendem/ungueltigem Cookie
   - Project-API-Endpoints: 401 bei fehlendem/ungueltigem Token, 403 bei Token-Projekt-Mismatch
   - Login/Health: kein Auth
6. **Worker-Agent-Pfad** (Trusted-Path im selben Prozess) wird **nicht** durch HTTP-Auth gehindert — Worker laufen direkt ueber die fachlichen Komponenten, nicht ueber HTTP.
7. **Auth-Modul ist als R-Boundary lint-konform**: keine A-BC-Importe ausser `state_backend_repository`.
8. **Tests gruen**: alle Unit- und Integration-Tests, ruff, mypy strict, alle drei concept-lints, architecture-conformance-Audit.
9. **Keine AC012-Warnings** im `agentkit.backend.auth`-Modul.

## Definition of Done

- Build kompiliert
- `pytest tests/unit` gruen, `pytest tests/integration` gruen falls relevant
- ruff, mypy strict
- alle drei concept-lints und architecture-conformance-Audit clean
- entities.md um `boundary.auth` erweitert
- Akzeptanzkriterien nachweislich erfuellt

## Konzept-Referenzen

- FK-15 (`concept/technical-design/15_security_secrets_identity_zugriffsmodell.md`) §15.10 — normative Auth-Festlegung
- FK-72 (`concept/technical-design/72_frontend_architektur.md`) §72.8 — BFF-URL-Konvention
- FK-91 (`concept/technical-design/91_api_event_katalog.md`) — API-Vertrag, Korrelations-Konvention

## Guardrail-Referenzen

- ZERO DEBT: keine TODOs, keine "spaeter sauber"-Loesungen
- FAIL CLOSED: bei fehlendem/ungueltigem Auth-Token immer 401, keine Fallbacks
- SINGLE SOURCE OF TRUTH: Tokens leben gehasht in `project_api_tokens`, kein Schattenfeld
- MOCKS NUR IM AUSNAHMEFALL: echte httpx-/TestClient-basierte Tests, keine ueberzogenen Mocks
