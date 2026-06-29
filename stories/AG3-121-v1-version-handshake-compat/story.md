# AG3-121: `/v1` Versions-Handshake (dev↔central) — `GET /v1/compat` + `426` fail-closed

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `control_plane_http` (BFF/Transport, cross-cutting) + `harness_client` (Project-Edge-Client). Die `/v1`-Grenze zwischen Dev-Maschine (Ebene 2/3) und zentralem Kern (Ebene 1) ist heute ein **statischer** Praefix ohne Aushandlung. FK-91 §91.1a Regel 11 und FK-10 §10.2.7/§10.2.8 verlangen einen Versions-Handshake: jeder Dev→Control-Plane-Request fuehrt die Agent-Runtime-Version und das gebundene Skill-Bundle als Header; der Kern prueft gegen ein Fenster `[min, max]`, annonciert `recommended`/`blocked` und blockt Inkompatibles fail-closed mit `426 Upgrade Required`. Ein `GET /v1/compat`-Endpunkt liefert das Fenster lesbar.

**Quell-Konzepte (autoritativ):**
- `FK-91 §91.1a Regel 11` — Versions-Handshake (dev↔central): Header `X-AK3-Client` + `X-AK3-Skill-Bundle`; Pruefung gegen `[min, max]`; `recommended`/`blocked`; **inkompatibel = fail-closed `426 Upgrade Required`** (Runtime unter `min`, in `blocked`, nicht unterstuetzte Wire-Version, fehlender Handshake an mutierenden/Governance-Endpunkten); Runtime unter `recommended` aber im Fenster = WARNING (`91_api_event_katalog.md:180-191`). Der Fehlervertrag folgt `FK-91 §91.1a Regel 7/8` (Correlation-Pass-through, `error_code`/`error`/`correlation_id`).
- `FK-91 §91.1a` — Endpoint `GET /v1/compat`: „Unterstuetztes Versionsfenster lesen: `min`/`recommended`/`blocked` fuer Agent-Runtime und Wire (dev↔central-Handshake, FK-10 §10.2.7)" (`91_api_event_katalog.md:107`).
- `FK-10 §10.2.7` — Versionsvertraege und Kompatibilitaet: drei Versions-Achsen (Agent-Runtime, Skill-/Prompt-Bundle, Wire `/v1`); dev↔central-Kompatibilitaet wird ueber `/v1` verhandelt (`10_runtime_deployment_speicher.md:468-492`).
- `FK-10 §10.2.8` — Update-Treibermodell + Reaktionsmatrix: `ERROR/fail-closed (z. B. HTTP 426)` vs. `WARNING (Request laeuft)` (`10_runtime_deployment_speicher.md:494-524`).

---

## 1. Kontext / Ist-Zustand (belegt)

> Re-verifiziert gegen den aktuellen Code. Befund deckt sich mit WP-G: alle drei Teile (Endpoint, Client-Header, Server-Validierung) **ABSENT**.

- **G1 — `GET /v1/compat` fehlt vollstaendig:** `src/agentkit/backend/control_plane_http/app.py` routet nur `/healthz` (`:480`, `_handle_healthz` `:267`), `/v1/telemetry/events` (`:752`) und `/v1/project-edge/sync` (`:754`) direkt, plus den BC-Router; eine `compat`-Route existiert nicht (Grep `compat` trifft nur den Modul-Docstring `:4` „compat re-export"). Project-Edge-Operationen-Pattern `:67`.
- **G2 — Client sendet keine Version:** `src/agentkit/harness_client/projectedge/client.py:113` setzt als Request-Header ausschliesslich `{"Content-Type": "application/json"}` und reicht (Regel #7) nur den Correlation-Header durch (`:114-120`). Kein `X-AK3-Client`, kein `X-AK3-Skill-Bundle`.
- **G3 — Keine Server-Validierung / kein `426`:** In `control_plane_http/app.py` gibt es keine Versions-Middleware vor dem Routing (`:480` ff. dispatcht direkt); kein `426`-Statuscode im Backend; die Tenant-Scope-Middleware (`control_plane_http/tenant_scope.py`) prueft Projekt-Existenz/Archiv, nicht die Client-Version.
- **Folge:** Ein zu altes oder in `blocked` liegendes Dev-Paket kann heute ungehindert gegen einen neuen Kern sprechen — gerade fuer Hook-Code ein fail-open-Risiko, das FK-10 §10.2.8 ausdruecklich ausschliesst („Ein Hook, der seine Kompatibilitaet nicht belegen kann, liefert kein PASS").

## 2. Scope

### 2.1 In Scope

1. **Kompatibilitaets-Fenster als typisiertes Modell:** ein Pydantic-Modell `CompatWindow` (o. Ae.) mit **`min`/`max`/`recommended`/`blocked`** je Achse (Agent-Runtime, Wire `/v1`) — das vollstaendige `[min, max]`-Fenster plus Annonce-Werte (FK-91 §91.1a, FK-10 §10.2.7). Die Werte stammen aus einer zentralen, versionierten Quelle des Kerns (Konfiguration/Konstanten der Control-Plane), **nicht** aus projektlokalem State (FK-10 §10.2.7: Manifest-Autoritaet bleibt zentral). **Wire-Version-Quelle:** der `/v1`-Pfadpraefix ist die getragene Wire-Version; eine nicht unterstuetzte Wire-Version (kein passender Praefix bzw. ausserhalb `[min, max]`) ist fail-closed.
2. **`GET /v1/compat` (read-only, ohne Projekt-Praefix):** liefert das Fenster (`min`/`recommended`/`blocked` fuer Agent-Runtime und Wire) als stabile JSON-Antwort mit `correlation_id` (FK-91 §91.1a). Der Endpunkt ist nicht mutierend und unterliegt **nicht** dem Handshake-Zwang (sonst Henne-Ei).
3. **Server-seitige Handshake-Validierung als Middleware** in `control_plane_http` (vor dem BC-Routing, nach Auth): liest `X-AK3-Client` (Agent-Runtime-Paketversion) und `X-AK3-Skill-Bundle` aus den Request-Headern und entscheidet typisiert entlang der Reaktionsmatrix:
   - **`426 Upgrade Required` (fail-closed):** Runtime unter `min`, Runtime in `blocked`, nicht unterstuetzte Wire-Version, **oder** fehlender Handshake an mutierenden/Governance-Endpunkten.
   - **WARNING (Request laeuft):** Runtime im Fenster aber unter `recommended` → strukturierter Hinweis (Antwort-Header), kein Block.
   - **PASS:** Runtime `>= recommended`.
   Die `426`-Antwort folgt dem stabilen Fehlervertrag (FK-91 §91.1a Regel 8: `error_code`, `error`, `correlation_id`) und annonciert das Fenster.
4. **Antwort-Header-Annonce:** jede Control-Plane-Antwort (bzw. mind. die mutierenden Endpunkte) traegt die `recommended`/`blocked`-Hinweise als Header, damit der Client den Update-Bedarf ohne separaten `compat`-Poll erkennt (FK-10 §10.2.8 „Der Core annonciert, die Dev-Maschine zieht").
5. **Client-seitiger Handshake (G2):** `harness_client/projectedge/client.py` ergaenzt `X-AK3-Client` (eigene Paketversion) und `X-AK3-Skill-Bundle` (gebundene Bundle-Version/-Hash) in `send(...)` (`:113`), ohne den bestehenden Correlation-Pass-through (Regel #7) oder `Content-Type` zu brechen. Die Versionsquelle ist die installierte Paket-Metadaten-Version (kein hartkodierter String).
6. **Handshake-Pflicht-Klassifikation:** mutierende und Governance-Endpunkte erfordern den Header (fehlend → `426`); read-only-Endpunkte und `/healthz`/`/v1/compat` sind ausgenommen. Die Klassifikation ist typisiert (kein String-Flag-Geflecht).

### 2.2 Out of Scope (mit Owner)

- **`agentkit update`-Verb / Update-Treibermechanik** (Ebene-2-Pull, Paket-/Bundle-Update) — **AG3-122** (Install-Trinity-Verben, FK-10 §10.2.8). Diese Story liefert nur die `compat`-Lesefläche + Validierung, nicht das Update-Kommando.
- **Wire-`/v2`-Bruchmechanik** (neuer Praefix bei Vertragsbruch) — FK-10 §10.2.7 hält `/v1` statisch; ein `/v2` ist nicht Teil dieser Story (kein In-Place-Bruch).
- **Tenant-Scope-Middleware** (Projekt-Existenz/Archiv) — bereits vorhanden (`control_plane_http/tenant_scope.py`, AG3-090); die Handshake-Middleware ergaenzt sie, ersetzt sie nicht.
- **Auth-/Identitaets-Vertrag** (dev↔central-Authentifizierung, FK-10 §10.2.10 → **FK-15 §15.10**) — eigener Owner; der Handshake setzt auf den bestehenden Auth-Pfad auf, definiert ihn nicht.
- **Skill-Bundle-Hash-/Signatur-Pruefung** (Integritaetsbruch) — FK-43/FK-44-Owner; hier wird nur die Bundle-**Version** im Handshake gefuehrt, keine Signaturpruefung.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/control_plane_http/` (neues Compat-/Handshake-Modul, z. B. `version_handshake.py` + `CompatWindow`-Modell) | Neu |
| `src/agentkit/backend/control_plane_http/app.py` | Aendern (`GET /v1/compat`-Route + Handshake-Middleware in die Dispatch-Kette ab `:480`) |
| `src/agentkit/harness_client/projectedge/client.py` | Aendern (`X-AK3-Client` + `X-AK3-Skill-Bundle` in `send(...)` `:113`) |
| `tests/unit/control_plane_http/**`, `tests/integration/control_plane_http/**`, `tests/contract/**` | Neu/Aendern (compat-Read, `426`-Negativpfade, WARNING/PASS, Client-Header-Capture, e2e) |

## 3. Akzeptanzkriterien

1. `GET /v1/compat` ist im `control_plane_http`-Routing erreichbar, antwortet read-only mit dem vollstaendigen Fenster **`min`/`max`/`recommended`/`blocked`** (Agent-Runtime + Wire) und traegt eine `correlation_id` (Routing- + Schema-Test). Der Endpunkt verlangt **keinen** Handshake-Header.
2. Server-Handshake fail-closed (`426`): Negativpfad-Tests — Runtime unter `min`, Runtime in `blocked`, **nicht unterstuetzte Wire-Version**, **und** fehlender Handshake an einem mutierenden Endpunkt — liefern je `426 Upgrade Required` mit Fehlervertrag (`error_code`, `correlation_id`) und Fenster-Annonce; die Mutation findet **nicht** statt.
3. **Fehlende Einzel-Header:** fehlt `X-AK3-Client` **oder** `X-AK3-Skill-Bundle` an einem mutierenden/Governance-Endpunkt → `426` (je ein Test pro fehlendem Header). Ein **veraltetes-aber-erlaubtes** Skill-Bundle (im Fenster, aber unter `recommended`) → WARNING (Request laeuft, Hinweis-Header), kein Block.
4. WARNING-Pfad: Runtime im Fenster aber unter `recommended` laeuft durch und traegt einen strukturierten `recommended`-Hinweis im Antwort-Header (Test). PASS-Pfad: Runtime `>= recommended` laeuft ohne Hinweis durch.
5. Der Project-Edge-Client sendet `X-AK3-Client` (installierte Paket-Metadaten-Version) und `X-AK3-Skill-Bundle` (gebundene Bundle-Version) bei jedem `send(...)`. **Echter Client-Test (keine Stub-Absicherung):** der reale `ProjectEdgeClient.send(...)` laeuft gegen eine Request-Capture-Strecke (z. B. lokaler Test-HTTP-Server/Transport-Spy), und der Test belegt die tatsaechlich gesendeten Header — nicht nur ein zusammengebautes Header-Dict; `Content-Type` und der Correlation-Pass-through (FK-91 §91.1a Regel 7) bleiben unveraendert.
6. **End-to-end (echte Routing-Strecke, kein Middleware-Mock):** ein Request mit zu alter Runtime durchlaeuft den realen `control_plane_http`-Dispatch und erhaelt `426`; ein gueltiger Request denselben Pfad und mutiert real. Der Test geht ueber den HTTP-/Routing-Pfad, nicht gegen die Middleware-Funktion isoliert (testing-guardrails §2: keine Stub-Absicherung der zu pruefenden Sache).
7. **ARCH-55:** Header-Namen, `error_code`-Werte, Modellfelder und Bezeichner englisch; keine `noqa`/`type: ignore` ohne Begruendung.
8. **Quality-Gates gruen** (aus Repo-Root, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`, `.venv\Scripts\python -m pytest` (unit/integration/contract), Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`);
   - `.venv\Scripts\python -m mypy src` (strict) **und** `.venv\Scripts\python -m mypy src --platform linux`, `.venv\Scripts\python -m ruff check src tests`;
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`;
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code) — kein Merge bei roten Remote-Gates.

## 4. Definition of Done

- AK 1–8 erfuellt; `/v1/compat` + Handshake-Middleware + Client-Header real verdrahtet (kein 501-Stub, kein fail-open-Default).
- Reaktionsmatrix (`426`/WARNING/PASS) deckungsgleich mit FK-10 §10.2.8 implementiert und getestet; Fenster vollstaendig (`min`/`max`/`recommended`/`blocked`).
- Pflichtbefehle + Konzept-Gates gruen; **Jenkins-Build gruen, SonarQube Zero-Violation gruen** (AC 8); QA-Subflow/Code-Review PASS; Status erst nach belegtem Diff + gruenen Befehlen auf `completed`.

## 5. Guardrail-Referenzen

- **FAIL CLOSED:** Inkompatible/handshake-lose Requests an mutierenden/Governance-Endpunkten werden `426`-geblockt; kein fail-open-Default. „Ein Hook, der seine Kompatibilitaet nicht belegen kann, liefert kein PASS" (FK-10 §10.2.8).
- **SINGLE SOURCE OF TRUTH:** das Kompatibilitaets-Fenster ist zentral (Kern-Konfiguration), nicht projektlokal; der Client spiegelt nur seine eigene Version, definiert das Fenster nicht.
- **TYPISIERT STATT STRINGS:** Fenster, Reaktionsklasse und Handshake-Pflicht sind typisierte Modelle, kein String-/Flag-Geflecht.
- **KEINE FACHLOGIK IN ADAPTERN:** der `harness_client` bleibt duenner Adapter (nur Header setzen); die Entscheidungslogik liegt server-seitig im Kern.
- **ARCH-55:** englische Header-/Feld-/`error_code`-Namen.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Anknuepfungspunkte: Routing/Middleware-Kette in `src/agentkit/backend/control_plane_http/app.py` (Dispatch ab `:480`, BC-Router; Auth + Tenant-Scope sind das Muster fuer die neue Handshake-Middleware in `control_plane_http/tenant_scope.py`-Manier). Client: `src/agentkit/harness_client/projectedge/client.py:113`.
- Reihenfolge: zuerst Fenster-Modell + `GET /v1/compat` (lesbar machen), dann Server-Middleware (`426`/WARNING/PASS), dann Client-Header, dann der e2e-Negativpfad. Henne-Ei beachten: `compat`/`healthz` duerfen den Handshake **nicht** verlangen.
- Versionsquelle: installierte Paket-Metadaten (`importlib.metadata`) fuer `X-AK3-Client`, gebundene Bundle-Version fuer `X-AK3-Skill-Bundle`. Kein hartkodierter Versions-String.
- `.mcp.json`/AK2 NICHT anfassen. Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Testnamen (compat-Read, drei `426`-Negativpfade, WARNING, PASS, Client-Header, e2e), gruene Pflichtbefehle.

## 7. Vorbedingungen

- Keine offenen Abhaengigkeiten (`depends_on: []`). Die BFF-Topologie (`control_plane_http` + Tenant-Scope-Middleware) liegt bereits vor (AG3-090).
- `unblocks`: keine (AG3-122 `agentkit update` referenziert den `compat`-Endpunkt fachlich, ist aber nicht hart blockiert).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed).
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
