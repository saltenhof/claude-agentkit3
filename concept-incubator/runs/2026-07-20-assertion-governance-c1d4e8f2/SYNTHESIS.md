# Synthese und finaler Plan — Human Assurance normativer Aussagen

Lauf: `2026-07-20-assertion-governance-c1d4e8f2` · Council-Orchestrator:
Fable 5 (Claude Code) · Beitragende: Fable 5 (Proposal 1), Codex
`openai.codex.review-agent` (Proposal 2, job-a67ac1e2, Resume-Kette aus
dem Gruendungslauf).

Status: **PO-Entscheidung getroffen, Umsetzung nicht begonnen.** Dieser
Lauf ist noch kein schema-konformer FK-78-Lauf; er wird bei
Umsetzungsbeginn als solcher aufgesetzt.

---

## 1. Auftrag

In einem Setting, in dem Agentennetzwerke weitgehend autonom grosse
Konzeptmengen erzeugen, entstehen normative Aussagen, die kein Mensch je
gesehen hat. Sie sind das Beste, was die Agenten als Intent des Menschen
antizipiert haben. Zwischen menschlichem Intent und agentischer
Antizipation liegt zwangslaeufig ein Drift — minimierbar, nie
eliminierbar.

Diese Aussagen sind normativ fuer das gesamte Projekt. Die Frage des PO:
Muss ein Agent einem Paragrafen gehorchen, den nie ein Mensch abgesegnet
hat? Und woran macht sich das fest?

## 2. Beitraege

| Quelle | Kern |
|---|---|
| Proposal 1 (Fable 5) | Ratifikation als digestgebundenes Ereignis; drei Stufen `agent_authored`/`po_informed`/`po_ratified`; vererbbare Ratifikation auf Abschnittsebene mit Kennzeichnung; unterschiedliche Aufloesungsautoritaet je nach Ratifikationsstand |
| Proposal 2 (Codex) | Bestaetigt Richtung, korrigiert drei Punkte hart; ergaenzt fehlende Authentizitaet als groesste Luecke; loest die Granularitaetsfrage; findet zwoelf Falsch-Gruen-Pfade und einen Normkonflikt mit FK-25 |

Beide Proposals liegen als `proposal-2-codex.md` bzw. im
Konversationsprotokoll vor.

## 3. Unstrittige Klaerungen (beide Proposals einig)

1. **Die Fragestellung war leicht falsch gestellt.** Ratifikation
   entscheidet nicht, *ob* eine Norm gilt, sondern **wer einen Konflikt
   abschliessend aufloesen darf**. Auch eine unratifizierte aktive Norm
   ist zu befolgen; sie ist anfechtbar, nicht optional.
2. **Ratifikation ist eine eigene Achse**, kein Wert in
   `assertion_status`. Sonst entsteht ein Kreuzprodukt.
3. **Digestbindung ist zwingend.** Ohne sie luegt der Status nach der
   ersten Umformulierung.
4. **Fail-closed.** Kein Eintrag bedeutet `unratified` — nicht Fehler,
   nicht `agent_authored`.
5. **Register-on-touch.** Nur ratifizierte, angefochtene, geaenderte und
   neu entstandene Aussagen werden registriert. Bestandsprosa bleibt
   `legacy_unknown`/`unratified`, gilt weiter, blockiert nichts.
6. **Granularitaet** = kleinste unabhaengig governierbare normative
   Proposition (Codex' Definition, uebernommen). Identitaet
   (`assertion_id`) und Revision (`revision_digest`) getrennt.

## 4. Die PO-Entscheidung

Der PO hat die Haertungsvorschlaege aus Proposal 2 bewertet und eine
bewusste Abwaegung getroffen. Wortlaut sinngemaess:

> In einem Setting, in dem der Mensch den Agenten als primaeres Interface
> benutzt — auch fuer die Erteilung seiner Zustimmung — bekommt man das
> System nur furchtbar schwer wirklich abgesichert, nicht nur
> schein-abgesichert. Die Frage lautet daher nicht richtig oder falsch,
> sondern **Komfort und Zeiteffizienz gegen Risiko**. Beides zugleich ist
> nicht zu haben. Ich entscheide mich bewusst fuer Komfort und Zeit. Mir
> ist das Tracking wichtig und der Mechanismus, der darauf aufsetzt.
> Grenzenloses Vertrauen in KI-Agenten behaupte ich nicht — aber der
> **Vorsatz**, sich ueber den Benutzerwillen hinwegzusetzen, fehlt. Das
> Restrisiko ist damit klein genug, um es zu akzeptieren.

**Entscheidungscharakter:** Proposal 2 wird in der Sache angenommen. Die
darin enthaltenen Haertungen werden dort abgeschwaechst, wo sie
Zeremonie gegen einen Angriff aufbauen, der Vorsatz voraussetzt.
Beibehalten wird alles, was gegen **unabsichtliche** Fehlattribution
schuetzt — denn genau das ist der Fehlermodus, der ohne Vorsatz auftritt
und den das Vorhaben adressieren soll.

**Leitsatz dieser Synthese:**

> Gehaertet wird gegen Irrtum, nicht gegen Boeswilligkeit.

## 5. Umsetzungsplan v1

### 5.1 Uebernommen ohne Abstriche

| Gegenstand | Begruendung |
|---|---|
| Assertion-Identitaet: `assertion_id` stabil, `revision_digest` je Fassung | Kern des Verfahrens; billig |
| Granularitaet = kleinste governierbare Proposition; Bedingungen, Ausnahmen, Scope, Failure-Semantik, Zahlenwerte samt Einheit bleiben im selben Atom | Genau hier entsteht Qualifikator-Drift |
| Explizite Marker fuer Prosa (`ASSERTION:BEGIN/END`), kleinstes strukturiertes Objekt im Formal-Layer | Ohne Anker keine dauerhafte Identitaet |
| Register-on-touch, `legacy_unknown` als ehrlicher Default | Verhindert 20.000-Aussagen-Umbau |
| Fuenf orthogonale Achsen (Authority/Lifecycle · Projection · Human Assurance · Challenge · Provenienz) | Vermeidet Statuskreuzprodukt |
| Eigener Meta-Kontext `assertion-governance` statt Einbau in `concept-incubation` | FK-78 erzeugt Bindungen, besitzt die Semantik nicht |
| Read-only Statusabfrage fuer implementierende Agents | Ohne Abfragepfad ist der Status wirkungslos |
| Promotion-Bindung Atom → dauerhafte Assertion (`assertion-bindings.tsv`) | Lauf-ID ist keine Korpus-ID |
| Keine impliziten Ausdehnungen: ein Ratifikationsereignis traegt eine explizit aufgezaehlte Menge von Aussage-Revisionen | Kostet keinen Komfort, weil der Agent die Liste erzeugt |
| Metrik-Ehrlichkeit: keine Prozentwerte ueber den Gesamtkorpus ohne vollstaendiges Inventar; absolute Zahlen plus `inventory_coverage` | Kostet nichts |

### 5.2 Bewusst abgeschwaecht

| Codex-Vorschlag | Entscheidung v1 | Akzeptiertes Risiko |
|---|---|---|
| Kryptographische Authentizitaet (signierte Commits, Allowed-Signers, detached Signaturen) als Voraussetzung fuer `ratified` | **Gestrichen fuer v1.** Ersatz: Das Ratifikationsereignis wird vom Agenten protokolliert und **muss die woertliche Nutzeraeusserung als Evidenz tragen** (Zitat, Sitzungsreferenz, Zeitpunkt), append-only. Der Statuswert traegt `assurance_level: agent_attested`; `cryptographically_verified` bleibt als spaetere Stufe vorgesehen. | Ein Agent koennte ein Ratifikationsereignis fabrizieren. Erfordert Vorsatz. **Nicht** abgedeckt vom Zitatzwang ist eine bewusste Faelschung des Zitats. |
| `po_informed` ersatzlos streichen | **Stufe bleibt, Wirkung wird null.** Sie heisst `presented` und ist reine Expositionstatsache: kein Einfluss auf Aufloesungsautoritaet, kein Zustimmungssurrogat. Materiell ist Codex' Einwand damit erfuellt, das Tracking bleibt erhalten. | Gering. Risiko ist Fehlinterpretation in Prompts — wird durch Namensgebung und eine explizite Negativaussage in der Norm adressiert. |
| Aenderungssperre fuer ratifizierte Assertion-Linien (harter Blocker ohne menschliche Freigabe) | **Kein Blocker, sondern Sichtbarkeit.** Aenderung einer ratifizierten Aussage laesst die Ratifikation verfallen (`stale`), markiert die Aenderung sichtbar und **verpflichtet den Agenten, sie dem Menschen aktiv zu spiegeln**. | Der von Codex beschriebene Pfad „erst minimal aendern, dadurch Ratifikation stale machen, dann selbst adjudizieren" bleibt technisch offen. Erfordert Vorsatz. Wird durch die Spiegelungspflicht sichtbar, nicht verhindert. |
| Challenge-State-Machine mit acht Zustaenden, Council-Pflicht bei hoher Tragweite | **Reduziert.** Challenge ist ein Registereintrag mit Pflichtfeldern (Assertion, Revision, Evidenz, Auswirkung, gewuenschte Loesung, Challenger). Zwei Ausgaenge: `uphold` oder `change_via_governed_promotion`. Unabhaengiger Zweitblick nur bei **ratifizierten** Aussagen; bei unratifizierten genuegen Aktenlage und Meldung an den Menschen. | Ein Einzelagent kann eine unratifizierte Norm mit duenner Begruendung kippen. Gegenmittel bleibt: er darf sie nicht umgehen, sondern nur ueber eine regulaere Promotion aendern — mit Akte. |
| Shard-Registry mit `index.json` und Vollstaendigkeitsbeweis gegen stilles Entfernen | **Flache, append-freundliche Registry ohne Vollstaendigkeitsbeweis.** | Ein Agent koennte Eintrag samt Verweis entfernen. Erfordert Vorsatz. |
| Verbot, dass ein Agent normative Ausnahmen erteilt | **Beibehalten.** Ausnahmen erteilt nur der Mensch. | — (nicht abgeschwaecht) |
| Verbot, dass ein Worker seine eigene Challenge abschliessend entscheidet | **Beibehalten.** | — (nicht abgeschwaecht) |

### 5.3 Warum der Zitatzwang die einzige nicht verhandelbare Ersatzmassnahme ist

Der Fehlermodus, der **ohne Vorsatz** auftritt, ist nicht Faelschung,
sondern **Ueberinterpretation**: Ein Agent haelt ein beilaeufiges „ja,
klingt gut" fuer die Ratifikation von zwanzig Aussagen und schreibt das
guten Glaubens ins Register. Das ist exakt derselbe Drift zwischen Intent
und Antizipation, den das Vorhaben adressieren soll — nur eine Ebene
hoeher.

Die Pflicht, die woertliche Aeusserung mitzufuehren, kostet keine Zeit
und keinen Komfort, macht diese Fehlklasse aber fuer den Menschen im
Nachhinein pruefbar: Er kann lesen, worauf sich die behauptete Zustimmung
stuetzt, und erkennt Ueberinterpretation sofort. Ohne diese Massnahme ist
das Tracking, das der PO ausdruecklich als wichtig benannt hat, wertlos —
es traegt dann eine Behauptung ohne Beleg.

### 5.4 Das Konfliktregime (v1, verbindlicher Satz)

> Jede aktive Norm ist zu befolgen, bis ein formaler Konflikt aufgeloest
> ist. Bei unratifizierten Normen darf ein unabhaengiger Agent oder ein
> Gremium die normative Aenderung adjudizieren; bei ratifizierten Normen
> darf dies ausschliesslich der Mensch. Ein erkannter Widerspruch darf in
> keinem Fall still umgesetzt werden.

Aufloesungsautoritaet:

| Assurance | Resolver |
|---|---|
| unregistriert / `legacy_unknown` | unabhaengiger Agent, mit Akte |
| `unratified` | unabhaengiger Agent, mit Akte |
| `presented` (nur vorgelegt) | unabhaengiger Agent, mit Akte |
| `ratified` | Mensch |
| `ratification_stale` (nach Aenderung) | Mensch, mit Spiegelungspflicht |
| menschlich widerrufen | unabhaengiger Agent |

Schutz gegen die Bequemlichkeits-Generalklausel (unveraendert aus
Proposal 2 uebernommen):

- Kosten-, Stil- oder Bequemlichkeitsargumente sind kein zulaessiger
  Challenge-Grund.
- Bestehender Code darf die Norm nicht „durch Realitaet ueberstimmen".
- Bis zur Aufloesung bleibt die betroffene Landung blockiert.
- Ein Agent darf keine normative Ausnahme erteilen — nur `uphold` oder
  `change_via_governed_promotion`.

## 6. Benanntes Restrisiko (offen, nicht verschleiert)

Von den zwoelf Falsch-Gruen-Pfaden aus Proposal 2 bleiben unter dieser
Entscheidung **vier** technisch offen. Alle vier erfordern Vorsatz:

1. Ein Agent schreibt selbst ein Ratifikationsereignis (Nr. 3).
2. Eine ratifizierte Norm wird erst veraendert und danach als
   unratifiziert agentisch ersetzt (Nr. 6).
3. Ein Registereintrag wird gemeinsam mit seinem Verweis entfernt
   (Nr. 9).
4. Ein „unabhaengiger" Agentenreviewer ist nur eine zweite Sitzung
   desselben entscheidenden Akteurs (Nr. 11) — in v1 nur bei
   ratifizierten Aussagen ueberhaupt gefordert.

Die uebrigen acht (Mehrfachaussagen je Block, Qualifikatoren ausserhalb
des Digests, Abschnittsratifikation erfasst Nachtraege, ID-Wiederverwendung
fuer neue Semantik, `presented` als schwache Zustimmung, format-only-Marker
traegt Ratifikation ueber Inhaltsaenderung, Projektions-Receipt als
Human-Ratifikation missverstanden, Coverage-Kennzahl verschweigt
Unregistriertes) werden in v1 **geschlossen** — sie sind Irrtumspfade,
keine Vorsatzpfade, und damit genau der Bereich, den diese Entscheidung
schuetzt.

Diese Auflistung ist bewusst Teil des Plans. Der Restpunkt lautet nicht
„erledigt", sondern „bewusst offen angenommen, mit benanntem
Aufloesungsweg" (kryptographische Assurance-Stufe, spaeter nachruestbar
ohne Modellbruch — die Achse `assurance_level` ist dafuer vorgesehen).

## 7. Beruehrte Normen

Unabhaengig vom Haertegrad zu klaeren, weil das agentische
Adjudikationsrecht heute nicht existiert:

- **FK-25 §25.2–25.3** verlangt bei Normativkonflikten derzeit *immer*
  menschliche Entscheidung. Das agentische Aenderungsrecht fuer
  unratifizierte Normen ist eine echte Normaenderung, kein Zusatz.
- Formaler Kontext `exploration` (Eskalationssemantik)
- `concept/_meta/assertion-authority.md` (bekommt Assurance- und
  Challenge-Semantik)
- `CLAUDE.md`, Abschnitt Konzepttreue
- FK-78 und Toolchain (Assertion-Bindungen in der Promotion)

## 8. Abgrenzung und Reihenfolge

Der PO hat die **Vektorsuche fuer Zielprojekte** (fehlender
`story-knowledge-base`-MCP-Server, FK-13 normiert, nicht implementiert)
vor dieses Vorhaben priorisiert. Das ist auch sachlich stimmig: Die
Statusabfrage aus §5.1 wird sinnvollerweise ueber denselben Pfad
konsumiert wie die semantische Konzeptsuche.

Nicht Teil von v1: vollstaendige Korpusatomisierung,
Ratifikationsdashboard, graphbasierte Priorisierung, UI fuer signierte
Batch-Ratifikation, semantische Diff-Vorschlaege, Control-Plane-Persistenz.

## 9. Entscheidungsprotokoll

| Nr. | Frage | Entscheidung | Entscheider |
|---|---|---|---|
| 1 | Eigene Achse oder Wert in `assertion_status` | eigene Achse | Council (beide Proposals einig) |
| 2 | Granularitaet | kleinste governierbare Proposition | Codex, vom PO angenommen |
| 3 | Kryptographische Authentizitaet in v1 | **nein** — Zitatzwang statt Signatur | PO |
| 4 | `po_informed` | bleibt als `presented` mit Wirkung null | Council-Synthese |
| 5 | Aenderungssperre fuer ratifizierte Linien | Sichtbarkeit statt Blocker | PO |
| 6 | Challenge-Verfahren | reduziert, Zweitblick nur bei ratifiziert | PO |
| 7 | Vollstaendigkeitsbeweis der Registry | nein | PO |
| 8 | Agentische Ausnahmen | verboten (unveraendert) | Council |
| 9 | Reihenfolge gegenueber Vektorsuche | Vektorsuche zuerst | PO |
