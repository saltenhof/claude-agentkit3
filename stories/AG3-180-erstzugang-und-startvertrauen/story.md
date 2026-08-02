# AG3-180 — Erstzugang und Startvertrauen: AK3 macht sich selbst betriebsbereit

- **Typ:** implementation
- **Groesse:** M
- **Betroffen:** `backend/auth/`, `backend/cli/`, `backend/installer/`, FK-15, FK-10
- **Herkunft:** Erste echte Fremdinstallation am 2026-08-02 (Nachbarprojekt „Intima").

## Befund

**AK3 kann sich nicht in einen benutzbaren Zustand bringen.** Eine frische
Installation hat keinen Weg zu einem Projekt-Token, und der Installer scheitert
an genau der Stelle, an der er es braucht.

Die Kette: `AGENTKIT_PROJECT_API_TOKEN` kommt aus
`POST /v1/projects/{project_key}/api-tokens`. Diese Route verlangt eine
angemeldete Session. Die Session kommt aus `POST /v1/auth/login`. Das Passwort
liegt Argon2id-gehasht in `~/.config/agentkit/auth.json` (ueberschreibbar per
`AGENTKIT_AUTH_CONFIG`), Standardbenutzer `admin`.

Gesetzt wird dieses Passwort von `credentials.set_password()`. **Aufgerufen wird
die Methode an genau vier Stellen — allen vieren in Tests**
(`tests/unit/auth/test_credentials.py`, `tests/unit/auth/http/test_auth_routes.py`,
`tests/integration/control_plane/test_takeover_confirm_pg.py`). Es gibt kein
CLI-Verb, keinen Installer-Schritt, keinen Bootstrap. Die Verbliste kennt weder
`auth` noch `login` noch `token`.

Aufgefallen ist es nie, weil die Tests sich ihre Voraussetzung selbst erschaffen.

**Zweiter Befund derselben Familie: das TLS-Startzertifikat.** `agentkit serve`
verlangt `--certfile` als Pflichtangabe. Erzeugt wird ein Zertifikat von
**nichts** in AK3 — kein Skript, kein Installer, keine Dokumentation. Unter
`var/devcert/` liegt seit dem 2026-06-21 ein handgemachtes Paar. Es traegt
`CN=localhost` und **keine SAN-Erweiterung**; damit verifiziert ausschliesslich
der Name `localhost`. Jede Anleitung, die `https://127.0.0.1:9702` nennt — meine
eingeschlossen — schlaegt mit „IP address mismatch" fehl.

Ein Produkt, das TLS verpflichtend fordert, muss sagen koennen, woher das
Zertifikat kommt.

**Dritter Befund: eine globale editierbare Installation.** Auf der
Entwicklungsmaschine zeigt `_editable_impl_agentkit.pth` im Benutzer-
`site-packages` auf `T:\codebase\claude-agentkit3\src`. Das ist genau die
Konstellation, vor der `CLAUDE.md` warnt: AK3 und AK2 teilen den Paketnamen
`agentkit`. Sie ist auch der Grund, warum ein beliebiger PATH-Python AK3
ueberhaupt importieren konnte und der Interpreter-Defekt so lange unentdeckt
blieb.

## Akzeptanzkriterien

1. **Ein frisch installiertes AK3 kommt ohne Handarbeit zu einem Projekt-Token.**
   Nachgewiesen an einer Installation, bei der `~/.config/agentkit/auth.json`
   und alle Token vorher **nicht existieren**. Kein Python-Einzeiler, kein
   direkter Dateieingriff, keine DB-Manipulation im Ablauf.
2. Der Erstzugang erzeugt sein Geheimnis **selbst** und zeigt es **genau einmal**
   an. Es wird nicht vom Bediener gesetzt und nirgends in Klartext abgelegt oder
   protokolliert. (Anlass: am 2026-08-02 ist ein solches Passwort im Klartext in
   einem Agenten-Protokoll gelandet.)
3. Ein zweiter Bootstrap-Aufruf auf einer bereits eingerichteten Instanz
   **erzeugt kein neues Geheimnis** und ueberschreibt keins — fail-closed mit
   klarer Meldung. Rotation ist ein eigener, ausdruecklicher Vorgang.
4. **Rotation existiert und ist belegt:** Geheimnis wechseln, neues Projekt-Token
   ausstellen, altes widerrufen — jeder Schritt ueber eine benannte Oberflaeche,
   kein Eingriff in Dateien.
5. **AK3 erzeugt sein Startzertifikat selbst**, mit `localhost`, `127.0.0.1` und
   `::1` als SAN. Nachgewiesen durch einen Verbindungsaufbau gegen **beide**
   Schreibweisen — Name und IP —, der die Zertifikatspruefung besteht.
6. Ein abgelaufenes oder unbrauchbares Startzertifikat fuehrt zu einer
   **benannten Fehlermeldung mit Handlungsanweisung**, nicht zu einem
   Verbindungsabbruch, den der Aufrufer selbst deuten muss.
7. **Die Reihenfolge des Hochfahrens ist dokumentiert**, dort wo ein Mensch sie
   sucht, und sie ist **nachvollzogen worden**: jemand ist ihr auf einer Maschine
   ohne Vorwissen gefolgt und hat das Becken erreicht. Insbesondere ist
   festgehalten, dass `serve` die `.env` nicht selbst laedt.
8. **Die globale Installierbarkeit ist entschaerft.** Entweder AK3 laesst sich
   nicht mehr global editierbar installieren, oder es erkennt die Konstellation
   und warnt beim Start mit Nennung des Konflikts mit AK2. Eine stillschweigend
   geteilte `site-packages`-Sichtbarkeit zwischen zwei Produkten mit gleichem
   Paketnamen ist kein zulaessiger Zustand.
9. Fuer jeden der drei Befunde existiert ein Test, der **gegen den heutigen Stand
   rot** ist. Insbesondere ein Test, der belegt, dass der Erstzugang **ohne
   vorher gesetztes Passwort** funktioniert — die heutige Suite beweist das
   Gegenteil, weil sie es sich selbst setzt.
10. Konzept nachgezogen: FK-15 (Erstzugang, Rotation, Token-Lebenszyklus) und
    FK-10 (Startzertifikat, Reihenfolge). Decision Record vorhanden.

## Abgrenzung

Keine Benutzerverwaltung, keine Rollen, kein Mehrbenutzerbetrieb — das
Zugriffsmodell aus FK-15 bleibt unveraendert. Diese Story stellt nur her, dass
der **erste** Zugang ohne Handarbeit entsteht und das Startvertrauen einen
Eigentuemer hat.

Kein Produktionszertifikat und keine PKI. Das Startzertifikat ist ausdruecklich
ein Entwicklungs- und Erstinbetriebnahme-Mittel.
