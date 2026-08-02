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

1. **Ein frisch installiertes AK3 kommt ohne Handarbeit zu einem Projekt-Token.**
   Nachgewiesen an einer Installation, bei der `~/.config/agentkit/auth.json`
   (bzw. der Pfad aus `AGENTKIT_AUTH_CONFIG`) und alle Token vorher **nicht
   existieren**. Im Ablauf kommt kein Python-Einzeiler, kein direkter
   Dateieingriff und keine DB-Manipulation vor. Der Nachweis laeuft ueber die
   Oberflaechen, die ein Bediener hat — nicht ueber `set_password()` aus einem
   Testmodul.
2. **Die beiden Geheimnisklassen sind getrennt normiert und im Code
   unterscheidbar.** FK-15 sagt danach fuer jede der beiden ausdruecklich:
   wer sie erzeugt, wo sie liegt, in welcher Form, mit welchen Rechten, wie
   lange, und wie sie widerrufen wird. Der heutige Widerspruch zwischen
   „nirgends in Klartext" und FK-15 §15.10.4 (`:492-497`, Klartext-Token
   einmalig angezeigt, clientseitig als Datei mit eingeschraenkten Rechten)
   ist damit aufgeloest — nicht durch Weglassen einer der beiden Aussagen.
3. **Die Bootstrap-Oberflaeche ist autorisiert und ihre Trust Boundary ist
   benannt.** Der Erstzugang ist nur ueber einen Weg erreichbar, der lokalen
   Maschinenzugriff voraussetzt. Ist die Oberflaeche HTTP, bindet sie
   ausschliesslich an Loopback (`127.0.0.1`, `::1`) und weist einen Aufruf mit
   nicht-lokaler Herkunft **ab**, statt ihn zu protokollieren. Nachgewiesen an
   einem Aufruf ueber eine Nicht-Loopback-Adresse derselben Maschine, der
   fehlschlaegt.
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
