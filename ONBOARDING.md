# AgentKit 3 — Onboarding & Handover

> **Zweck:** Von „Repo ist noch nicht geklont" bis „ich kann weiterarbeiten" auf
> einem frischen Rechner. Enthaelt: Klonen, Toolchain, Infrastruktur außenrum,
> MCP-Server, wo die User-Stories liegen, Arbeitsweise und den **aktuellen
> Arbeitsstand** (Stand: 2026-05-31).
>
> Die normative Wahrheit bleibt `CLAUDE.md`, `PROJECT_STRUCTURE.md` und
> `concept/`. Dieses Dokument ist eine Einstiegshilfe + datierter Status-Snapshot.

---

## 1. Was ist AgentKit 3?

Deterministische Orchestrierungsmaschine fuer KI-gestuetzte Story-Abarbeitung.
AK3 ist ein **Meta-Harness**: er erweitert den Agent-Harness (Claude Code / Codex)
um prozessuale und Governance-Capabilities (Story-Pipeline, 4-Schichten-QA,
Guards, Telemetrie, Closure), damit Agents grosse Projekte hochautomatisiert
umsetzen. Details: `CLAUDE.md` (Kernauftrag) + `concept/domain-design/00-uebersicht.md`.

---

## 2. Repository klonen

```bash
git clone https://github.com/saltenhof/claude-agentkit3.git
cd claude-agentkit3
```

- **Default-Branch:** `main` (wir committen direkt auf `main`).
- Git-User dieser Arbeit: `StefanAltenhof`.

> **WICHTIG (Pfad-Annahmen):** Einige Tool-/MCP-Konfigurationen sind aktuell auf
> den absoluten Pfad `T:/codebase/claude-agentkit3` gepinnt (siehe `.mcp.json`).
> Auf dem neuen Rechner den Pfad dort anpassen (siehe §6).

---

## 3. Toolchain (Voraussetzungen)

| Tool | Version | Zweck |
|---|---|---|
| **Python** | **>= 3.12** | Laufzeit (`requires-python = ">=3.12"`) |
| **git** | aktuell | VCS |
| **GitHub CLI `gh`** | optional | PR-/Issue-Operationen, einige Tests `requires_gh` |
| PowerShell 7+ **oder** bash | — | Dev-Umgebung (Windows: PowerShell; Skripte auch bash-kompatibel) |

Optionale Python-Extras (nur wenn genutzt): `weaviate-client`, `mcp[cli]`.

---

## 4. venv + Installation

> **KRITISCH — niemals global installieren.** AK3 und AK2 teilen denselben
> Package-Namen `agentkit`. Ein globaler Install ueberschreibt AK2 und zerstoert
> dessen Claude-Code-Hooks. **Alle** Python-Befehle ausschliesslich ueber das
> Projekt-venv.

```bash
# venv anlegen (einmalig)
python -m venv .venv

# editable install inkl. dev-Extras
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows
# .venv/bin/python   -m pip install -e ".[dev]"      # Linux/macOS
```

`.venv/` ist git-ignoriert. Auf dem neuen Rechner frisch anlegen, nicht kopieren.

---

## 5. Zielprojekt mit AgentKit initialisieren

Dieser Abschnitt beschreibt das Onboarding eines Zielprojekts, nicht das Setup
dieses AK3-Entwicklungsrepos.

Pflicht-Voraussetzungen fuer einen produktiven `agentkit install`:

- Das AK3-venv muss aktuell installiert sein:
  `.venv/Scripts/python -m pip install -e ".[dev]"`.
- `AGENTKIT_STATE_BACKEND=postgres` und `AGENTKIT_STATE_DATABASE_URL=...`
  muessen in der Shell gesetzt sein. Die lokale `.env` wird nicht implizit
  geladen.
- Wenn Sonar/Jenkins fuer das Zielprojekt als verfuegbar deklariert sind, muss
  die Shell auch die passenden Endpunkte und Secrets enthalten:
  `SONAR_URL`, `SONAR_USER`, `SONAR_PASSWORD` oder alternativ
  `SONARQUBE_TOKEN`/`SONAR_TOKEN`, sowie `JENKINS_URL`, `JENKINS_USER` und
  `JENKINS_API_TOKEN` oder `JENKINS_PASSWORD`.
- Fuer den Sonar-Branch-Plugin-Self-Test muss der konfigurierte Jenkins-Job den
  CP10d-Self-Test-Modus unterstuetzen und auf seinem Agent den SonarScanner
  ausfuehren koennen. Der Installer-Rechner braucht keinen lokalen
  `sonar-scanner`. Fehlt der Jenkins-Pfad, scheitert CP 10d fail-closed; ein
  Opt-out mit `--no-sonarqube-available` ist nur fuer Projekte korrekt, bei
  denen Sonar bewusst nicht anwendbar ist.

Single-Repo mit optionaler Default-Struktur:

```bash
.venv/Scripts/agentkit install \
  --project-key my-project \
  --project-name "My Project" \
  --project-root /path/to/project \
  --github-owner my-org \
  --github-repo my-project \
  --default-project-structure
```

Multi-Repo verlangt explizite Code-Repositories; der Installer erfindet keine
Unterordner unter `codebase/`:

```bash
.venv/Scripts/agentkit install \
  --project-key my-project \
  --project-name "My Project" \
  --project-root /path/to/project \
  --github-owner my-org \
  --github-repo my-project \
  --default-project-structure \
  --multi-repo \
  --code-repo frontend=https://github.example/my-org/frontend.git \
  --code-repo backend=https://github.example/my-org/backend.git
```

`agentkit doctor --project-root /path/to/project` prueft die lokale CLI-Sicht auf
das Zielprojekt.

---

## 6. Standardbefehle nach Codeaenderungen

```bash
.venv/Scripts/python -m pytest                 # Tests (unit/integration/contract; e2e nur opt-in)
.venv/Scripts/python -m mypy src               # strict, ohne unerklaerte type: ignore
.venv/Scripts/python -m ruff check src tests   # ohne unerklaerte noqa
```

- **Coverage-Gate: >= 85%** (`pyproject.toml [tool.coverage.report] fail_under = 85`).
- Test-Ebenen: `tests/unit/`, `tests/integration/`, `tests/contract/`,
  `tests/e2e/` (e2e nie Standard-CI).
- Ruff line-length 130, target py312. mypy strict + pydantic-Plugin.

---

## 7. MCP-Server

| MCP | Konfiguriert in | Zweck |
|---|---|---|
| **agentkit3-concepts** | `.mcp.json` (Repo-Ebene) | Semantische Suche ueber `concept/` (FK/DK/formal). **Primaer statt grep auf Konzepte.** |
| **multi-llm-hub** | Session/global | Sparring/Reviews via ChatGPT, Gemini, Grok, Qwen, Kimi (Browser-Pools) |
| **codex-bridge** | Session/global | Giftige Codex-Reviews + Story-Vorlagen |

### 7.1 agentkit3-concepts MCP auf einem neuen Rechner verfuegbar machen

Der Server (`tools/concept_mcp/server.py`) ist ein hybrider (BM25 + Vektor)
Index ueber `concept/`, gespeichert in **Weaviate**. Vektorisiert wird
**serverseitig in Weaviate** ueber das Modul `text2vec-transformers` (kein
Client-seitiges Embedding). Drei Bausteine:

**(a) Weaviate mit `text2vec-transformers`** — die eigentliche Infra-Abhaengigkeit.
- Lokal erwartet auf **HTTP `9903`**, **gRPC `50051`** (Defaults; override via
  `AK3_WEAVIATE_HOST` / `AK3_WEAVIATE_HTTP_PORT` / `AK3_WEAVIATE_GRPC_PORT`).
- Weaviate-Image mit **aktivem Modul `text2vec-transformers`** + ein
  transformers-inference-Container mit **multilingualem** Modell (Korpus ist
  DE+EN). Referenz-Stand der aktuellen Maschine: Weaviate **1.36.4**.
- docker-compose-Eckwerte: `ENABLE_MODULES=text2vec-transformers`,
  `DEFAULT_VECTORIZER_MODULE=text2vec-transformers`,
  `TRANSFORMERS_INFERENCE_API=http://<inference-host>:8080`, Port-Mapping
  `9903:8080` (HTTP) + `50051:50051` (gRPC). Inference-Image z.B.
  `semitechnologies/transformers-inference` mit einem multilingual-Modell
  (z.B. multilingual-e5 / paraphrase-multilingual-MiniLM).

**(b) Python-Umgebung fuer den Server** — `.mcp.json` startet
`python -m tools.concept_mcp.server`. Diese Umgebung braucht **nicht** die volle
agentkit-Installation, nur:
```bash
pip install "mcp[cli]" weaviate-client pyyaml
```
> Das ist NICHT `pip install -e .` von agentkit. Die AK2/AK3-Namenskollision
> (§4) betrifft nur das `agentkit`-Paket, nicht mcp/weaviate/pyyaml. Sauberste
> Variante: ins **venv** installieren und `.mcp.json` aufs venv-Python zeigen (c).

**(c) `.mcp.json` anpassen** (liegt im Repo-Root, wird von Claude Code beim Start
im Repo automatisch erkannt):
```json
{ "mcpServers": { "agentkit3-concepts": {
    "command": "<klon>/.venv/Scripts/python",
    "args": ["-m", "tools.concept_mcp.server"],
    "cwd": "<lokaler-klon-pfad>" } } }
```
→ `cwd` MUSS der lokale Klon-Pfad sein (der Server importiert `tools.*` relativ
dazu). `command` = venv-Python (empfohlen) oder `"python"`, falls mcp+weaviate
global liegen. Alternativ via CLI: `claude mcp add`.

**(d) Index befuellen** (einmalig, sobald Weaviate laeuft + leer ist):
```bash
<klon>/.venv/Scripts/python -m tools.concept_ingester.cli full     # Schema + Vollingest
<klon>/.venv/Scripts/python -m tools.concept_ingester.cli status   # local vs. remote counts
```
Alternativ zur Laufzeit ueber das MCP-Tool `concept_ingest(strategy="full")`,
Kontrolle mit `concept_status()`. Nach Konzept-Aenderungen reicht `delta`.

**Env-Variablen** (alle mit Default, nur bei abweichendem Setup setzen):
`AK3_WEAVIATE_HOST`=127.0.0.1 · `AK3_WEAVIATE_HTTP_PORT`=9903 ·
`AK3_WEAVIATE_GRPC_PORT`=50051 · `AK3_CONCEPT_COLLECTION`=Ak3ConceptChunk ·
`AK3_CONCEPT_CHUNK_MAX`=12000.

**Smoke-Test:** `... cli status` zeigt remote-Counts > 0; dann im Agent
`concept_search(query="ProjectionAccessor", limit=3)`.

---

## 8. LSP / Code-Intelligence (basedpyright) auf neuem Rechner

Claude Code zeigt beim Editieren von `.py` live `<new-diagnostics>` getaggt
`(basedpyright)`. **Verifizierter Mechanismus auf diesem Rechner** (Claude Code
**2.1.158**): Claude Codes **eingebaute** Code-Intelligence-Auto-Discovery
erkennt `basedpyright-langserver` auf dem PATH und startet ihn als internen
Inline-Server `basedpyright-python-inline`. Es ist **KEIN** Marketplace-Plugin
installiert (`~/.claude/plugins/installed_plugins.json` listet nur skill-creator/
codex/codex-bridge), und **kein** `ENABLE_LSP_TOOL` gesetzt (ab Claude Code
v2.0.74 default-on).

### Replikation (Windows)
```powershell
# 1) Claude Code aktuell (>= 2.0.74; hier 2.1.158)
claude --version          # ggf. claude update

# 2) basedpyright GLOBAL installieren -> legt basedpyright-langserver auf den PATH
pip install basedpyright  # in die globale Python-Installation, NICHT nur ins venv

# 3) verifizieren, dass der Langserver gefunden wird
where.exe basedpyright-langserver
#   erwartet z.B. C:\Program Files\Python314\Scripts\basedpyright-langserver

# 4) Claude Code im Repo starten, eine .py-Datei oeffnen -> Diagnostics erscheinen.
#    Inline ansehen: Ctrl+O. Diagnose bei Problemen: claude doctor  /  /status
```
> Wichtig: `basedpyright-langserver` muss in der **PATH-Python-Umgebung** liegen
> (global), damit die Auto-Discovery ihn unabhaengig vom Projekt-venv findet.

### Alternative (falls Auto-Discovery in einer Version mal nicht greift)
Offizielles Marketplace-Plugin `pyright-lsp` (nutzt Microsofts `pyright`, nicht
basedpyright): in einer Claude-Code-Session `/plugin install pyright-lsp@claude-plugins-official`,
dann `pyright` global installieren (`pyright-langserver` auf PATH). Der offizielle
Marketplace fuehrt `*-lsp`-Plugins fuer viele Sprachen (pyright, typescript, rust-analyzer, …).

---

## 9. Infrastruktur außenrum (Services)

AK3 nutzt im Vollbetrieb mehrere lokale Dienste. **Credentials sind lokal/
umgebungsspezifisch und stehen NICHT im Repo** — aus deinem lokalen Secret-Setup
beziehen bzw. beim Aufsetzen neu vergeben.

| Dienst | Rolle | Default-Host (lokal) | Hinweise |
|---|---|---|---|
| **PostgreSQL** | **Kanonisches** State-Backend (DK-05/FK-18) | lokal | `AGENTKIT_STATE_BACKEND=postgres`, `AGENTKIT_STATE_DATABASE_URL=postgresql://…` |
| **SQLite** | Test-paralleles Backend, **nur** enge Unit-Tests | Datei | Fail-closed gated: `AGENTKIT_ALLOW_SQLITE=1` |
| **Weaviate** (VektorDB) | Story-Knowledge-Base (FK-13), nur `features.vectordb` | lokal | Optional je Projektprofil (`core` vs. `are`) |
| **Jenkins** | CI / Pipeline-Build | `http://127.0.0.1:9900` | Job `claude-agentkit3`; Trigger via Crumb-Cookie (siehe unten) |
| **SonarQube** | Quality-Gate (muss **gruen** sein, nicht „accepted") | `http://localhost:9901` | Projektschluessel `claude-agentkit3` |
| **Multi-LLM-Hub** | LLM-Pools fuer Reviews/Bewertungen | MCP `127.0.0.1:9600` | Browser-Pools 9100/9200/9300/9400 |

### Persistenz-Konvention (wichtig)
**Postgres ist kanonisch; SQLite nur test-parallel** (fail-closed ueber
`AGENTKIT_ALLOW_SQLITE=1`). Schema-Definitionen werden **symmetrisch** in
`src/agentkit/backend/state_backend/postgres_schema.sql` (+ `postgres_store.py`) und
`sqlite_store.py` gehalten. Niemals eine zweite operative Wahrheit einfuehren.

### Jenkins-Build triggern (Crumb-Cookie-Muster)
```bash
CRUMB=$(curl -s -u <user>:<pass> -c jc.txt \
  "http://127.0.0.1:9900/crumbIssuer/api/json" \
  | python -c "import sys,json;print(json.load(sys.stdin)['crumb'])")
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -u <user>:<pass> -b jc.txt -H "Jenkins-Crumb: $CRUMB" \
  -X POST "http://127.0.0.1:9900/job/claude-agentkit3/build"   # erwartet HTTP 201
rm -f jc.txt
```

### Sonar Quality-Gate pruefen
```bash
curl -s -u <user>:<pass> \
  "http://localhost:9901/api/qualitygates/project_status?projectKey=claude-agentkit3"
# Helfer: scripts/python/wait_for_sonar_quality_gate.py
```

### CI-Gates (laufen in Jenkins, lokal nachstellbar)
`scripts/ci/`:
- `check_concept_frontmatter.py` — Frontmatter-Konsistenz der Konzepte
- `check_concept_code_contracts.py` — Konzept↔Code-Vertraege
- `check_architecture_conformance.py` — **AC001–AC008** (BC-Importgrenzen!)
- `compile_formal_specs.py` — formal-spec-Kompilierung

Architecture-Conformance (AC001 = kein Cross-BC-Import auf nicht-exponierte
Subkomponenten) ist auch als pytest abgedeckt:
`tests/unit/tools/concept_compiler/test_architecture_conformance*.py`.

> **Hinweis:** `.env.example` und `Makefile` existieren, sind aktuell aber leer
> (Platzhalter). Env-Variablen direkt in der Shell setzen.

---

## 10. Wo liegen die User-Stories?

- **Verzeichnis:** `stories/` — eine Story je Ordner `AG3-NNN-<slug>/` mit
  `story.md` (Scope, AKs, DoD) + `status.yaml` (status, depends_on, unblocks).
- **Operative Arbeitsliste (autoritativ):**
  `stories/_bearbeitungsreihenfolge.md` — Reihenfolge der aktuellen Welle, wird
  nach jeder abgenommenen Story gepflegt.
- Weitere Steuerdateien: `stories/_story-schnitt-aus-themen.md` (depends_on-Graph),
  `stories/_priorisierungsempfehlung.md`, diverse `*-gap-analyse.md`.

Stories AG3-001 … AG3-049 sind angelegt. Konzepte dazu: `concept/technical-design/`
(FK-XX), `concept/domain-design/` (DK-XX), `concept/formal-spec/` (maschinenpruefbar).

---

## 11. Arbeitsweise (eingespielter Loop)

Pro Story, **streng der Reihe nach** gemaess `_bearbeitungsreihenfolge.md`:

1. **Feasibility zuerst** — relevante FK/DK lesen (via concepts-MCP), Ist-Zustand,
   Delta, Design-Entscheidung. Konzepttreue ist Pflicht; bei Konflikt hart stoppen.
2. **Worker** (oft Sonnet-Sub-Agent, Hintergrund) setzt um. Erste Briefing-Zeile
   immer: `Read T:/codebase/claude-agentkit3/CLAUDE.md first`.
3. **Trust-but-verify** — Worker-Diff pruefen, Pflichtbefehle selbst fahren
   (pytest/mypy/ruff/Coverage + Architecture-Conformance).
4. **Commit** (logisch geschnitten) → **Push** auf `main`.
5. **Jenkins** triggern → **Sonar** genuin gruen verifizieren (nicht „accepted").
6. **Giftige Codex-Review** (liest FKs): „Solange Codex relevante Punkte findet,
   ist es nicht durch."

Guardrails (aus `CLAUDE.md`): ZERO DEBT · FIX THE MODEL, NOT THE SYMPTOM ·
SINGLE SOURCE OF TRUTH · FAIL-CLOSED · NO ERROR BYPASSING · Severity PASS/WARNING/ERROR.

---

## 12. Aktueller Arbeitsstand (Stand: 2026-05-31)

### Letzte Commits auf `main`
```
a7e4ea0  Konzept: neue BC harness-integration (FK-76), §30.11 nach FK-76 verlagert
2d0d23c  AG3-049: Story re-scoped auf FK-76 + Codex-Auflagen (.codex/hooks.json)
db5396c  AG3-035: ProjectionAccessor + run-scoped Reset-Purge (FK-69)
d93c0ee  AG3-031 Hotfix: Hook-Identitaet auf 4-Tupel (matcher+command) — Governance-Loch
```
Arbeitsbaum **clean**, alles gepusht.

### Welle (aus `_bearbeitungsreihenfolge.md`)
| # | Story | Status |
|---|---|---|
| 1 | AG3-026 VerifySystem Top-Surface | ✅ done |
| 2 | AG3-029 KpiAnalytics | ✅ done |
| 3 | AG3-030 RequirementsCoverage | ✅ done |
| 4 | AG3-027 Skills Top-Surface | ✅ done |
| 5 | AG3-031 Governance Top-Surfaces (+ Hotfix) | ✅ done |
| 6 | **AG3-035 ProjectionAccessor + Reset-Purge** | ✅ done (2026-05-31) |
| 7 | **AG3-040 Postgres-Store-Komplettierung** | 🟢 **naechste WIP** |
| 8 | AG3-028 FailureCorpus (Vollumsetzung) | nach 035/040 |
| 9 | AG3-048 Skills-Persistenz + Installer | nach 027 |
| 10 | AG3-049 Codex-Harness-Adapter | nach FK-76 / 031 |

### Architektur-Grossentscheidung dieser Session
Neue **Bounded Context `harness-integration` (FK-76)**: die harness-spezifische
Anbindung (Claude Code/Codex — Adapter, CLI-Wrapper, Settings-Schemas
`.claude/settings.json` + `.codex/hooks.json`, Lifecycle) wurde aus FK-30
(governance-and-guards) herausgeloest. FK-30 behaelt nur die harness-neutrale
Hook-/Guard-Definition + Enforcement. §30.11 ist nach FK-76 verlagert
(korpusweiter Verweis-Sweep erledigt). Sparring ChatGPT/Grok/Qwen + ChatGPT-
Freigabe mit eingearbeiteten Auflagen.

---

## 13. Offene Punkte / noch nicht erledigte QS

| Punkt | Status | Detail |
|---|---|---|
| **AG3-035 Jenkins/Sonar gruen** | offen | Build nach `a7e4ea0` getriggert (HTTP 201); Sonar-Quality-Gate noch verifizieren |
| **AG3-035 giftige Codex-Review** | offen | FK-lesende Codex-Review (FK-69/FK-29/FK-39) noch nicht gefahren |
| **AG3-049 Worker beauftragen** | offen | Story re-scoped + von Codex „Segen mit Auflagen"; wartet bewusst auf FK-76-Basis. Reihenfolge: AG3-040/028/048 zuerst |
| **Code-Migration harness_adapters → harness_integration** | offen (optional) | `agentkit.harness_client.harness_adapters.*` → `agentkit.harness_integration.*` (Paketname = BC-Name). Rein kosmetisch; BC-Zugehoerigkeit + Importrichtung sind bereits via FK-76 normativ. Eigene Folge-Story |
| **Concept-Index Re-Ingest** | offen | Nach FK-76 + §30.11-Sweep: concepts-MCP `concept_ingest`, damit die Suche FK-76 + neue Verweise kennt |
| **AG3-028 ↔ AG3-040 Zyklus** | beachten | Aufloesung: AG3-040 in zwei Sub-Bloecken (ohne fc_-Tabellen zuerst). Siehe `_bearbeitungsreihenfolge.md` Anmerkung 1 |

### Naechster sinnvoller Schritt
1. AG3-035 final abschliessen: Sonar gruen pruefen + giftige Codex-Review.
2. Dann **AG3-040** (Postgres-Store-Komplettierung) als naechste WIP starten —
   liefert u.a. `Telemetry.write_projection` produktiv, Voraussetzung fuer AG3-028.

---

## 14. Schnell-Referenz Konzepte

- `CLAUDE.md` — Projektregeln, Kernauftrag, Guardrails (OVERRIDE-Prioritaet).
- `PROJECT_STRUCTURE.md` — verbindliche Verzeichnisstruktur + Modulgrenzen.
- `concept/_meta/bc-cut-decisions.md` — Bounded-Context-Schnitt-Entscheidungen.
- `concept/technical-design/_meta/{bounded-contexts,domain-registry}.yaml` — BC-Katalog.
- Zentrale FKs: FK-27 (QA-Subflow), FK-30 (Hooks/Enforcement), FK-69 (QA-Read-Models/
  ProjectionAccessor), FK-29 (Closure), FK-39 (Phase-State), **FK-76 (Harness-Integration, neu)**,
  FK-50 (Installer), FK-11/FK-75 (LLM-Provider/Multi-LLM-Hub).
- **Konzeptsuche immer ueber den `agentkit3-concepts`-MCP**, nicht grep.
