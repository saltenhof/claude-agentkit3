# AG3-208 AC 7 — Ist-Realitaetsnachweis der Einheitsdistribution

Datum: 2026-08-07. Plattform: Windows 11, Python 3.14.3.
Zweck: den **Ist-Zustand** messen, nicht ihn pruefen. Ein rotes Ergebnis ist
das erwartete Ergebnis.

Arbeitsverzeichnis der Wegwerf-Umgebung: `var/ag3-208-realitaetsnachweis/`
(gitignored, wegwerfbar).

## 1. Kommandos

```bash
# 1) Heutiges Einzel-Wheel bauen (in-tree PEP-517-Backend)
.venv/Scripts/python.exe -m pip wheel --no-deps \
  --wheel-dir var/ag3-208-realitaetsnachweis/wheel .

# 2) Zuvor leere venv erzeugen
py -3.14 -m venv var/ag3-208-realitaetsnachweis/venv

# 3) Ausgangsinventar der leeren venv
var/ag3-208-realitaetsnachweis/venv/Scripts/python.exe -m pip list --format=freeze

# 4) Nur das Wheel installieren, Abhaengigkeiten von PyPI aufloesen
var/ag3-208-realitaetsnachweis/venv/Scripts/python.exe -m pip install --no-cache-dir \
  var/ag3-208-realitaetsnachweis/wheel/agentkit-0.1.0-py3-none-any.whl

# 5) Inventar nach der Installation
var/ag3-208-realitaetsnachweis/venv/Scripts/python.exe -m pip list --format=freeze

# 6) ECHTER Hook-Prozess mit realem stdin, in einem fremden Projektverzeichnis
printf '%s' '{"session_id":"ag3-208-proof","transcript_path":"C:/tmp/t.jsonl",
  "cwd":"<fake-project>","hook_event_name":"PreToolUse","tool_name":"Bash",
  "tool_input":{"command":"git status"}}' \
  | var/ag3-208-realitaetsnachweis/venv/Scripts/agentkit-hook-claude.exe pre branch_guard
```

Gebautes Wheel: `agentkit-0.1.0-py3-none-any.whl`, **3 608 461 Bytes**,
sha256 `d1a7b3469f2c0439fd7caea562b065b6fe5e9ddf4619af2a15bbe27fc44ff86d`.

## 2. Environment-Inventar

**Vor der Installation** — die venv enthaelt genau eine Distribution:

```
pip==25.3
```

**Nach der Installation** — 56 Distributionen plus `pip` (57 Zeilen):

```
agentkit==0.1.0            annotated-types==0.8.0     anyio==4.14.2
argon2-cffi==25.1.0        argon2-cffi-bindings==25.1.0  attrs==26.1.0
Authlib==1.7.2             certifi==2026.7.22         cffi==2.1.1
charset-normalizer==3.4.9  click==8.4.2               colorama==0.4.6
cryptography==50.0.0       filelock==3.32.2           fsspec==2026.7.0
grpcio==1.78.0             h11==0.16.0                httpcore==1.0.9
httpx==0.28.1              httpx-sse==0.4.3           huggingface_hub==0.36.2
idna==3.18                 joserfc==1.7.4             jsonschema==4.26.0
jsonschema-specifications==2025.9.1                   mcp==1.29.0
packaging==26.3            pip==25.3                  protobuf==6.33.6
psutil==7.2.2              psycopg==3.3.4             psycopg-binary==3.3.4
psycopg-pool==3.3.1        pycparser==3.0             pydantic==2.13.4
pydantic-settings==2.14.2  pydantic_core==2.46.4      PyJWT==2.13.0
python-dotenv==1.2.2       python-multipart==0.0.32   pywin32==312
PyYAML==6.0.3              referencing==0.37.0        requests==2.34.2
rpds-py==2026.6.3          sse-starlette==3.4.8       starlette==1.4.1
tokenizers==0.21.0         tomlkit==0.15.1            tqdm==4.70.0
typing-inspection==0.4.2   typing_extensions==4.16.0  tzdata==2026.3
urllib3==2.7.0             uvicorn==0.52.1            validators==0.35.0
weaviate-client==4.22.0
```

**Anwesenheit der Kern-Dependencies belegt** (importiert in derselben venv):

```
psycopg      PRESENT 3.3.4
psycopg_pool PRESENT 3.3.1
weaviate     PRESENT 4.22.0
mcp          PRESENT
tokenizers   PRESENT 0.21.0
uvicorn      PRESENT 0.52.1
starlette    PRESENT 1.4.1
```

**Console-Scripts, die das eine Wheel erzeugt:**

```
agentkit.exe   agentkit-hook-claude.exe   agentkit-hook-codex.exe
```

`agentkit-are-mcp` fehlt — der Installer registriert dieses Kommando
(`backend/core_types/mcp_server_registration.py`), aber `[project.scripts]`
erzeugt es nicht.

## 3. Echter Hook-Lauf

**Lauf 1 — `agentkit-hook-claude pre branch_guard`, realer stdin:**

```
(keine Ausgabe auf stdout/stderr)
EXIT=0
```

Exit 0 = ALLOW. Der Hook hat die Entscheidung tatsaechlich getroffen; es ist
kein Import- oder Startfehler.

**Lauf 2 — derselbe Wrapper ohne Argumente (Argumentvertrag):**

```
Usage: agentkit-hook-claude {pre|post} {hook_id}
EXIT=2
```

## 4. Was der Hook-Prozess laedt

Gemessen in derselben venv, in einem fremden Projektverzeichnis, indem
`claude_code.main(["pre","branch_guard"])` bzw. `main_project_edge([])` mit
realem stdin ausgefuehrt und danach `sys.modules` ausgewertet wurde.

| Messgroesse | `main` (`pre branch_guard`) | `main_project_edge` (Sammel-Hook, Tool `Read`) |
|---|---:|---:|
| `agentkit.*`-Module geladen | **294** | **292** |
| `agentkit.backend.*`-Subpakete geladen | **23** | **23** |
| Drittbibliotheken geladen (beobachtete Liste, siehe Abschnitt 5) | `pydantic`, `yaml` | `pydantic`, `yaml` |

Die 23 geladenen Backend-Subpakete:

```
artifacts, boundary, code_backend, config, control_plane, core_types,
exceptions, execution_planning, governance, installer, phase_state_store,
pipeline_engine, process, prompt_runtime, state_backend,
story_context_manager, story_creation, story_exit, story_reset, story_split,
telemetry, utils, verify_system
```

Darunter geladen — Auszug, vollstaendig gemessen:

- `verify_system` **komplett**: `sonarqube_gate.*` (16 Module),
  `llm_evaluator.*` (14), `adversarial_orchestrator.*`, `policy_engine.*`,
  `qa_cycle.*`, `stage_registry.*`, `evidence.*`
- `state_backend.store`, `state_backend.telemetry_event_store`,
  `state_backend.state_backend_connection_manager`
- `control_plane.models`, `control_plane.push_sync`, `control_plane.ownership`
- `installer.interpreter`, `installer.paths`

Ein PreToolUse-Hook auf einem `Read` laedt damit den SonarQube-Gate-Code und
den LLM-Evaluator.

## 5. Praezisierung einer kursierenden Behauptung

Die AG3-230-Feasibility (2026-08-06) behauptet, der PreToolUse-Hook laedt bei
jedem Read/Grep den Postgres-Treiber ueber die Kette
`… → state_backend/store/control_plane_writer_lease.py:32 import psycopg`.

**Das ist widerlegt.** Der Import an dieser Stelle steht unter
`if TYPE_CHECKING:` (`control_plane_writer_lease.py:27–32`) und wird zur
Laufzeit nicht ausgefuehrt.

**Praezisierung der Belegform (Review-Befund).** Die Messung in Abschnitt 4
prueft eine **hartcodierte Beobachtungsliste** ohne `pydantic_core` und
`typing_extensions`; sie belegt streng genommen nur „unter den beobachteten
direkten Abhaengigkeiten". Das ist als Widerlegung zu schwach. Die
Nachmessung arbeitet deshalb **ohne Allowlist**: `sys.modules` nach dem
echten Hooklauf, abzueglich `sys.stdlib_module_names` und `agentkit`.
Vollstaendiges Ergebnis — **9** Nicht-stdlib-Top-Level-Module:

```
annotated_types, cython_runtime, pydantic, pydantic_core,
pywin32_bootstrap, pywin32_system32, typing_extensions,
typing_inspection, yaml
```

Diese Liste ist erschoepfend, nicht gefiltert; `psycopg` ist nicht darin.
Unabhaengig bestaetigt durch eine AST-Erreichbarkeitsanalyse ueber alle
1042 Module (kein modul-level `psycopg`-Import erreichbar).

`psycopg` ist auf der Maschine **installiert**, nicht **geladen**. Der Befund
traegt trotzdem: die Angriffs-, Update- und Wartungsflaeche entsteht durch die
Anwesenheit von 56 Distributionen auf einem Rechner, der die Datenbank nie
sieht — nicht durch den Ladevorgang.

## 6. Bewertung

| Kriterium | Ergebnis |
|---|---|
| Wegwerfbare, zuvor leere venv | erfuellt (nur `pip` vor der Installation) |
| Heutiges Einzel-Wheel installiert | erfuellt (`agentkit-0.1.0`, 3,6 MB) |
| Installierte Distributionen aufgelistet | erfuellt (56 + `pip`) |
| Anwesenheit der Kern-Dependencies belegt | erfuellt (`psycopg`, `psycopg-pool`, `weaviate-client`, `tokenizers`, `uvicorn`, `starlette`) |
| Echter Hook-Prozess mit realem stdin | erfuellt (`agentkit-hook-claude pre branch_guard`, Exit 0) |
| Ergebnis | **rot, wie erwartet** — eine Hook-Installation bringt den vollstaendigen Kern mit |
