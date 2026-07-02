# AG3-146 — Provider-Adapter-Schnitt: schmale Code-Backend-Adapter-Schnittstelle (Capability-Set), git-Protokoll-Präferenz (`ls-remote`), `gh` nur im GitHub-Adapter, Azure-DevOps-Tauglichkeit als Abnahmekriterium

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [] — startbar: Umbau der bestehenden
  Git-/GitHub-Zugriffsschicht auf `main`; braucht weder Ownership-Schema
  noch Command-Queue (GAP §4: ST-16 hat keine eingehenden Kanten; die
  Kanten ST-16 → ST-14a und ST-16 → ST-15 existieren, weil der
  Preflight-Remote-Read in AG3-145 und die Ref-Schutz-Administration in
  AG3-147 diesen Adapter brauchen).
- **Quell-Konzept:** FK-12 §12.1 (Provider-Neutralitäts-Grundsatz,
  Capability-Tabelle „Code-Backend-Feature", Lesen/Verifizieren-Zeile,
  Abgrenzung schreibender Adapter, `gh` nur im Adapter-Rahmen);
  FK-10 §10.2.4-Umfeld (Voraussetzungstabelle: Provider-CLI optional/
  adapter-abhängig, Edge nutzt git-CLI)
- **Herkunft:** GAP-Analyse Session-Ownership v4
  (`_temp/gap-analyse-session-ownership.md`), Story-Kandidat GAP-ST-16;
  normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7 (+ Decision-Records
  unter `concept/_meta/decisions/`, insb. Nachtrag PO-Direktive III in
  `2026-07-02-k1-worktree-topologie.md`).

## Kontext / Problem

PO-Direktive III: AgentKit darf nicht mit GitHub-Spezifika verschraubt
werden (Azure-DevOps-Einsatz geplant); pures git ist unkritisch,
Provider-API-Spezifika sind so schmal wie möglich zu halten und leben nur
hinter einer austauschbaren Adapter-Schnittstelle (FK-12 §12.1). Der
Ist-Zustand (am Code verifiziert 2026-07-02):

- **Es gibt keinen Adapter-Port und kein Capability-Set.** Der
  GitHub-Client ist eine generische `gh`-Kommando-Fassade:
  `integration_clients/github/client.py` — `run_gh` (:135, Aufruf `gh`
  :155), `run_gh_json` (:177), `run_gh_graphql` (:200), Token-Auflösung
  via `gh auth token --user` (:49) und keyring/credentials-file (:34-88).
  Sie ist als Public Surface exportiert
  (`integration_clients/github/__init__.py:18-22`), hat aber **keinen
  produktiven Backend-Konsumenten** — ein API-Versprechen „beliebige
  gh-Kommandos" statt eines definierten, minimalen Capability-Sets.
- **`gh` wird am Client vorbei aufgerufen:** Die Installer-Repo-Probe
  führt einen **eigenen** `gh repo view`-Subprocess aus
  (`backend/installer/repo_probe.py:57` `shutil.which("gh")`, :65
  `["gh", "repo", "view", ...]`); Aufrufer ist Checkpoint CP 2
  (`installer/bootstrap_checkpoints/cp01_to_06.py:78` ff., inkl.
  `gh`-Auth-Fehlerbildern). Provider-Zugriff liegt damit außerhalb jeder
  Kapselung — genau das von SOLL-180 verbotene „Spezifika außerhalb".
- **Es existiert keinerlei backend-seitige Ref-Read-Fläche:** Grep
  `ls-remote`/`ls_remote` über `src/agentkit/`: **null Treffer**. Die von
  FK-12 §12.1 geforderte Lese-/Verifikationsfläche (Ref-Reads,
  Push-Verifikation via git-Protokoll) fehlt vollständig — sie ist die
  Vorbedingung für die serverseitige Push-Verifikation (AG3-147) und den
  Preflight-Remote-Read (AG3-145).
- **GitHub-Kopplung in der Koordinaten-Ableitung:**
  `installer/github_coordinates.py` akzeptiert bewusst nur
  `github.com`-Remotes (:24-44, fail-closed statt Fehl-Attribution) —
  eine dokumentierte, aber unkapselte Provider-Annahme; die
  Registrierungs-Koordinaten (`github_owner`/`github_repo`) ziehen sich
  durch `installer/registration.py`, `paths.py`, `runner.py`.
- **Vereinbar mit dem Zielbild:** Die dev-lokale Git-Mechanik läuft
  bereits über die `git`-CLI (Agent/Edge, FK-12 §12.1-Tabelle); der
  Umbau betrifft die backend-seitigen Provider-Funktionen.

## Scope

### In Scope

1. **Schmale Provider-Adapter-Schnittstelle als Capability-Set**
   (Port im Backend, neuer fachlicher Baustein
   `src/agentkit/backend/code_backend/`): definiertes, **minimales**
   Capability-Set — mindestens: `repo_probe` (Existenz/Erreichbarkeit
   eines Repos), `ref_read` (Head-SHA eines Refs, Basis der
   Push-Verifikation), Compare-/Change-Evidence-Lesefläche auf gepushtem
   Stand (deklariert; produktive Konsumenten folgen in AG3-147 ff.) sowie
   die **deklarierte** Capability `ref_protection_administration`
   (`story/*`-Ref-Schutz) inklusive `capability_supported`-Abfrage — die
   Durchsetzung/Administration selbst liegt in AG3-147. **Keine
   schreibende Merge-Capability** — ein schreibender Code-Backend-Adapter
   ist ausdrücklich ausgeschlossen (SOLL-181; API-Merge nur als späterer
   Strang mit FK-29-Äquivalenznachweis, SOLL-186/KONZEPT-DONE). [SOLL-180]
2. **git-Protokoll-Präferenz:** Die Lese-Capabilities (`ref_read`,
   Push-Verifikations-Read) sind provider-neutral über `git ls-remote`
   implementiert (Netz-Protokoll, kein Worktree, kein physischer
   Repo-Zugriff); Provider-REST/GraphQL nur, wo das git-Protokoll die
   Capability nicht trägt (z. B. Compare-Endpunkte, Ref-Schutz-Admin).
   **AG3-146 stellt die `ls-remote`-Lesefläche;** AG3-145 (Preflight-
   Remote-Read) und AG3-147 (Push-Verifikation/Ref-Schutz) konsumieren
   sie (Kanten existieren jetzt: 145 ← 146, 147 ← 146). Es entsteht
   keine Übergangs-Lesefläche in einer anderen Story. [SOLL-179, SOLL-183]
3. **`gh`-Kapselung:** Sämtliche `gh`-Aufrufe liegen ausschließlich im
   GitHub-Adapter (`integration_clients/github/`): `run_gh`/`run_gh_json`/
   `run_gh_graphql` werden adapter-interne Werkzeuge (kein generischer
   Export als Public Surface mehr); die Installer-Repo-Probe
   (`repo_probe.py`) stellt auf die `repo_probe`-Capability um — der
   direkte `gh`-Subprocess außerhalb des Adapters entfällt. Die
   `gh`-Fehlerbilder aus FK-12 §12.1.2 (Rate-Limit-Retry, Token-Ablauf)
   sind Adapter-Interna des GitHub-Adapters. [SOLL-182]
4. **Provider-CLI optional:** Ein fehlendes `gh` ist kein Crash und keine
   stille Degradation, sondern ein deterministischer, benannter
   Capability-Befund (die betroffene Capability meldet sich als nicht
   verfügbar; Konsumenten entscheiden fail-closed). Die dev-lokale
   Git-Mechanik (Agent/Edge) braucht nie eine Provider-CLI — sie nutzt
   die `git`-CLI. [SOLL-184]
5. **Azure-DevOps-Tauglichkeit als Abnahmekriterium** (PO-Direktive III):
   Die Port-Schnittstelle ist frei von GitHub-Typen/-Annahmen
   (keine `gh`-Argumente, keine GitHub-URL-Formen, keine
   Owner/Repo-Slug-Semantik im Port — Provider-Koordinaten sind ein
   opakes, adapter-eigenes Bindungsdetail); eine Port-Contract-Suite
   läuft gegen jede Implementierung; eine zweite Implementierung
   (Test-Double eines Nicht-GitHub-Providers) besteht sie unverändert.
   Eine dokumentierte Capability-Matrix (GitHub: Rulesets/App-Identität;
   Azure DevOps: Branch-Security/Service-Principal — Mechanik-Hinweise je
   Capability) gehört zum Lieferumfang des Port-Moduls (Docstring).

### Out of Scope (mit Owner)

- **Ref-Schutz-DURCHSETZUNG, Dienst-Identität als Credential-Klasse,
  Edge-Push-Gate, Degradations-WARNING-Betriebsbefund**: **AG3-147**
  (nutzt die hier deklarierte Capability-Schnittstelle).
- **Edge-Command-Queue + Worktree-Ops-Umzug** (inkl. des dortigen
  Preflight-Remote-Reads): **AG3-145** (konsumiert die hier gestellte
  Adapter-Lesefläche; siehe In-Scope 2).
- **Closure-Merge** (kein schreibender Adapter; Ausführungsort Edge):
  **AG3-152**; API-Merge-Strang: SOLL-186, KONZEPT-DONE, kein Code.
- **Registrierungs-Wire-Contract**: `--gh-owner`/`--gh-repo` und die
  persistierten Felder `github_owner`/`github_repo`
  (`installer/registration.py`, `project_registry`) bleiben unverändert —
  GitHub ist Referenz-Provider, die FK-91-CLI-Tabelle führt die Flags
  weiterhin; eine provider-neutrale Registrierungs-Generalisierung ist
  kein Bestandteil des Capability-Schnitts und würde Konzept-Änderungen
  voraussetzen (bei Bedarf eigener Strang).
- **Verlagerung der Verify-/QA-Evidenz auf Adapter-Compare**: **AG3-147**
  (Grenz-Evidenz) bzw. Folgearbeiten des Strangs; diese Story stellt nur
  die Lesefläche bereit.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/code_backend/provider_port.py` (neues Paket `code_backend/`, PROJECT_STRUCTURE-Regel 2: Backend-BCs unter `backend/`) | neu | Port + Capability-Set (Protocol), Capability-Deklarationsmodell (`capability_supported`), typisierte Ergebnisformen (`RefReadResult`, `RepoProbeResult`-Neuform), Capability-Matrix-Doku — Blutgruppe A |
| `src/agentkit/backend/code_backend/git_protocol.py` | neu | Provider-neutrale `git ls-remote`-Implementierung der Lese-Capabilities (Netz-Protokoll; Subprocess-Kapselung) |
| `src/agentkit/integration_clients/github/client.py` | ändern | `run_gh`/`run_gh_json`/`run_gh_graphql`/Token-Auflösung werden adapter-intern; GitHub-Adapter implementiert den Port (dünner Adapter, Fachlogik bleibt im Backend) |
| `src/agentkit/integration_clients/github/__init__.py` | ändern | Public Surface = Port-Implementierung statt generischer `run_gh`-Export |
| `src/agentkit/backend/installer/repo_probe.py` | ändern | Direkter `gh repo view`-Subprocess (:57/:65) → `repo_probe`-Capability über den Port |
| `src/agentkit/backend/installer/bootstrap_checkpoints/cp01_to_06.py` | ändern | CP 2 konsumiert die Capability (Fehlerbilder bleiben fail-closed; `gh`-Spezifika nur noch im Adapter) |
| `src/agentkit/backend/installer/github_coordinates.py` | ändern (minimal) | Kopplungs-Kommentar/Einordnung: Koordinaten-Parsing als GitHub-Adapter-Bindungsdetail ausgewiesen; Verhalten unverändert (fail-closed github.com-only) |
| `src/agentkit/backend/bootstrap/composition_root.py` | ändern | Wiring des produktiven GitHub-Adapters an den Port |
| `tests/unit/code_backend/**`, `tests/contract/**`, `tests/integration/**` | neu | Port-Contract-Suite (läuft gegen GitHub-Adapter UND Nicht-GitHub-Test-Double), `ls-remote`-Lesetests, Capability-Negativtests (`gh` fehlt) |

## Akzeptanzkriterien

1. **Capability-Set statt Kommando-Fassade:** Der Port definiert das
   minimale Capability-Set (repo_probe, ref_read,
   Compare-/Change-Evidence-Lesefläche, deklarierte
   ref_protection_administration mit `capability_supported`); es gibt
   **keine** generische „führe beliebiges Provider-Kommando aus"-Fläche
   und **keine** schreibende Merge-Capability (Code-Beweis: kein
   `run_gh`-Export außerhalb des Adapters).
2. **`ls-remote`-Präferenz:** `ref_read` liefert den Head-SHA eines Refs
   provider-neutral via `git ls-remote` — ohne Worktree, ohne physischen
   Repo-Zugriff (Test gegen ein lokales bare-Repo-Fixture); ein nicht
   auflösbarer Ref/Remote ist ein deterministischer, typisierter Fehler
   (fail-closed, kein leerer Erfolg).
3. **`gh` nur im GitHub-Adapter:** Grep-Beweis über `src/agentkit/`:
   `gh`-Subprocess-Aufrufe existieren ausschließlich unter
   `integration_clients/github/`; `repo_probe.py`/CP 2 laufen über den
   Port (Regressionstest: CP-2-Verhalten — Repo fehlt, `gh` fehlt, Auth
   fehlt — bleibt fail-closed FAILED, nie silent skip).
4. **Provider-CLI optional:** Fehlt `gh`, meldet der GitHub-Adapter die
   betroffenen Capabilities deterministisch als nicht verfügbar
   (benannter Befund); `ls-remote`-Capabilities funktionieren ohne `gh`
   (Negativtest ohne installiertes `gh`).
5. **Azure-DevOps-Tauglichkeit:** Die Port-Contract-Suite läuft
   unverändert gegen den GitHub-Adapter und ein
   Nicht-GitHub-Test-Double; `mypy`-/Signatur-Beweis: keine
   GitHub-spezifischen Typen, Feldnamen oder URL-Annahmen in
   Port-Signaturen; die Capability-Matrix (GitHub/Azure DevOps) ist im
   Port-Modul dokumentiert.
6. **Keine zweite Wahrheit:** Es existiert genau EIN Weg zu
   Provider-Funktionen (der Port); die alte Export-Fläche ist entfernt —
   kein Konsument importiert `run_gh` außerhalb des Adapters
   (Konformanz-Grep).
7. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner, englische
   Capability-/Befund-Codes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-145 und AG3-147); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-179–184.

## Konzept-Referenzen

- FK-12 §12.1 (Provider-Neutralität normativ: GitHub = Referenz-Provider,
  nicht Kopplungsfläche; bevorzugt universelles git-Protokoll —
  `git ls-remote` für backend-seitige Ref-Reads/Push-Verifikation;
  Provider-Funktionen nur über schmale, austauschbare
  Adapter-Schnittstelle mit minimalem Capability-Set; Spezifika nie
  außerhalb; Zielbild Azure DevOps durch Adapter-Tausch; Tabelle
  „Code-Backend-Feature" mit Lesen/Verifizieren-Zeile; kein schreibender
  Adapter — FK-29-Äquivalenznachweis-Vorbehalt; `gh` nur als
  GitHub-Werkzeug im Adapter-Rahmen)
- FK-12 §12.1.2 (GitHub-Fehlerbilder Rate-Limit/Token — Adapter-Interna)
- FK-10 §10.2.4a Ausführungsort-Aufzählung (b) (Ref-Reads/Push-Verifikation
  bevorzugt via provider-neutralem git-Protokoll; Compare via Adapter oder
  Edge-gemeldet) und FK-10 §10.2.4-Umfeld (Voraussetzungen:
  Provider-CLI-Werkzeuge optional/adapter-abhängig; Edge nutzt git-CLI)
- Decision-Record `2026-07-02-k1-worktree-topologie.md`, Nachtrag
  PO-Direktive III (Disposition der Provider-Neutralität)

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Die generische gh-Kommando-Fassade
  wird durch ein typisiertes Capability-Modell ersetzt — nicht um weitere
  Direkt-Subprocesses (wie `repo_probe.py`) ergänzt.
- **SINGLE SOURCE OF TRUTH:** Genau ein Zugangsweg zu Provider-Funktionen;
  keine parallelen `gh`-Pfade neben dem Adapter.
- **FAIL-CLOSED:** Nicht verfügbare Capabilities und nicht auflösbare
  Refs sind benannte Fehler/Befunde, nie stille Degradation; CP 2 bleibt
  fail-closed.
- **Architektur (CLAUDE.md):** `integration_clients/` bleiben dünne
  Adapter — das Capability-Modell und die Entscheidungslogik liegen im
  Backend (`code_backend/`), die Provider-Mechanik im Adapter.
- **MOCKS/STUBS-Regel:** Das Nicht-GitHub-Test-Double ist eine echte
  Port-Implementierung für die Contract-Suite (Austauschbarkeits-Beweis),
  kein Mock produktiver Kernlogik.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Nicht einschlägig — diese Story führt keine neuen
  Tabellen ein (kein Schema-Bezug; explizit geprüft).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Port,
  Capability-Modell und Ergebnistypen (`code_backend/provider_port.py`)
  = **A**; GitHub-Adapter-Mapping (Provider-Antwort ↔ Ergebnistypen)
  = **R**; `ls-remote`-/`gh`-Subprocess-Kapselung (`git_protocol.py`,
  Adapter-Interna) = **T**. Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert:
  `bundles/target_project/tools/agentkit/projectedge.py` enthält keine
  `gh`-Aufrufe und keinen Provider-Zugriff; der Treffer in
  `bundles/skill_bundles/create-userstory-core/4.0.0/SKILL.md:20-21` ist
  eine Negativ-Aussage „NO gh issue create" — kein Asset-Umbau nötig).
