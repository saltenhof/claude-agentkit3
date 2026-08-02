# AG3-188 — Startzertifikat, Trust-Verteilung und Erneuerung

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-187
- **Quell-Konzept:** FK-10 (Runtime/Deployment, Hochfahrreihenfolge),
  FK-15 (Secrets, Schluesselablage)
- **Herkunft:** Erste echte Fremdinstallation am 2026-08-02. Ausgezogen aus
  AG3-180 am 2026-08-02 nach unabhaengigem Codex-Review des Schnitts aus
  Commit `77b4b034` (Auflage ERROR-6).

## Kontext

### Befund — belegt, mit Locator

`agentkit serve` verlangt `--certfile` als Pflichtangabe. Erzeugt wird ein
Zertifikat von **nichts** in AK3 — kein Skript, kein Installer-Schritt, keine
Dokumentation. Unter `var/devcert/` liegt seit dem 2026-06-21 ein handgemachtes
Paar. Es traegt `CN=localhost` und **keine SAN-Erweiterung**; damit verifiziert
ausschliesslich der Name `localhost`. Jede Anleitung, die
`https://127.0.0.1:9702` nennt, schlaegt mit „IP address mismatch" fehl.

Ein Produkt, das TLS verpflichtend fordert, muss sagen koennen, woher das
Zertifikat kommt.

### Was am ersten Schnitt falsch war

Der Schnitt vom 2026-08-02 verlangte, AK3 erzeuge „sein Startzertifikat selbst,
mit `localhost`, `127.0.0.1` und `::1` als SAN". Das ist notwendig und nicht
hinreichend: **ein selbstsigniertes Zertifikat besteht die Pruefung eines
Clients nicht dadurch, dass es die richtigen SAN-Eintraege traegt.** Es fehlt
der Vertrauensvertrag:

- **Wie vertraut ein Client dem Zertifikat?** Selbstsigniert heisst: keine
  bekannte CA. Ohne einen benannten Weg (Trust-Store-Eintrag, `--cacert`,
  `SSL_CERT_FILE`, projektlokale Bindung) schlaegt jede Verbindung mit
  `CERTIFICATE_VERIFY_FAILED` fehl statt mit „IP address mismatch" — der Fehler
  wandert nur.
- **Woher kommt der CA-/Cert-Pfad?** Der Installer, die CLI, der MCP-Server und
  der Harness-Hook sind vier verschiedene Clients. Jeder braucht denselben
  Pfad, und der Pfad braucht einen Eigentuemer.
- **Welche Rechte hat der Private Key?** Ein Startvertrauen, dessen privater
  Schluessel welt-lesbar liegt, ist kein Vertrauen.
- **Wie wird erneuert?** Ein abgelaufenes Zertifikat ist der Regelfall, nicht
  die Ausnahme. Erneuerung, die den laufenden Dienst durch eine halb
  geschriebene Datei schickt, ist ein neuer Ausfallmodus.

## Scope

### In Scope

- Erstgenerierung des Startzertifikats durch AK3 selbst, idempotent.
- Trust-Verteilung an alle AK3-eigenen Clients ueber genau **einen** benannten
  Pfad.
- Dateirechte des privaten Schluessels auf Windows und POSIX.
- Ablauf-Erkennung, Rotation und Erneuerung — atomar.
- Normative Nachfuehrung in FK-10 (Startzertifikat, Ablageort,
  Hochfahrreihenfolge) samt Decision Record.

### Out of Scope

- **Kein Produktionszertifikat und keine PKI.** Das Startzertifikat ist
  ausdruecklich ein Entwicklungs- und Erstinbetriebnahme-Mittel.
- Kein ACME/Let's-Encrypt-Pfad, keine externe CA-Anbindung.
- Der Erstzugang (Passwort/Token) — **AG3-180**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/cli/` (`serve`) | geaendert | `--certfile` bekommt eine Herkunft; Ablauf-/Unbrauchbarkeitsbefund |
| `src/agentkit/backend/` (neues Startvertrauens-Modul) | neu | Erzeugung, Idempotenz, Rotation, Rechte |
| `src/agentkit/backend/installer/` | geaendert | Installer erzeugt/verteilt das Startvertrauen als Checkpoint |
| `src/agentkit/harness_client/`, `src/agentkit/integration_clients/mcp/` | geaendert | Clients beziehen den CA-Pfad aus der einen benannten Quelle |
| `concept/technical-design/10_runtime_deployment_speicher.md` | geaendert | Startzertifikat, Ablageort, Rotation, Hochfahrreihenfolge |
| `concept/_meta/decisions/2026-XX-XX-startzertifikat.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/integration/` | neu | echte TLS-Verbindungen gegen drei Schreibweisen; Rotation unter Last |
| `var/devcert/` | entfernt | handgemachtes Paar vom 2026-06-21 faellt weg; `var/` ist ephemer und nie fachliche Wahrheit |

## Akzeptanzkriterien

1. **Erstgenerierung:** Auf einer Maschine ohne vorhandenes Startvertrauen
   erzeugt AK3 Zertifikat und Schluessel selbst, ohne dass der Bediener ein
   externes Werkzeug aufruft. Nachgewiesen an einem Lauf, bei dem der
   Ablageort vorher leer ist.
2. **Idempotenz:** Ein zweiter Lauf erzeugt **kein** neues Paar und
   ueberschreibt keins. Ein bereits laufender Dienst behaelt sein Vertrauen.
   Nachgewiesen ueber den Fingerabdruck vor und nach dem zweiten Lauf.
3. **Dateirechte des privaten Schluessels** sind auf POSIX (Modus) und auf
   Windows (wirksamer ACL-Eintrag) nachgemessen. Ein Test, der auf Windows nur
   `chmod` aufruft und `st_mode` prueft, erfuellt dieses Kriterium **nicht**.
4. **Client-Bindung:** Es gibt genau **einen** benannten Ort, aus dem jeder
   AK3-eigene Client (CLI, Installer, MCP-Server, Harness-Hook) den
   Vertrauensanker bezieht. Nachgewiesen daran, dass ein Verschieben dieses
   Ortes **alle** Clients gleichzeitig scheitern laesst — nicht drei von vier.
   Kein Client deaktiviert die Zertifikatspruefung, auch nicht per Umgebungs-
   variable, auch nicht „nur lokal".
5. **Echte TLS-Verbindungen bestehen die Pruefung** gegen `localhost`,
   `127.0.0.1` **und** `::1`. Nachgewiesen durch drei tatsaechlich aufgebaute
   Verbindungen mit aktivierter Verifikation gegen den laufenden Dienst — nicht
   durch das Auslesen der SAN-Eintraege aus der Zertifikatsdatei.
6. **Ablauf ist ein benannter Befund:** Ein abgelaufenes oder unbrauchbares
   Startzertifikat fuehrt beim Start zu einer Fehlermeldung mit
   Handlungsanweisung, nicht zu einem Verbindungsabbruch, den der Aufrufer
   selbst deuten muss. Nachgewiesen mit einem Zertifikat, dessen
   Gueltigkeitsende in der Vergangenheit liegt.
7. **Rotation ist atomar:** Waehrend der Erneuerung sieht kein Client jemals
   eine halb geschriebene Datei oder ein Paar aus altem Zertifikat und neuem
   Schluessel. Nachgewiesen an einem Lauf, in dem waehrend der Rotation
   fortlaufend Verbindungen aufgebaut werden: entweder altes oder neues
   Vertrauen, nie ein Fehlschlag durch Inkonsistenz.
8. **Die Reihenfolge des Hochfahrens ist dokumentiert**, dort wo ein Mensch sie
   sucht, und sie ist **nachvollzogen worden**: jemand ist ihr auf einer
   Maschine ohne Vorwissen gefolgt und hat den Dienst erreicht. Insbesondere
   ist festgehalten, dass `serve` die `.env` nicht selbst laedt.
9. **Konzept nachgezogen** (FK-10) mit Decision Record und
   Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–9 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Coverage haelt die 85-%-Schwelle.
- Alle deterministischen Konzept-Gates gruen; Decision Record im Diff oder
  gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/10_runtime_deployment_speicher.md` — Ablageorte,
  Hochfahrreihenfolge, Laufzeitverzeichnisse
- `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md` —
  Secrets-Ablage und Dateirechte
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` —
  Trust Boundaries

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — ein unbrauchbares Startvertrauen wird nicht
  durch Deaktivieren der Pruefung umgangen.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 4 verbietet den Verifikations-Aus-Schalter.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — genau ein Vertrauensanker,
  `var/` ist ephemer und nie fachliche Wahrheit.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 5 verlangt echte
  Verbindungen, nicht das Lesen der Zertifikatsdatei.
