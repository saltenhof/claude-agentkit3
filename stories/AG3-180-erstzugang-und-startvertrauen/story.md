# AG3-180 — Erstzugang ohne Handarbeit: der Bootstrap-Vertrag

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-187
- **Quell-Konzept:** FK-15 §15.10.3 (Cookie-Session mit lokalem Passwort),
  FK-15 §15.10.4 (Thin-Client-Token), FK-10 (Hochfahrreihenfolge)
- **Herkunft:** Erste echte Fremdinstallation am 2026-08-02 (Nachbarprojekt).
  Neu geschnitten am 2026-08-02 nach unabhaengigem Codex-Review des Schnitts
  aus Commit `77b4b034` (Auflage ERROR-4).

## Kontext

### Befund — belegt, mit Locator

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

### Was am ersten Schnitt falsch war

Der Schnitt vom 2026-08-02 verlangte ein „Geheimnis", das „nirgends in Klartext
abgelegt oder protokolliert" wird. Das ist **sicherheitskritisch unbestimmt**
und steht mit dem Bestand im Widerspruch:

- Es gibt **zwei verschiedene Geheimnisse** mit verschiedenen Regeln. Das
  **Strategenpasswort** (Anmeldung des Benutzers `admin`) darf nirgends im
  Klartext liegen — es liegt Argon2id-gehasht. Das **Projekt-Token** dagegen
  wird nach `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md:492-497`
  ausdruecklich „**einmal bei Erstellung** angezeigt, danach nie wieder",
  serverseitig gehasht gehalten und **clientseitig im Klartext** in einer
  „projekt-lokalen Konfigurationsdatei (typisch `.agentkit/credentials` mit
  eingeschraenkten Dateirechten, ausserhalb der Versionsverwaltung)".
  Ein pauschales „nirgends in Klartext" verbietet damit genau den Weg, den das
  Fachkonzept vorschreibt.
- Es fehlte, **wer** bootstrappen darf und **von wo**. Ein Bootstrap-Endpunkt
  ohne Trust Boundary ist eine Uebernahmeschnittstelle: wer ihn erreicht,
  bekommt das Administratorgeheimnis einer noch leeren Instanz.
- Es fehlte die **Einmaligkeit unter Nebenlaeufigkeit**. „Ein zweiter Aufruf
  erzeugt kein neues Geheimnis" ist eine Aussage ueber zwei *nacheinander*
  laufende Aufrufe. Zwei *gleichzeitige* Aufrufe auf einer leeren Instanz sind
  der interessante Fall — dort entscheidet sich, ob zwei Bediener beide ein
  gueltig aussehendes Geheimnis in der Hand halten.
- Es fehlte das **Verhalten nach Abbruch**. Zwischen Passwortanlage, erstem
  Login und Tokenausstellung liegen mehrere Schritte. Bricht der Ablauf
  dazwischen ab, ist die Instanz halb eingerichtet — und genau dann greift die
  Fail-closed-Regel „zweiter Bootstrap wird abgewiesen" und sperrt den Bediener
  aus seiner eigenen Installation aus.
- Es fehlten **Dateirechte auf beiden Plattformen**. AK3 laeuft auf Windows
  (Entwicklung) und POSIX (CI). `chmod 600` ist unter Windows wirkungslos; ein
  ACL-Weg ist etwas anderes und muss benannt werden.
- Es fehlte der **Schutz gegen nicht-interaktive Ausgabe**. Am 2026-08-02 ist
  ein solches Passwort im Klartext in einem Agenten-Protokoll gelandet. Ein
  Geheimnis, das „genau einmal angezeigt" wird, wird in einem Agenten- oder
  CI-Lauf genau einmal **protokolliert** — und liegt dann dauerhaft dort.

## Rollenmodell — PO-Entscheidung 2026-08-03, nach Review R2

Review R2 meldete als ERROR 1, der Erstzugang sei aus der Laptop-Cloud-Topologie
nicht erreichbar. **Der Befund beruht auf einer falschen Annahme: er unterstellt
eine Rolle, wo zwei sind.** Der PO hat das am selben Tag entschieden:

| Rolle | Womit | Erstzugang |
|---|---|---|
| **Backend-Admin** | installiert den Kern (fertiges Image oder On-demand-Installation) und hat dabei **zwangslaeufig** eine Shell auf der Kernmaschine | legt den Admin-Account beim Provisionieren an — das ist Teil der Installation, kein eigenes Problem |
| **Client-Bediener** | haengt einen Entwicklerrechner an, erreicht den Kern **nur** ueber HTTPS, hat **keine** Shell und ist **nicht** der Admin | bekommt vom Admin ein **Projekt-Token** ausgehaendigt und verbindet sich damit |

**Damit ist der CLI-Bootstrap auf der Kernmaschine richtig** und AC 3 in seiner
Bedingung („ist die Oberflaeche HTTP …") gegenstandslos, nicht verletzt.

**Die verbleibende Luecke liegt woanders und ist gemessen:**
`harness_client/projectedge/auth_operator.py:47` holt das Projekt-Token ueber
`authenticate_strategist(username="admin", password=…)`. Der Client-Bediener
muesste also das **Admin-Passwort** kennen, um seinen Rechner anzuhaengen. Die
beiden Geheimnisklassen sind damit in der *Verwendung* getrennt (Review-Runde 1,
E1: ein Projekt-Token darf nichts administrieren), aber nicht im **Erwerb**.

`backend/cli/auth_commands.py:351` zeigt dieselbe Vermischung: `issue-token`
meldet sich als Stratege an **und** schreibt die Credential-Datei nach
`--project-root` — beides auf derselben Maschine, also unter der Annahme, Admin
und Bediener seien dieselbe Person.

**Der beschlossene Weg** — er braucht kein neues Konzept, FK-15 §15.10.4
beschreibt ihn bereits („einmal bei Erstellung angezeigt, danach nie wieder"):

1. Der **Admin** erzeugt das Projekt-Token kernseitig. Es wird **einmal**
   ausgegeben und **nicht** lokal als Credential-Datei abgelegt.
2. Die Uebergabe an den Bediener erfolgt **ausserhalb des Systems**.
3. Der **Bediener** legt das Token auf seinem Rechner ab — ueber ein Verb, das
   **keine Anmeldung** verlangt, weil das Token selbst der Nachweis ist.

Ausdruecklich **nicht** beschlossen: ein Anforderungs-/Genehmigungsvorgang, bei
dem der Bediener ein Token beantragt und der Admin es freigibt. Das waere eine
eigene Faehigkeit mit Warteschlange, Zustand und Oberflaeche — eigene Story,
nicht diese.

## Scope

### In Scope

- Eine **autorisierte Bootstrap-Oberflaeche** fuer den Erstzugang, mit benannter
  Trust Boundary und Loopback-Beschraenkung.
- Der vollstaendige Weg von der leeren Installation bis zum Projekt-Token, ohne
  Handarbeit an Dateien oder Datenbank.
- Rotation und Widerruf beider Geheimnisklassen.
- Normative Nachfuehrung in FK-15 (Erstzugang, Rotation, Token-Lebenszyklus)
  samt Decision Record.

### Out of Scope

- Benutzerverwaltung, Rollen, Mehrbenutzerbetrieb. Das Zugriffsmodell aus FK-15
  bleibt unveraendert; diese Story stellt nur her, dass der **erste** Zugang
  ohne Handarbeit entsteht.
- Das TLS-Startzertifikat — **AG3-188**.
- Die globale editierbare Installation — **AG3-189**.
- Der durchgehende Fremdinstallations-Lauf — **AG3-187**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/auth/credentials.py` | geaendert | `set_password()` bekommt einen produktiven Aufrufer; Einmaligkeits- und Rotationssemantik |
| `src/agentkit/backend/auth/` (neues Bootstrap-Modul) | neu | Erzeugung, atomare Einmaligkeit, Trust-Boundary-Pruefung |
| `src/agentkit/backend/auth/http/` | geaendert | Bootstrap-/Rotations-Route mit Loopback-Beschraenkung, falls die Oberflaeche HTTP ist |
| `src/agentkit/backend/cli/` | geaendert | Bootstrap-, Login-, Token- und Rotationsverben in der Verbliste |
| `src/agentkit/backend/installer/` | geaendert | Installer bezieht das Projekt-Token ueber den Bootstrap-Weg statt es vorauszusetzen |
| `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md` | geaendert | Erstzugang, Trust Boundary, Rotation, Dateirechte je Plattform, Abgrenzung der beiden Geheimnisklassen |
| `concept/_meta/decisions/2026-XX-XX-erstzugang-bootstrap.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/integration/auth/` | neu | Erstzugang ohne vorher gesetztes Passwort, Nebenlaeufigkeit, Abbruch |
| `tests/unit/auth/` | geaendert | Dateirechte je Plattform, Ausgabekanal-Schutz |

## Akzeptanzkriterien

1. **Beide Rollen kommen ohne Handarbeit ans Ziel — getrennt nachgewiesen.**
   Vorbedingung beider Nachweise: `~/.config/agentkit/auth.json` (bzw. der Pfad
   aus `AGENTKIT_AUTH_CONFIG`) und alle Token existieren vorher **nicht**. In
   keinem der beiden Ablaeufe kommt ein Python-Einzeiler, ein direkter
   Dateieingriff oder eine DB-Manipulation vor; beide laufen ausschliesslich
   ueber Oberflaechen, die die jeweilige Rolle tatsaechlich hat — nicht ueber
   `set_password()` aus einem Testmodul.

   **1a — Admin, kernseitig.** Mit Shell auf der Kernmaschine: Admin-Account
   anlegen, anmelden, ein Projekt-Token erzeugen. Das Token wird **einmal**
   ausgegeben und **nicht** als Credential-Datei auf der Kernmaschine abgelegt —
   der Admin sitzt nicht am Rechner des Bedieners.

   **1b — Client-Bediener, laptopseitig.** **Ohne** Shell auf dem Kern und
   **ohne** Kenntnis des Admin-Passworts: das ausgehaendigte Token ablegen und
   damit einen authentisierten Aufruf gegen den Kern fuehren. Nachgewiesen an
   einem Ablauf, in dem das Strategenpasswort **nirgends vorkommt** — weder als
   Eingabe, noch als Umgebungsvariable, noch als Datei.

   Ein Nachweis, der 1a und 1b auf **derselben** Maschine und mit **denselben**
   Rechten fuehrt, erfuellt dieses Kriterium nicht: er bildet genau die Trennung
   nicht ab, um derentwillen es existiert.
2. **Die beiden Geheimnisklassen sind getrennt normiert und im Code
   unterscheidbar.** FK-15 sagt danach fuer jede der beiden ausdruecklich:
   wer sie erzeugt, wo sie liegt, in welcher Form, mit welchen Rechten, wie
   lange, und wie sie widerrufen wird. Der heutige Widerspruch zwischen
   „nirgends in Klartext" und FK-15 §15.10.4 (`:492-497`, Klartext-Token
   einmalig angezeigt, clientseitig als Datei mit eingeschraenkten Rechten)
   ist damit aufgeloest — nicht durch Weglassen einer der beiden Aussagen.
3. **Die Bootstrap-Oberflaeche ist autorisiert und ihre Trust Boundary ist
   benannt.** Der Erstzugang setzt Zugriff auf die **Kernmaschine** voraus —
   das ist die Trust Boundary, und sie deckt sich mit der Rolle, die den Kern
   ohnehin provisioniert (siehe Rollenmodell). Nachzuweisen ist deshalb die
   **Abwesenheit** eines zweiten Weges: es existiert **keine** Netzoberflaeche,
   ueber die sich ein Erstzugang ohne diesen Maschinenzugriff erzeugen laesst.
   Nachgewiesen an einer repository-weiten Suche nach Bootstrap-Routen und an
   einem Aufruf von aussen, der nicht auf eine abgeschaltete Route trifft,
   sondern darauf, dass es sie nie gab.

   **Der frueher hier verlangte Loopback-Nachweis entfaellt** — nicht weil er zu
   schwer waere, sondern weil er einen HTTP-Bootstrap voraussetzt, den es nach
   der PO-Entscheidung nicht geben soll. Ein Test, der einen Nicht-Loopback-Ruf
   gegen eine **nicht existierende** Route schickt und `401` erwartet, bestuende
   auch ohne jede Origin-Policy und belegt nichts (Review R2, ERROR 2).
4. **Einmaligkeit haelt unter Nebenlaeufigkeit.** Zwei **gleichzeitig**
   gestartete Bootstrap-Aufrufe auf derselben leeren Instanz: genau einer
   liefert ein Geheimnis, der andere endet fail-closed mit benanntem Grund.
   Nachgewiesen an einem echten Zwei-Prozess-Rennen, wiederholt gefahren —
   nicht an einem Test, der die Aufrufe serialisiert und die Serialisierung
   selbst simuliert.
5. **Ein Abbruch zwischen Passwortanlage, Login und Tokenausstellung sperrt
   niemanden aus.** Fuer jeden Zwischenzustand ist ausgeschrieben und getestet,
   was gilt und wie der Bediener weiterkommt. Ein Zustand „Passwort existiert,
   Bediener kennt es nicht" ist entweder unmoeglich oder hat einen benannten,
   getesteten Ausweg — er wird nicht der Rotation zugeschoben, die ihrerseits
   eine Anmeldung braucht.
6. **Rotation und Widerruf existieren und sind belegt:** Strategenpasswort
   wechseln, neues Projekt-Token ausstellen, altes widerrufen — jeder Schritt
   ueber eine benannte Oberflaeche, kein Eingriff in Dateien. Nachgewiesen
   daran, dass ein widerrufenes Token danach mit `401` abgewiesen wird
   (FK-15 §15.10.4, Revocation).
7. **Dateirechte sind fuer Windows UND POSIX festgelegt und geprueft.** Auf
   POSIX ist der Modus der Auth-Datei und der clientseitigen Token-Datei
   nachgemessen; auf Windows ist der wirksame ACL-Eintrag nachgemessen. Ein
   Test, der auf Windows nur `chmod` aufruft und `os.stat().st_mode` prueft,
   erfuellt dieses Kriterium **nicht** — er misst dort nichts.
8. **Das einmalig angezeigte Geheimnis erreicht kein nicht-interaktives
   Protokoll.** Laeuft der Bootstrap ohne angeschlossenes Terminal (Agent, CI,
   umgeleitete Ausgabe), wird das Geheimnis **nicht** auf stdout/stderr
   geschrieben; der Aufruf endet fail-closed mit der Angabe, welcher Weg
   stattdessen gilt. Nachgewiesen an einem Lauf mit umgeleiteten Stroemen, in
   dem das Geheimnis im gesamten aufgefangenen Text nicht vorkommt.
   (Anlass: am 2026-08-02 ist ein solches Passwort im Klartext in einem
   Agenten-Protokoll gelandet.)
9. **Fuer jeden Befund existiert ein Test, der gegen den heutigen Stand rot
   ist.** Insbesondere einer, der belegt, dass der Erstzugang **ohne vorher
   gesetztes Passwort** funktioniert — die heutige Suite beweist das Gegenteil,
   weil sie es sich selbst setzt. Jeder dieser Tests ist per Mutation belegt:
   Fix zurueckgedreht -> rot, wiederhergestellt -> gruen.
10. **Konzept nachgezogen** (FK-15) mit Decision Record und
    Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–10 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Coverage haelt die 85-%-Schwelle.
- Alle deterministischen Konzept-Gates gruen; Decision Record im selben Diff
  oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`
  („Definition of Done"). Ein gruener CI-Lauf ist kein Abbruchkriterium.

## Konzept-Referenzen

- `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md`
  §15.10.3 (Cookie-Session mit lokalem Passwort), §15.10.4 (`:486-505`,
  Thin-Client-Token, Speicherung server-/clientseitig, Revocation, Projektbindung),
  §15.10.5 (Verhalten bei fehlender/ungueltiger Auth)
- `concept/technical-design/10_runtime_deployment_speicher.md` —
  Hochfahrreihenfolge, Ablageorte, Startvertrauen
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` —
  Trust Boundaries

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — ein unklarer Bootstrap-Zustand wird nicht
  grosszuegig toleriert.
- `CLAUDE.md` „ZERO DEBT RULE" — kein Zwischenzustand ohne benannten Ausweg.
- `CLAUDE.md` „MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL" — AC 4 verlangt ein
  echtes Zwei-Prozess-Rennen.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — der Erstzugang wird
  gegen eine echte leere Installation nachgewiesen, nicht gegen eine Fixture.
- `guardrails/testing-guardrails.md` — Negativpfade an Phasengrenzen.
