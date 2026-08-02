# AG3-187 — Fremdinstallations-Golden-Path aus leerer Umgebung

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-180", "AG3-188", "AG3-189"]`
- **Quell-Konzept:** FK-10 (Runtime/Deployment), FK-15 (Zugriffsmodell),
  FK-22 (Preflight/Checkpoints), FK-13 (Retrieval/MCP), FK-44 (Prompt-Bundles)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-3 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

## Kontext

### Befund

Am 2026-08-02 wurde AK3 zum ersten Mal in ein fremdes Projekt installiert. Es
funktionierte nicht — an mehreren voneinander unabhaengigen Stellen, von denen
**jede einzelne** durch eine gruene Suite gedeckt schien:

| Defekt | Warum ihn niemand sah |
|---|---|
| Kein Weg zu einem Projekt-Token | `set_password()` wird ausschliesslich aus Tests aufgerufen; die Suite erschafft sich ihre Voraussetzung selbst |
| `control-plane.json` zeigte auf Port `9080` | ein Compat-Alias hielt den Legacy-Port am Leben; die Portmigration auf `9702` erreichte den Installer nie (`CLAUDE.md`, Anlassfall) |
| MCP-Server startete nicht | fehlende Interpreterbindung — behoben in `01a27de1` |
| Jeder Commit starb an einem fehlenden Import | Git-Hooks riefen `python` vom PATH — behoben in `cb3662c4`; der zugehoerige Test *verlangte* dieses Verhalten sogar |
| Startzertifikat ohne SAN | jede Anleitung mit `127.0.0.1` schlug fehl |

Die sieben Storys aus Commit `77b4b034` adressieren diese Defekte einzeln.
**Keine von ihnen besitzt den durchgehenden Produktpfad.** Damit bleibt genau
die Lage bestehen, die den 2026-08-02 erzeugt hat: jeder Teil ist gruen, das
Produkt ist nicht installierbar. Ein Zusammenbau, den niemand als Ganzes faehrt,
ist keine Faehigkeit, sondern eine Vermutung.

### Warum ein Ausschnitt nicht genuegt

Die drei Defekte, die am teuersten waren — Prompt-Bundle-Version,
MCP-Interpreter, Git-Hook-Interpreter — haben eine gemeinsame Eigenschaft: sie
sind **Bindungen zwischen zwei Bausteinen**, nicht Fehler in einem. Ein Test,
der einen Baustein prueft, kann sie strukturell nicht finden. Nur der Lauf, der
alle Bausteine in ihrer echten Reihenfolge benutzt, findet sie.

## Scope

### In Scope

Ein einziger, wiederholbarer Lauf aus einer **leeren Umgebung** durch den
vollstaendigen Produktpfad:

1. saubere Maschine / leere Umgebung (kein `~/.config/agentkit`, keine Token,
   kein Startvertrauen, kein globales `agentkit` im `site-packages`)
2. isolierte AK3-Installation (AG3-189)
3. Core starten (AG3-188: Startvertrauen; Hochfahrreihenfolge)
4. Erstzugang (AG3-180)
5. Projekt-Token ausstellen (AG3-180)
6. Fremdprojekt registrieren
7. **alle** Installer-Checkpoints durchlaufen
8. erster Commit im Fremdprojekt mit echten, aktiven Hooks
9. zweiter, idempotenter Lauf auf derselben Installation

Der Lauf erfasst dabei ausdruecklich mit: **Prompt-Bundle-Version,
MCP-Interpreter und Git-Hook-Interpreter** — die drei realen Tagesdefekte.

### Out of Scope

- Die Behebung einzelner Defekte, die dabei auffallen. Die gehoert in die
  jeweilige Fach-Story; hier entsteht der **Nachweis**, nicht der Fix.
- Die Fremdsystem-Vertragsmatrix und die E2E-Spitze je Fremdsystem —
  **AG3-183**. Diese Story ist der Produktpfad, nicht die Systematik.
- Mehrbenutzerbetrieb, Remote-Installation, Container-Deployment.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `tests/e2e/install_golden_path/` | neu | der durchgehende Lauf als ausfuehrbarer Nachweis |
| `tests/e2e/conftest.py` | geaendert | Umgebungs-Isolation (HOME/`AGENTKIT_AUTH_CONFIG`/`site-packages`) |
| `src/agentkit/backend/installer/` | geaendert | Checkpoints liefern maschinenlesbare Ergebnisse fuer den Lauf |
| `concept/technical-design/22_setup_preflight_worktree_guard_activation.md` | geaendert | Checkpoint-Liste des Golden Path normativ verankern |
| `concept/_meta/decisions/2026-XX-XX-golden-path.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `docs/` bzw. der Ort, an dem ein Mensch die Inbetriebnahme sucht | neu/geaendert | die Reihenfolge, der jemand ohne Vorwissen folgen kann |

## Akzeptanzkriterien

1. **Der Lauf existiert als ein einziger ausfuehrbarer Vorgang** und faehrt alle
   neun Stationen in dieser Reihenfolge. Er ist kein Skript, das neun
   unabhaengige Tests hintereinander startet: eine spaetere Station benutzt
   ausschliesslich das, was eine fruehere erzeugt hat.
2. **Der Startzustand ist beweisbar leer.** Der Lauf beginnt mit einer
   Umgebung ohne `~/.config/agentkit`, ohne Token, ohne Startvertrauen und ohne
   globales `agentkit` im `site-packages` — und er **prueft** das, statt es
   vorauszusetzen. Ein Lauf, der auf einer vorbereiteten Maschine gruen wird,
   erfuellt dieses Kriterium nicht.
3. **Der Lauf beruehrt kein Interna.** Zwischen den Stationen wird nichts per
   Python-Einzeiler, Dateieingriff oder DB-Manipulation nachgeholfen. Jede
   Station benutzt ausschliesslich Oberflaechen, die ein Bediener hat.
4. **Alle Installer-Checkpoints laufen und ihr Ergebnis ist einzeln sichtbar.**
   Ein uebersprungener, abgebrochener oder nicht gefahrener Checkpoint ist im
   Ergebnis von einem bestandenen unterscheidbar. Ein Lauf, in dem ein
   Checkpoint fehlt, ist rot — nicht gruen mit weniger Zeilen.
5. **Der erste Commit im Fremdprojekt gelingt mit echten, aktiven Hooks.**
   Nachgewiesen an einem tatsaechlich erzeugten Commit in einem Repository
   ausserhalb dieses Repos, mit `core.hookspath` gesetzt. Kein Simulieren des
   Hook-Aufrufs.
6. **Die drei Tagesdefekte sind namentlich abgedeckt und einzeln nachweisbar:**
   - **Prompt-Bundle-Version:** der Lauf stellt fest, welche Bundle-Version
     materialisiert wurde, und weist eine Abweichung vom Pin als Fehler aus.
   - **MCP-Interpreter:** der registrierte MCP-Server startet im Fremdprojekt
     tatsaechlich und antwortet — nicht „der Eintrag steht in der Konfiguration".
   - **Git-Hook-Interpreter:** der Hook laeuft korrekt, **obwohl** ein falsches
     `python` im PATH steht.
   Fuer jeden der drei ist per Mutation belegt, dass der Lauf rot wird, wenn man
   den zugehoerigen Fix zurueckdreht.
7. **Der zweite Lauf ist idempotent und das ist gemessen:** kein neues
   Geheimnis, kein neues Startvertrauen, keine doppelte Registrierung, keine
   veraenderte Konfiguration. Nachgewiesen ueber einen Vorher-/Nachher-Vergleich
   der erzeugten Artefakte, nicht ueber „es lief wieder durch".
8. **Der Lauf ist ehrlich, wenn er nicht laufen kann.** Faellt eine
   Voraussetzung aus (Dienst nicht verfuegbar, Umgebung im Umbau), ist das eine
   **benannte Luecke mit Grund** im Ergebnis — nie ein stilles Ueberspringen und
   nie „gruen". Diese Aussage ist getestet, nicht nur behauptet.
9. **Die Inbetriebnahme-Reihenfolge steht dort, wo ein Mensch sie sucht**, und
   ist von jemandem ohne Vorwissen nachvollzogen worden. Der Nachweis benennt,
   wer sie gefahren hat und wo er haengengeblieben ist.
10. **Konzept nachgezogen** (FK-22 Checkpoint-Liste) mit Decision Record und
    Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–10 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Der Golden-Path-Lauf ist mindestens einmal vollstaendig gegen eine echte
  leere Umgebung gefahren; Kommando und Ausgabe liegen im Story-Record.
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Alle deterministischen Konzept-Gates gruen; Decision Record im Diff oder
  gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/22_setup_preflight_worktree_guard_activation.md` —
  Preflight und Checkpoints
- `concept/technical-design/10_runtime_deployment_speicher.md` —
  Hochfahrreihenfolge, Ablageorte
- `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md` —
  Erstzugang und Token
- `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` —
  MCP-Auslieferung ins Zielprojekt
- `concept/technical-design/44_prompt_bundles_materialization_audit.md` —
  Prompt-Bundle-Pinning und Materialisierung

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — dies ist der
  Realitaetsnachweis des Produkts selbst.
- `CLAUDE.md` „FAIL-CLOSED" — AC 4 und AC 8.
- `CLAUDE.md` „MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL" — AC 3 und AC 5.
- `PROJECT_STRUCTURE.md` §tests — E2E-Ebene; die Verbindlichkeitsstufe in der
  CI entscheidet **AG3-194**, nicht diese Story.
