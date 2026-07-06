# Soll-Prozess (Rev. 2): Push-Barriere als Edge-getriebener Wartepunkt mit Boundary-Lifecycle
### AG3-147 Design-Korrektur — nach Codex-Design-Review; PO-Entscheid: **V1-gehärtet**

## 0. Kern der Korrektur
Die Barriere ist **kein synchroner Backend-Schnappschuss über running-latest „Frische"**, sondern ein
**edge-getriebener, begrenzter Wartepunkt**, aufgelöst bei der bestätigenden Edge-Rückkehr auf einen
**konkreten, an DIESE Grenze gebundenen Head `H`**, den der Backend selbst serverseitig bestätigt
(`ls-remote == H`), zweistufig, hartes UND je Repo. Das Ergebnis wird als **ein autoritativer Verdict-Record
persistiert**, den alle anderen nur **lesen**.

## 1. Invarianten (müssen immer gelten)
- **pushed-only:** nur server-bestätigt Gepushtes zählt.
- **zweistufig:** Edge-Meldung **und** backend-eigener Server-Read — Edge-Meldung allein genügt nie.
- **Ownership-autorisiert:** Push nur nach Online-Gate (aktueller `owner_session`/`ownership_epoch`); Ex-Owner scheitert (Gate + Ref-Schutz).
- **fail-closed:** unbekannt / Timeout / offener Auftrag / Fehler → blockieren + sichtbarer Push-Rückstand + Eskalation. Nie stiller Durchlass, nie Endlos-Hang.
- **Multi-Repo hartes UND:** ein ungepushtes Repo blockiert.
- **Frische = Information, nie Entscheidung** (FK-10 §10.2.4b / Kap 02.7) — Barriere entscheidet NICHT auf running-latest Frische.
- **eine Wahrheit:** genau ein persistierter Verdict je Grenz-Instanz; Konsumenten leiten nichts neu ab.

## 2. Boundary-Lifecycle (das verbindende Modell — schließt Findings #1/#3/#4)
Eine Barriere ist eine **gebundene Grenz-Instanz**, kein Moment.

- **Bindung bei Grenz-Eintritt:** `(boundary_type, boundary_id, boundary_epoch=1, erwarteter Head H je Repo)`.
  `boundary_id` identifiziert die Grenz-Instanz; `boundary_epoch` zählt Re-Bindungen innerhalb der Instanz.
- **Mutations-Invalidierung (#4):** Jeder AK3-registrierte Commit **nach** dem Grenz-Eintritt invalidiert die
  aktuelle Bindung → `boundary_epoch++`, neues erwartetes `H`, jeder Verdict der alten Epoch wird
  `superseded`. So kann ein Retry der alten Grenze mit altem `H` die neue Bindung **nicht** erfüllen.
  **Mechanisch erzwingen (Design-Review-Auflage):** Diese Invalidierung ist an ALLEN commit-erzeugenden
  AK3-Pfaden zu erzwingen, solange eine Boundary pending ist — nicht als Worker-Konvention.
- **V1-gehärtete Edge-Invariante (#1):** Der Edge-`sync_push`-Executor bestimmt `H = rev-parse HEAD`
  **unmittelbar vor** dem Push, pusht **genau dieses** `H`, und prüft **nach** dem Push `HEAD == H`.
  Zwischen Grenz-Eintritt und Auflösung ist der Worker an dieser Grenze **quiesziert** (keine produktive
  Mutation); bewegt sich HEAD doch, wird die Bindung invalidiert (neue Epoch) statt still weiterzumachen.
  Damit kann der Executor keinen veralteten `A` als „aktuell" pushen, während lokal `B` neuer ist.

## 3. Happy Path — Schrittfolge E ↔ B
Auslöser: Worker erreicht Grenze `G`. Backend **bindet** die Grenz-Instanz (§2): `boundary_id`,
`epoch`, erwartetes `H` je Repo (bei V1: `H` wird durch die Edge-Deklaration im Push-Result final gesetzt
und gegen die Quieszenz-Invariante gehärtet).

1. **E → B (Anfrage + Freigabe):** „stehe an `G`." B prüft **online** Ownership. Nicht-Owner → verweigern.
   Owner → B autorisiert den Push (`story/{id}`, Dienst-Identität) für diese Grenz-Instanz `(boundary_id, epoch)`.
2. **E (Ausführung, V1-gehärtet):** `H = rev-parse HEAD`; Push von `H` auf `story/{id}` mit Dienst-Identität; nach Push `HEAD == H` prüfen.
3. **E → B (bestätigende Rückkehr):** Branch-Ref-Meldung „gepusht `H`" (je Repo), getaggt mit `(boundary_id, epoch, ownership_epoch)`.
4. **B (Auflösung + Verdict):** B liest **selbst** den Server (`ls-remote story/{id}`). Je Repo, zweistufig:
   (a) E meldet `H` als gepusht **und** (b) Server-Head `== H`, **und** (c) `(boundary_id, epoch, ownership_epoch)` ist aktuell (nicht superseded). → persistiere **PushBarrierVerdict** (§4).
5. **Aggregation:** Barriere PASST genau dann, wenn **alle** beteiligten Repos einen `passed`-Verdict für die **aktuelle** `epoch` haben — bei der finalen Aggregation **server-frisch nachgeprüft** (#5). Sonst → blockt (§5).

## 4. Autoritativer Verdict-Record (#3 — „eine Wahrheit" als Artefakt)
`PushBarrierVerdict` je `(project_key, story_id, run_id, boundary_type, boundary_id, repo_id)` mit:
Producer, `boundary_epoch`, erwartetes `H`, `server_head`, `ownership_epoch`, `status`
(`pending | passed | blocked_backlog | superseded`), Zeitstempel. **Postgres-only, K5.**
- **Konsumenten lesen nur:** der strukturelle `completion.push`-Check, das QA-Cycle-Gate und die
  SOLL-190-Merge-Vorbedingung **lesen diesen Verdict** — sie rufen **nicht** eigenständig `evaluate_push_barrier`
  neu auf. Wer eine frische Prüfung braucht, fordert explizit einen neuen Wait-Point/eine neue Grenz-Instanz an.

## 5. Fehler-, Timeout-, Supersede-Zweig (#2)
- **Timeout als eigener Zustand:** bleibt die bestätigende Rückkehr innerhalb der Schranke aus → Verdict
  `blocked_backlog`, sichtbarer Push-Rückstand, Eskalation. Kein stiller Durchlass, kein Endlos-Hang.
- **Offener/steckengebliebener Auftrag (Edge-Crash nach `delivered`, vor Result):** der offene `sync_push`
  wird **superseded/admin-aborted**; eine neue Grenz-Bindung/`epoch` kann einen frischen Auftrag ausstellen,
  **ohne** auf die Terminalität des toten Auftrags zu warten.
- **Late-Result-Fence:** ein Result, das eine **superseded** `(boundary_epoch)` oder eine veraltete
  `ownership_epoch` trägt, wird verworfen — es kann eine Grenze **nie rückwirkend** passfähig machen.

## 6. Multi-Repo & Closure (#5)
- **Per-Repo-Verdicts;** die Barriere passt nur, wenn **alle** beteiligten Repos für die aktuelle `epoch`
  `passed` sind — bei finaler Aggregation **server-frisch nachgeprüft** (ein Repo, das sich nach seinem PASS
  bewegt, zählt nicht mehr).
- **Closure-Entry ≠ Pre-Merge:** der Closure-Eintritts-Push und der spätere integrierte Pre-Merge-Kandidat
  sind **verschiedene Heads** → **getrennte Boundary-Typen/-IDs und getrennte Verdicts**, keine
  Wiederverwendung. SOLL-190 konsumiert den **Pre-Merge**-Verdict, nicht den Closure-Entry-Verdict.

## 7. Failure-Mode-Matrix (inkl. der von der Review gefundenen neuen Varianten)
| Failure-Mode | Warum ausgeschlossen |
|---|---|
| Fail-Open (alter A==A) | konkreter Grenz-`H` + Server-Read; alter Stand ist nicht der gebundene `H` |
| False-Negative/Deadlock (zu früh) | Auswertung bei E's Rückkehr, nach dem Push |
| Retry-Treadmill (per-Versuch-ID) | Wahrheit = „Server zeigt gebundenes `H`"; Verdict statt per-Versuch-Korrelation |
| Zwei Prüf-Flächen | ein persistierter Verdict, den Konsumenten nur lesen |
| **NEU: stale edge-declared `H` (#1)** | V1-Härtung: `H=rev-parse HEAD` unmittelbar + Post-Push-Recheck + Quieszenz/Epoch-Invalidierung |
| **NEU: offener Queue-Auftrag / Late-Result (#2)** | Supersede + Late-Result-Fence über `(boundary_epoch, ownership_epoch)` |
| **NEU: Reentry-Alt-`H` erfüllt neue Grenze (#4)** | Mutation invalidiert Bindung → neue `epoch`, alter Verdict `superseded` |
| **NEU: Multi-Repo-/Closure-Drift (#5)** | Per-Repo + finale Server-Frische-Prüfung; Closure-Entry vs. Pre-Merge getrennt |

## 8. Konzept-Konsequenz (Formulierung korrigiert — WARNING #6)
Die Implementierung war **ein Konzept-Verstoß PLUS eine Präzisierungslücke**: FK-10 §10.2.4b sagt bereits
„Edge meldet Head-SHA", „Edge- plus Server-Verifikation" und „Frische = Information, nie Entscheidung" —
das Entscheiden auf running-latest Frische war der **Verstoß**. Aber **Boundary-`H`, Wait-Point-Timing,
Queue-Superseding und Verdict-SSOT waren nie explizit** — das ist die **Lücke**. Die FK-10-Korrektur macht
beides fest (siehe `konzept-korrektur-fk10-10.2.4b.md`).

## 9. Was bleibt / was ersetzt wird
- **Bleibt (wiederverwenden):** zweistufiger A-Kern (Edge-Meldung ∧ Server-Read), Postgres/K5, Dienst-
  Identität + `story/*`-Ref-Schutz (`bypass_actors`), Online-Push-Gate, Evidenz-Umzug off backend-local-git.
- **Ersetzt/neu:** Boundary-Lifecycle mit `boundary_id`/`epoch`, V1-Härtung im Edge-Executor, persistierter
  `PushBarrierVerdict` als SSOT (statt re-derivierender Aufrufe), Supersede-/Late-Result-Fence, getrennte
  Closure-Entry-/Pre-Merge-Boundaries. **Zu entfernen:** running-latest-Frische als Entscheidungsgrundlage
  und die per-Versuch-Korrelation.
