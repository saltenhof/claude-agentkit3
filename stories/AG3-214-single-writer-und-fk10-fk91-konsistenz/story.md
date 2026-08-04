# AG3-214 — Ein Writer, ein Vertrag: FK-10 gegen FK-91 konsistent machen

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-10 (Runtime/Deployment, Hochfahrreihenfolge), FK-91
  (API-/Event-Katalog, Claim- und Replay-Vertrag), FK-15 (Security, Rollen),
  FK-50 (Installer)
- **Herkunft:** Befundrunde vom 2026-08-04. Bei AG3-180 hatte eine Reviewrunde
  einen FK-10/FK-91-Widerspruch gemeldet, der nie ins Repo geschrieben wurde
  und dessen Inhalt verloren ging. Die Neuermittlung hat fuenf ERRORs und ein
  WARNING gefunden — ob der urspruengliche darunter ist, laesst sich nicht
  beweisen, aber alle sind aus dem heutigen Bestand belegbar.

## Befund 1 (ERROR, Datenintegritaet) — zwei Prozesse gegen einen Writer

**Locatoren:** FK-10:573-576 gegen FK-91:332; Code `cli/lifecycle.py:46`,
`cli/serve.py:67`, `control_plane_http/app.py:1049`,
`state_backend/postgres_store/_ownership_rows.py:1437`,
`control_plane/startup_reconcile.py:147`

FK-10 normiert als Hochfahrschritt **zwei** Dienste:
`agentkit serve --ui-bff` und `agentkit serve --project-api`. Die beiden Flags
sind eine `mutually_exclusive_group(required=True)` — **selbst verifiziert**;
FK-10 verlangt damit zwingend zwei Prozesse. FK-91 verlangt **genau einen**
aktiven Control-Plane-Writer pro Datenbank plus Reconciliation, bevor Requests
angenommen werden.

Beide Profile starten dieselbe vollstaendige Anwendung. Jeder Prozess erhoeht
die gemeinsame Backend-Inkarnation und reconciliert frueherer Inkarnationen —
**der zweite Prozess kann damit Claims des noch lebenden ersten als verwaist
behandeln.** Das ist kein Dokumentationsfehler, sondern ein Pfad zu
Datenkorruption im laufenden Betrieb.

### PO-ENTSCHEID 2026-08-04 — Variante (a): ein Prozess, zwei Listener

FK-91s Single-Writer-Vertrag bleibt unangetastet. FK-10 wird auf **eine**
aktive Writer-Laufzeit normiert: beide Oberflaechen — UI-BFF und Project-API —
leben in derselben Laufzeit und derselben Boot-Identitaet.

Zur Wahl standen:

- **(a) — GEWAEHLT.** Ein Prozess, zwei Listener.
- **(b) — verworfen.** UI-BFF als nicht schreibender Proxy. Haette die
  Prozessgrenze erhalten, aber eine erzwungene Nicht-Schreib-Garantie
  gebraucht.
- **(c) — verworfen.** Zwei Writer, Vertrag auf Koexistenz umgestellt. Waere
  die Abschwaechung des Single-Writer-Vertrags gewesen.

**Die Konsequenz ist ausdruecklich mitentschieden und muss nachgezogen werden:**
Die Trennung von UI-BFF und Project-API war eine **Prozessgrenze mit
Sicherheitsbedeutung**. Sie faellt. FK-15 darf danach keine Trennung mehr
behaupten, die es nicht mehr gibt — ein Sicherheitskonzept, das eine nicht
existierende Grenze beschreibt, ist schlimmer als keines, weil sich Leser
darauf verlassen. Welche Schutzwirkung die Grenze hatte und wie sie innerhalb
eines Prozesses hergestellt wird (getrennte Auth-Kontexte, getrennte
Bind-Adressen, Rechtetrennung auf Routenebene), ist Teil dieser Story und
gehoert in den Decision Record.

Unabhaengig davon: der Code braucht eine **Lebensdauer-Exklusivitaet**, damit
ein zweiter schreibender Prozess nicht unbemerkt startet. Heute ist das nicht
nur moeglich, es ist die dokumentierte Empfehlung.

## Befund 2 (ERROR) — Auth-Claims sind nicht instanzgebunden

**Locatoren:** FK-10:951 und FK-91:332 gegen
`state_backend/store/inflight_idempotency_guard.py:369`, Aufrufpfad
`auth/http/routes.py:380`

Beide Konzepte verlangen fuer jeden In-Flight-Claim `backend_instance_id` und
`instance_incarnation`. Der von den Auth-Routen benutzte generische Guard
schreibt `operation_epoch`, `backend_instance_id` und `instance_incarnation`
**ausdruecklich als NULL** — mit dem Kommentar, sein Zaun sei „the op_id PK +
the claimed status, not an instance epoch". **Selbst verifiziert.**

Folge: Die Startup-Reconciliation findet nur Claims derselben Backend-ID aus
einer frueheren Inkarnation. Ein Auth-Claim mit NULL-Identitaet bleibt nach
einem Absturz ausserhalb dieses Pfades — es bleibt der manuelle Admin-Abort.

### PO-ENTSCHEID 2026-08-04 — der Absender gehoert auf jeden Claim

> „ich kenn die designentscheidung nicht, aber fuer mich klingt es sinnvoll den
> absender immer dazu zu packen"

**Die woertliche Lesart gilt: es ist ein Codedefekt, keine Konzeptpraezisierung.**
Der generische Guard persistiert kuenftig Backend-Identitaet, Inkarnation und
Fencing-Epoch; die Startup-Reconciliation bezieht diese Claims ein.

Die Entscheidung ist nicht nur eine Auslegung, sie ist die robustere Seite:
**Ein Claim ohne Absender ist grundsaetzlich nicht automatisch aufloesbar.**
Der bestehende Zaun (`op_id`-PK plus `claimed`-Status) verhindert zwar
Doppelausfuehrung, beantwortet aber nie die Frage „lebt der Halter noch". Damit
bleibt nach jedem Absturz der manuelle Admin-Abort als einziger Ausweg — eine
Betriebslast, die niemand eingeplant hat.

**Der Umsetzer prueft die urspruengliche Begruendung trotzdem** (Kommentar in
`inflight_idempotency_guard.py:369`, zugehoerige Storys AG3-137/AG3-138): Trug
sie ein Argument, das hier uebersehen wurde — etwa einen Pfad, auf dem die
Instanzbindung nicht ermittelbar ist —, wird das **gemeldet statt umgangen**.
Die Entscheidung steht; ein belegter Gegengrund ist eine Mandatsanfrage, keine
stille Abweichung.

## Befund 3 (ERROR) — FK-10 und FK-91 tragen den Registrierungspfad von vor AG3-180

**Locatoren:** FK-10:331 und FK-91:116 gegen FK-15:663; Code
`cli/auth_commands.py:204`, `cli/installer_commands.py:341`

FK-10 verlangt waehrend `register-project` eine Passworteingabe und eine
temporaere Strategen-Session; FK-91 laesst denselben Ausnahmeweg zu. FK-15 —
der massgebliche Security-Vertrag — verlangt das **Projekt-Token vor**
`register-project` und verbietet die Strategen-Session dort. Der gelandete Code
folgt FK-15 und verweist sonst auf `store-token`.

Zusaetzlich: FK-91s angeblich eng begrenzte Strategen-Ausnahme ist serverseitig
**nicht** an „erste Registrierung / vor erster Credential" gebunden. Die Route
muss die behauptete Rollenbegrenzung auch erzwingen.

## Befund 4 (ERROR) — FK-91s Auth-CLI-Katalog ist veraltet, und ein Test friert ihn ein

**Locatoren:** FK-91:445 gegen `cli/auth_commands.py:161`; Test
`tests/unit/concept_toolchain/test_ag3_180_decision_record.py:65`

FK-91 beschreibt `issue-token` mit `--project-root` und lokaler
Veroeffentlichung, kennt kein `store-token` und gibt `revoke-token` eine
falsche Signatur. Code und FK-15 weisen die Veroeffentlichung ausschliesslich
dem Clientverb `store-token` zu.

Der AG3-180-Contract-Test pinnt derzeit **genau fuenf** Auth-Verben und
verfestigt damit den veralteten Katalog. Der Decision Record
`2026-08-03-erstzugang-bootstrap.md:159` benennt die ausstehende
FK-91-Korrektur bereits ausdruecklich — sie ist nie erfolgt.

## Befund 5 (ERROR) — FK-10s Startkommandos starten keinen gueltigen Listener

**Locatoren:** FK-10:573 und Porttabelle FK-10:1054 gegen FK-91:172; Code
`cli/lifecycle.py:57`

FK-10 zeigt beide `serve`-Aufrufe **ohne Zertifikatsargument**. FK-91 erklaert
Plain HTTP fuer ungueltig, und der Parser verlangt folgerichtig `--certfile`.
FK-10s normative Hochfahrkommandos koennen den geforderten HTTPS-Listener also
gar nicht starten. FK-10 muss Zertifikatsquelle, Uebergabe und vollstaendige
Startkommandos normieren; HTTPS wird nicht gelockert.

## Befund 6 (WARNING) — sicherheitsrelevanter Kommentar sagt das Gegenteil des Codes

**Locator:** `auth/http/routes.py:392` gegen FK-15:638

Der Kommentar behauptet, ein Token-Create-Replay gebe dasselbe Klartext-Token
zurueck. FK-15 und die Implementierung schliessen Klartext in HTTP-Antwort und
Idempotenz-Record ausdruecklich aus. **Das Laufzeitverhalten ist richtig, der
Kommentar ist falsch** — und er steht an einer Stelle, an der ein Leser
Sicherheitsannahmen ableitet. Korrektur des Kommentars, nichts am Verhalten.

## Akzeptanzkriterien

1. **Es gibt genau einen aktiven Control-Plane-Writer pro Datenbank.** UI-BFF
   und Project-API laufen in derselben Laufzeit und derselben Boot-Identitaet
   (PO-Entscheid Variante a); FK-10 normiert das. Ein zweiter schreibender
   Prozess kann nicht unbemerkt starten: die Exklusivitaet ist **erzwungen**,
   nicht zugesagt, und der abgewiesene Start nennt seinen Grund. Nachgewiesen
   durch einen Negativtest fuer den zweiten Start und durch einen Test, der
   belegt, dass eine Reconciliation keine Claims eines lebenden Writers als
   verwaist behandelt.

   **1a. Die entfallene Prozessgrenze ist ersetzt, nicht nur gestrichen.** Was
   die Trennung von UI-BFF und Project-API sicherheitstechnisch geleistet hat,
   ist benannt und innerhalb des einen Prozesses hergestellt. FK-15 beschreibt
   danach die tatsaechliche Grenze — keine Prozesstrennung, die es nicht mehr
   gibt.

2. **Jeder In-Flight-Claim traegt seinen Absender** (PO-Entscheid). Der
   generische Guard persistiert Backend-Identitaet, Inkarnation und
   Fencing-Epoch; die Startup-Reconciliation bezieht diese Claims ein.
   Nachgewiesen durch einen Test, der einen Absturz mitten im Auth-Vorgang
   simuliert und belegt, dass der Neustart den Claim **selbst** aufloest —
   ohne Admin-Eingriff. Ergibt die Pruefung der urspruenglichen Begruendung
   einen belegten Gegengrund, wird er gemeldet, nicht umgangen.
3. **FK-10 und FK-91 beschreiben den Registrierungsablauf von heute.** Die
   Strategen-Session vor `register-project` ist ueberall entfernt; die
   serverseitige Ausnahme ist auf „vor erster Credential" begrenzt und wird
   **erzwungen**, nicht nur behauptet. Negativpfad-Test.
4. **FK-91s Auth-CLI-Katalog stimmt mit der CLI ueberein**, inklusive
   `store-token` und korrekter `revoke-token`-Signatur. Der Contract-Test pinnt
   den tatsaechlichen Katalog statt einer veralteten Zahl.
5. **FK-10s Startkommandos sind vollstaendig und lauffaehig**, inklusive
   Zertifikatsquelle und -uebergabe. Nachgewiesen daran, dass die dokumentierten
   Kommandos gegen eine echte Installation einen HTTPS-Listener hochbringen —
   Realitaetsnachweis, kein Unit-Test.
6. **Der Klartext-Replay-Kommentar sagt, was der Code tut.**
7. **Volle Suite gruen** (Jenkins), `ruff`, `mypy --strict`, alle
   deterministischen Konzept-Gates; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1-7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — Befund 1
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — Befunde 1 und 2
- `CLAUDE.md` „FAIL-CLOSED" — Befunde 1, 2, 3
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 5
- `CLAUDE.md` „Konzepttreue ist Pflicht" — ein Konzept, das vom beschlossenen
  Verhalten abweicht, wird an der Stelle nachgezogen
