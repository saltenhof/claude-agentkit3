# Konzept-Korrektur-Vorschlag (Rev. 2): FK-10 §10.2.4b (Sync-Punkte / Push-Barriere)
### Vorschlag zur PO-Freigabe — NOCH NICHT in FK-10 eingearbeitet (erst nach Bestätigungs-Review + PO-OK)

## Ausgangslage
FK-10 §10.2.4b hält im Kern **bereits das Richtige** fest: „Der Edge pusht … und **meldet den Head-SHA**";
„Verifikation … **Edge-Erhebung plus serverseitige Verifikation** (Ref-Read) — nie allein aus der lokalen
Erhebung"; „**Push-Frische** … ist Information, nie Entscheidung".

Der Fehler AG3-147 war deshalb **ein Konzept-Verstoß PLUS eine Präzisierungslücke**:
- **Verstoß:** die Barriere entschied auf der running-latest Push-Frische — genau das, was „Information, nie
  Entscheidung" ausschließt.
- **Lücke:** **Boundary-Head-Bindung**, **Wait-Point-Timing**, **Superseding offener Aufträge/Late-Results**
  und ein **autoritativer Verdict (Single Source of Truth)** waren im Konzept **nie explizit**.

Die folgende Präzisierung schließt beides und ist mit dem übrigen §10.2.4b-Text konsistent (der bestehende
Text zu opportunistischen Pushes, Frische=Information, WIP-Ref-Verwurf, dauerhaft scheiternder Barriere
bleibt unverändert).

## Vorgeschlagene Ergänzung/Schärfung unter „Harte Push-Barrieren"

> **Entscheidungsgrundlage (explizit):** Die Barriere entscheidet auf dem **konkreten, an DIESE
> Grenz-Instanz gebundenen Head `H`** (je beteiligtem Repo), serverseitig verifiziert — d. h. sie PASST
> genau dann, wenn der Edge für die Grenze `H` als gepusht meldet **und** der backend-eigene Ref-Read
> (`ls-remote` auf `story/{story_id}`) denselben `H` bestätigt (zweistufiges hartes UND je Repo). Sie
> entscheidet **nicht** auf der running-latest Push-Frische; diese bleibt reine Information.
>
> **Wartepunkt statt Momentaufnahme (explizit):** Die Barriere ist ein **begrenzter Wartepunkt**. Offizieller
> Ablauf ist push-dann-melden: der Backend autorisiert den Push (Online-Ownership-Gate), der Edge pusht `H`
> mit der Dienst-Identität und **kehrt mit der Branch-Ref-Meldung zurück**; erst diese bestätigende Rückkehr
> (plus Server-Ref-Read) löst die Barriere auf. Der Backend wertet **nach** der Edge-Ausführung aus, nie durch
> eine verfrühte Momentaufnahme davor.
>
> **Grenz-Bindung & Head-Identität (explizit):** Jede Grenz-Überquerung bindet eine Grenz-Instanz
> (`boundary_id` + Epoch) an das erwartete `H`. Der Edge bestimmt `H` **unmittelbar vor** dem Push
> (`rev-parse HEAD`), pusht genau dieses `H` und prüft danach `HEAD == H`; zwischen Grenz-Eintritt und
> Auflösung ist der Worker an der Grenze quiesziert. **Jede produktive Mutation (neuer AK3-registrierter
> Commit) nach Grenz-Eintritt invalidiert die Bindung** (neue Epoch, neues erwartetes `H`); ein alter,
> server-konsistenter Stand kann eine bewegte Grenze damit nicht erfüllen.
>
> **Eine autoritative Verifikation (Single Source of Truth, explizit):** Das Barriere-Ergebnis wird als **ein
> persistierter Verdict** je Grenz-Instanz und Repo geführt (Postgres-only, K5). Alle Konsumenten — der
> strukturelle `completion.push`-Check (FK-33), das QA-Zyklus-Gate und die Push-Verifikation vor Merge
> (SOLL-190, §12.4.3) — **lesen diesen Verdict**, statt die Verifikation eigenständig neu abzuleiten. Wer eine
> frische Prüfung braucht, fordert explizit eine neue Grenz-Instanz an.
>
> **Fail-closed bei Ausbleiben/Alt-Ergebnis (explizit):** Bleibt die bestätigende Rückkehr innerhalb der
> Schranke aus (Remote nicht erreichbar, Edge offline, Auftrag steckt), bleibt die Barriere fail-closed
> blockiert, der Push-Rückstand sichtbar, Eskalation an den Menschen. Ein **superseded** oder aus einer
> veralteten Ownership-/Grenz-Epoch stammendes Ergebnis kann eine Barriere **nie rückwirkend** passfähig
> machen. Kein stiller Durchlass, kein Endlos-Hang.

## Head-Autorität: PO-Entscheid **V1 (edge-deklariert), gehärtet**
`H` wird durch die Edge-Deklaration gesetzt, aber **gehärtet**: unmittelbares `rev-parse HEAD` vor dem Push,
Post-Push-Recheck `HEAD == H`, Quieszenz + Epoch-Invalidierung bei Mutation. Die Restannahme (Edge deklariert
seinen wahren HEAD) ist im Trust-Modell vertretbar; die Ex-Owner-Bedrohung ist separat über Online-Gate +
`story/*`-Ref-Schutz (FK-12/§15.5.4/FK-55 §55.9) abgedeckt. V2 (registrierungs-autoritativer erwarteter
Head, neuer kanonischer Commit-Head-Record) bleibt als spätere Verschärfung notiert, nicht Teil dieser Korrektur.

## Konsistenz (bestätigt in der Design-Review)
FK-91 §91.1b (Queue, `sync_push`, `branch_ref_report`/`push_status_report`), FK-12 §12.4.3 / SOLL-190
(Push server-verifiziert vor Merge), FK-15 §15.5.4 (Online-Gate/zweistufig), FK-55 §55.9 (offizieller
Servicepfad), FK-56 §56.13c / Kap 02.7 (Frische = Information) — kein Widerspruch; die neue Semantik braucht
lediglich präzisere Wire-/State-Verträge (Verdict-Record, Boundary-Epoch, Late-Result-Fence).
