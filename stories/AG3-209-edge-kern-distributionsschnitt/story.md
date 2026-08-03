# AG3-209 — Edge, Kern und Wire-Vertrag in einem atomaren Distributionsschnitt

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-208"]`
- **Quell-Konzept:** das in AG3-208 nachgezogene FK-10-Zielbild, FK-01
  (Trust Boundaries), FK-30 (lokale Guard-Engine), FK-07 §7.7-§7.9
- **Herkunft:** PO-Entscheidung vom 2026-08-03,
  `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md`;
  technische Umsetzung des normativen Schnitts aus AG3-208.

## Kontext

### Der Ist-Zustand ist nicht nur ein Importproblem

`pyproject.toml:74-80` baut heute ein Wheel `agentkit` aus dem gesamten
`src/agentkit` und liefert drei Scripts daraus. Die 40 in AG3-208 vollstaendig
inventarisierten Kanten aus `harness_client` greifen auf 20 Backend-Module zu:
25 DTO-/Vertragskanten, 9 Engine-Kanten und 6 Hilfsfunktionskanten. In der
Gegenrichtung importieren vor allem Guard-Engine, Installer und gemischte CLI
den ProjectEdge-Client und Harness-Writer.

Das bildet die echte Laptop-Laufzeit ab:

- `agentkit-hook-claude` ruft bei
  `harness_client/harness_adapters/claude_code.py:283` lokal
  `Governance.run_hook(...)` auf; der Sammel-Hook ruft bei `:379`
  `evaluate_pre_tool_use(...)` auf.
- `agentkit-hook-codex` ruft bei
  `harness_client/harness_adapters/codex/cli.py:58` lokal dieselbe
  Guard-Engine auf.
- der deployte Launcher
  `bundles/target_project/tools/agentkit/projectedge.py:251-332,369-405`
  fuehrt Story-Reconciliation und Edge-Commands lokal aus; seine
  `backend/story_creation`-Engine wird bei `:284-287,540-544` gebaut und bei
  `harness_client/projectedge/client.py:973` ausgefuehrt.
- Projektregistrierung, Hook-/MCP-Materialisierung, Update und Detach liegen
  unter `backend/installer`, laufen aber auf dem Entwicklerrechner.

Darum gibt es keinen verantwortbaren Teilschnitt „erst Modelle“, „spaeter
Engine“, „spaeter Installer“ oder „spaeter Gate“. Jeder solche Commit liesse
entweder beide Importwege aufloesbar, ein nicht installierbares Edge-Wheel oder
eine nur konventionelle Grenze zurueck. Analog AG3-182 wird die gesamte
Import-/Namespace-Migration in **einem** landbaren Zug vollzogen.

### AG3-129 bleibt die Datenebenen-Grundlage

AG3-129 (`completed`) hat Guard-Counter, Worker-Health und Telemetrie ueber die
bestehende ProjectEdge-/Governance-REST-Strecke vermittelt. Die neue
Edge-Distribution uebernimmt diesen Client und die hook-seitigen REST-Adapter;
die Kern-Distribution behaelt HTTP-Routen, Services und Postgres-Repositories.
Der Schnitt baut weder neue Endpunkte noch einen zweiten HTTP-Transport und
enthaelt niemals einen Direkt-DB-Fallback.

### Auswirkungen auf bestehende Storys

| Story | Bewertung dieses Schnitts |
|---|---|
| **AG3-189** (`ready`) | Bleibt in der Invariante gueltig: Installationen muessen isoliert und Entry Points an ihren echten Interpreter gebunden sein. Der Ein-Artefakt-Wortlaut („ein AK3-Interpreter“ fuer CLI, Installer, Git-, MCP- und Harness-Hooks; `pyproject.toml` als ein Build) ueberlappt aber die hier erfolgende Aufteilung und kann nach dem Schnitt nur **pro Deployment-Artefakt** gelesen werden. AG3-209 haengt nicht von AG3-189 ab und setzt sie nicht um; der PO muss entscheiden, ob ihr Briefing vor Umsetzung angepasst wird. |
| **AG3-206** (`ready`) | Bleibt in der Invariante gueltig: deklarierte und importierbare Abhaengigkeiten brauchen einen Owner und eine venv. Ihr heutiger Singular `pyproject.toml`/„AK3 und seine Abhaengigkeiten“ wird durch drei getrennte Dependency-Metadaten konkretisiert. AG3-209 besitzt die Partition und deren Build-Gate; AG3-206 besitzt weiterhin Preflight, venv-Verweigerung und Hook-Fehler-Sichtbarkeit. Keine Dependency in beide Richtungen; landet 206 zuerst, migriert AG3-209 ihren Preflight ohne zweiten Pfad. |
| **AG3-187** (`blocked`) | Der Golden Path muss kuenftig mindestens zwei getrennte Installationen/Umgebungen (Core und Edge, plus Vertrag transitiv) und die ausschliesslich ausgehende Edge->Core-Verbindung aufbauen. Der gezielte Clean-Edge-Hook-Nachweis dieser Story ersetzt nicht AG3-187s vollstaendigen Fremdinstallationsweg. Der bestehende Storyschnitt muss vom PO gegen das neue FK-10-Zielbild bewertet werden; AG3-209 aendert ihn nicht. |
| **AG3-193** (`blocked`) | Liefert das Muster „erst Bestand restlos schneiden, dann Gate ohne Ausnahmeliste“. Hier darf das Distribution-Gate wegen der PO-Entscheidung §3.3 jedoch nicht in eine spaetere Story: Schnitt und Gate landen gemeinsam. AG3-209 kopiert nicht das Anti-Compat-Gate und haengt nicht von AG3-193 ab; es uebernimmt dessen baseline-freie Negativtest-Disziplin fuer eine andere Invariante. |

## Scope

### In Scope

- Drei installierbare Artefakte gemaess AG3-208 bauen: Edge, Kern und ein
  kleines Vertragspaket. Jedes Artefakt besitzt eigene Paket-Metadaten,
  Runtime-Dependencies, Wheel-Inhalte und Entry Points.
- Alle produktiven Module in ihre normative Auslieferungsheimat verschieben:
  insbesondere Guard-Runner/-Evaluation und hook-seitige Guards/REST-Adapter,
  Story-Creation, ProjectEdge-Code, lokale Provider-Port-Anteile, Installer und
  Bediener-CLI zum Edge; Control-Plane, kanonische Services/Persistenz und
  Kern-CLI zum Kern; ausschliesslich beidseitige Wire-Modelle zum
  Vertragspaket. `frontend`, `integration_clients`, `bundles`, der Paket-Root
  und jede bis dahin hinzugekommene Deployment Unit werden gemaess der
  AG3-208-Matrix mitgeschnitten; nichts bleibt nur deshalb in beiden Wheels,
  weil es heute unter dem gemeinsamen `src/agentkit` liegt.
- Die 40 Vorwaertskanten, alle in AG3-208 inventarisierten Gegenkanten, die
  zusaetzlichen Backend-Importe im deployten Target-Project-Launcher und alle
  Aufrufstellen in `src/`, `tests/`, `scripts/` und paketierten Assets im
  selben Zug migrieren. Alte Modulpfade werden geloescht, nicht re-exportiert.
- Entry-Point-/CLI-Schnitt aus AG3-208 umsetzen. Jedes Verb und jedes Script
  wird genau von seiner Distribution geliefert; keine Distribution installiert
  fremde Entry Points.
- Installer, Update/Detach, Hook-Registrierung, MCP-Registrierung,
  ProjectEdge-Launcher und `bundles/target_project` auf die Edge-Distribution
  und deren Interpreter/Modulpfade umstellen.
- Dependency-Mengen entlang tatsaechlicher Import-Reachability partitionieren.
  Core-only Dependencies sind nicht transitive Dependencies des Edge-Wheels;
  Edge-only Dependencies sind nicht transitive Dependencies des Core-Wheels;
  das Vertragspaket hat nur die fuer seine Blattmodelle notwendigen
  Dependencies.
- Test-Layout und Testkonfiguration auf die drei Artefakte ausrichten, ohne die
  volle Monorepo-Suite als Ersatz fuer Wheel-/Clean-Install-Nachweise zu lesen.
- Ein blockierendes Distribution-Boundary-Gate samt Wheel-, Metadata-,
  Import-Reachability- und Clean-Install-Pruefung im selben Diff einfuehren.

### Out of Scope

- Die PO-Entscheidung oder eine Ein-Distributions-Variante neu bewerten —
  **kein Owner, entschieden**.
- Alte Imports, CLI-Namen oder Modulpfade uebergangsweise erhalten — **kein
  Owner, durch Anti-Compat-Grundregel verboten**.
- Neue Governance-/Control-Plane-Fachlogik oder neue REST-Endpunkte — **Owner:
  jeweiliger BC und eigene Story bei einem belegten Gap**.
- AG3-189s globale Installationsverweigerung und Interpreter-SSOT vollstaendig
  implementieren — **Owner: AG3-189**. Diese Story stellt nur sicher, dass ihre
  neuen Artefakte keine Einheitsdistribution voraussetzen.
- AG3-206s Transcript-Aggregator und generischen Dependency-Preflight bauen —
  **Owner: AG3-206**. Diese Story besitzt nur korrekte Metadaten und den
  distributionsspezifischen Build-/Install-Nachweis.
- Den vollstaendigen Fremdinstallations-Golden-Path mit Erstzugang, Token,
  erstem Commit und Idempotenzlauf bauen — **Owner: AG3-187**. Der hier
  geforderte echte Hook ist der engere Realitaetsnachweis des
  Distributionsschnitts.
- Ein generisches Anti-Compat-Gate bauen — **Owner: AG3-193**.
- Bestehende Storys umschneiden, umpriorisieren oder auf `superseded` setzen —
  **Owner: Product Owner**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| Paket-/Build-Metadaten (`pyproject.toml` und die in AG3-208 bestimmte Monorepo-Struktur) | geaendert/neu | drei Wheels, drei Dependency-Mengen, eindeutige Entry Points |
| `src/agentkit/harness_client/**` bzw. normative Edge-Heimat aus AG3-208 | verschoben/geaendert | Harness-Adapter, ProjectEdge, Guard-Engine, Story-Creation, lokaler Installer/CLI-Anteil |
| `src/agentkit/backend/**` | verschoben/geaendert | nur Kerncode verbleibt; Edge-Code und Wire-DTOs verlassen den Kern |
| normative Contract-Heimat aus AG3-208 | neu | kleines I/O-freies Wire-Vertragspaket |
| `src/agentkit/bundles/target_project/**` | geaendert | Launcher-, Hook-, MCP- und Interpreterpfade zeigen ausschliesslich auf Edge |
| `src/agentkit/backend/installer/**` bzw. neue Edge-Heimat | verschoben/geaendert | Projektinstallation ist Laptop-Laufzeit |
| `src/agentkit/backend/cli/**` bzw. getrennte Edge-/Kern-CLI-Heimaten | verschoben/geaendert | kein gemeinsamer eager Dispatcher ueber beide Artefakte |
| `concept/formal-spec/architecture-conformance/**` | ggf. synchron nachgezogen | die in AG3-208 normierten Pfade muessen zum realen Schnitt passen; keine neue Grundentscheidung |
| `scripts/ci/check_distribution_boundaries.py` | neu | blockierendes Artefakt-/Import-/Dependency-Gate |
| `Jenkinsfile`, `.githooks/pre-commit` | geaendert | Gate im Pflichtlauf; nicht gelaufen ist nie PASS |
| `tests/{unit,integration,contract,e2e}/**` | verschoben/geaendert/neu | Imports, Distributionstestkontexte, Clean-Install- und echte Hook-Nachweise |
| `PROJECT_STRUCTURE.md` | nur falls Pfadkorrektur noetig | format-/locator-treuer Nachzug zum in AG3-208 bereits entschiedenen Zielbild |

## Akzeptanzkriterien

1. **Drei echte Artefakte:** Aus einem sauberen Checkout werden exakt die in
   AG3-208 benannten Edge-, Kern- und Contract-Wheels gebaut. `wheel RECORD`,
   `METADATA`, `Requires-Dist` und Console-Scripts entsprechen jeweils ihrer
   Ownership-Matrix. Weder Edge noch Kern packt den Quellbaum der anderen
   Distribution mit ein.
2. **Ein atomarer Import-/Namespace-Schnitt:** Alle 40 Vorwaertskanten, alle
   Gegenkanten und alle Target-Project-Launcher-Importe sind auf ihre neue
   Heimat migriert. Kein alter produktiver Modulpfad loest noch auf; ein
   Negativtest importiert repraesentative entfernte Engine-, DTO- und
   Helper-Pfade und erwartet `ModuleNotFoundError`. Es gibt keinen Re-Export,
   Alias, Shim, `deprecated`-Pfad oder Commit mit beiden Wegen.
3. **Guard-Engine bleibt Edge-seitig und echt:** Beide installierten
   Hook-Scripts normalisieren ihr Harness-Payload und fuehren dieselbe lokale,
   harness-neutrale Guard-Engine aus. Guard-Counter, Worker-Health und
   Telemetrie gehen weiter ueber den AG3-129-REST-Transport; ein statischer und
   dynamischer Nachweis zeigt, dass aus dem Hook-Prozess weder `psycopg` noch
   ein Postgres-Repository erreichbar ist.
4. **Kern und Vertrag sind reachability-sauber:** Kein Modul im gebauten
   Kern-Wheel importiert Edge; kein Contract-Modul importiert Edge oder Kern,
   oeffnet I/O oder zieht Engine-/Installer-Code transitiv nach. Edge und Kern
   teilen produktiven Python-Code ausschliesslich ueber das Vertragspaket.
5. **Dependencies folgen dem Laufzeitbesitzer:** Fuer jede bisherige
   `pyproject.toml`-Runtime-Dependency dokumentiert der Implementierungsnachweis
   den importierenden Artefaktpfad. Eine als `core-only` klassifizierte
   Distribution/Dependency fehlt nach normaler Installation aus `pip list` und
   `importlib.metadata` der Edge-venv; umgekehrt fuer `edge-only` in der
   Kern-venv. `pip check` ist in allen drei Umgebungen gruen. Eine
   handgepflegte zweite Dependency-Liste ausserhalb der Build-Metadaten ist
   unzulaessig.
6. **Entry Points, Installer, Bundle und MCP schneiden gemeinsam um:** Alle
   heutigen Console-Scripts und CLI-Verben werden exakt von der in AG3-208
   bestimmten Distribution geliefert. `register-project`, Update/Detach,
   Hook-/MCP-Registrierung und der deployte ProjectEdge-Launcher funktionieren
   mit dem Edge-Interpreter und enthalten keinen alten Backend-Modulpfad.
   `serve` und andere Kernprozesse starten ohne installierte Edge-Distribution.
7. **Benanntes Pflicht-Gate `check_distribution_boundaries.py`:** Das Gate
   prueft mindestens (a) AST-/Import-Reachability zwischen Quell-Deployment-
   Units, (b) Wheel-Inhalte, (c) `Requires-Dist`-Closure, (d) Installation aus
   einem lokalen Wheelhouse, das fuer Edge nur Edge+Contract enthaelt, und (e)
   den echten Hook-Prozess. Es laeuft blockierend in Jenkins und lokal im
   Pflichtpfad, hat keine Baseline/Ausnahmeliste und meldet SKIP/ABORT/NOT_RUN
   als Fehler, niemals PASS.
8. **Gate-Negativbeweise:** Drei nacheinander konstruierte und wieder
   zurueckgenommene Mutationen machen das Gate rot: (a) Edge importiert ein
   Kernmodul, (b) Edge deklariert eine core-only Dependency, (c) das Contract-
   Paket importiert eine Engine. Diff, Kommando und Finding-Code jeder Mutation
   liegen im Story-Record.
9. **Realitaetsnachweis auf einer kernfreien Edge-Maschine:** In einer neuen
   Windows-venv und einer neuen macOS-venv wird die Edge-Distribution normal
   aus den gebauten Wheels installiert; die Kern-Distribution und alle nach
   AG3-208 core-only klassifizierten Pakete sind nachweislich nicht installiert.
   Ein auf einem separaten, vom Laptop nur ausgehend erreichbaren Host
   installierter Kern lauscht auf seiner echten HTTP-Schnittstelle; ein
   in-process oder in derselben venv gestarteter Kern erfuellt dieses Kriterium
   nicht.
   Aus jeder Edge-venv wird mindestens ein echter Claude- und ein echter
   Codex-Hook per Console-Script mit realem stdin ausgefuehrt; die lokale
   Guard-Entscheidung und der AG3-129-HTTP-Hop sind im Beleg sichtbar. Kein
   Import-Pfad, Mock, Test-Client oder in-process Kern ersetzt diesen Lauf.
10. **Netzrichtung ist real:** Der Kern initiiert keine Verbindung zum Laptop.
    Der Realitaetsnachweis laeuft mit einer Edge-Umgebung ohne eingehenden
    Listener/Port und belegt ausschliesslich Edge->Kern-HTTP. Ein unerreichbarer
    Kern erzeugt beim kanonischen Guard-Vorgang den normierten fail-closed
    Ausgang; es gibt keinen lokalen Ersatzstate.
11. **Test-Layout beweist Artefakte:** Unit-/Integration-/Contract-Tests sind
    dem Artefaktbesitzer zugeordnet. Mindestens eine Teststufe importiert jedes
    gebaute Wheel aus einer installierten venv statt ueber den Repository-
    Source-Root. Die volle bestehende Suite bleibt gruen; verschobene Tests
    werden nicht geloescht oder durch schmalere Duplikate ersetzt.
12. **Versions- und Handshake-Vertrag:** Client-Versionsermittlung (heute
    `harness_client/projectedge/client.py:72-82` mit `_PACKAGE_NAME =
    "agentkit"`) liest die in AG3-208 bestimmte Edge-Distribution. Edge,
    Contract und Kern melden/validieren die beschlossene Release-
    Kompatibilitaet ohne hardcodierten Einheits-Paketnamen oder parallelen
    Fallback.
13. **Qualitaetsgates:** Volle Suite und Coverage >=85 %, `ruff`, `mypy`
    strict fuer `win32`, `linux` und `darwin`, alle deterministischen Konzept-
    und Architektur-Gates sowie das neue Distribution-Gate gruen. Jenkins ist
    gruen; Sonar hat `violations=0`, `critical_violations=0`,
    `security_hotspots=0`.
14. **Unabhaengiges Review bis zum Abbruchkriterium:** Ein anderer Principal
    prueft ueber die benannten Achsen hinaus insbesondere Contract-Bloat,
    versehentliche transitive Kerninstallation, tote/duplizierte Entry Points,
    alte Importauflosung, Windows/macOS-Verhalten und Ehrlichkeit des
    Clean-Install-Nachweises. Findings werden an der Wurzel behoben und erneut
    vorgelegt.

## Definition of Done

- AC 1-14 erfuellt, jeweils mit Kommando, Artefaktpfad, Testname oder
  Reviewbeleg.
- Die drei gebauten Wheels und ihre geprueften `METADATA`-/`RECORD`-Inventare
  sind im Story-Record referenziert; keine Build-Artefakte liegen unkontrolliert
  im Repo.
- Windows- und macOS-Clean-Edge-Protokoll aus AC 9 enthaelt `pip list`,
  `pip check`, Kern-Abwesenheitsassertion, Console-Script-Pfade, stdin,
  Exit-Code und HTTP-Nachweis.
- Die drei Gate-Mutationen aus AC 8 sind dokumentiert und vollstaendig
  zurueckgenommen.
- `.venv\Scripts\python -m pytest`, `ruff`, `mypy`, alle deterministischen
  Konzept-/Architektur-Gates, Jenkins und Sonar sind gruen.
- Unabhaengiges Codex-Review erreicht eines der Abbruchkriterien aus
  `CLAUDE.md`.
- Kein bestehender Story-Status wird durch diese Story eigenmaechtig geaendert.

## Offene Fragen an den Product Owner

Keine neuen. AG3-209 startet erst, nachdem AG3-208 die drei dort benannten
PO-Fragen beantwortet und die Antworten normativ verankert hat. Taucht bei der
Umsetzung eine neue Grundentscheidung ohne Anker auf, stoppt die Story und legt
genau diese Frage dem PO vor; sie wird nicht durch einen Packaging-Default
ersetzt.

## Konzept-Referenzen

- `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md`
- das durch AG3-208 aktualisierte
  `concept/technical-design/10_runtime_deployment_speicher.md`
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md`
- `concept/technical-design/30_hook_adapter_guard_enforcement.md`
- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
- `concept/formal-spec/architecture-conformance/`
- `PROJECT_STRUCTURE.md`

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS“ — AC 2 und 6;
  der Schnitt erfolgt in einem Zug.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT“ — genau eine Code-,
  Metadata-, Dependency- und Entry-Point-Heimat.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN“ — AC 9/10; die
  fehlende Kerninstallation ist der Beweisgegenstand.
- `CLAUDE.md` „NO ERROR BYPASSING“ — kein Direkt-DB-/Source-Root-/Mock-Ersatz.
- AG3-193 als Muster fuer baseline-freie, blockierende Negativbeweise; keine
  fachliche Dependency.
