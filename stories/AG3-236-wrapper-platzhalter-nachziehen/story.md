# AG3-236 — Der zurückgezogene Platzhalter steht noch 154-mal im Korpus

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: [AG3-208]` — dort ist die Regel entschieden
- **Herkunft:** AG3-208 Runde 2, nach dem AC-10-Review, 2026-08-07

## Anlass

AG3-208 hat `<absolute-agentkit-wrapper>` **zurueckgezogen**. Der erste Versuch,
ihn zentral als `agentkit-project-edge` umzudeuten, war der eigentliche Fehler:

> Er korrigierte die 154 Fundstellen nicht, sondern machte aus bisher
> **mehrdeutigen** Befehlen ausdruecklich **falsche**.

```
<absolute-agentkit-wrapper> serve      Decision Record 2026-08-02 Port 9702:149
                                       -- `serve` gehoert dem KERN
<absolute-agentkit-wrapper> dashboard  FK-63:86
                                       -- `dashboard` gibt es als Verb nicht
```

An seine Stelle treten **vier eindeutige Platzhalter** — Edge-CLI, Kern-CLI und
die beiden Hook-Wrapper — und die Aufloesungsregel ist nicht mehr „ein
Platzhalter, eine Distribution", sondern:

> **Das Verb entscheidet.**

Bis der Text nachgezogen ist, gilt jede Fundstelle als **veraltet**, nicht als
gueltig. Diese Story zieht ihn nach.

## Umfang, gemessen

```
154 Fundstellen in 49 Dateien
 18 davon unter concept/formal-spec/*/commands.md  (Prosa-Formal-Audit)
dazu aktive bare `agentkit …`-Kommandos in FK-91:575 und FK-41,
    obwohl FK-10 das Script `agentkit` zurueckzieht
```

## Warum das eine eigene Story ist

**Die fachliche Entscheidung ist gefallen.** Was hier ansteht, ist Schreibarbeit
entlang einer Regel, die bereits normiert ist. Ein Massenrename gehoert nicht in
denselben Auftrag, der normative Grundsatzfragen klaert — dort haette er die
Reviewfaehigkeit des eigentlichen Zielbilds erdrueckt.

**Aber es ist keine mechanische Ersetzung.** Jede Fundstelle braucht die
Zuordnung ueber ihr **Verb**, und genau daran ist der zentrale Ansatz
gescheitert. Ein `sed` ueber alle 154 Stellen wuerde denselben Fehler in
grossem Massstab wiederholen.

## Der Teil, der nicht geloest wird

**Neun Verben aus den Fundstellen haben keine CLI-Entsprechung:**
`dashboard`, `resolve-conflict`, `structural`, `policy`, `stages`, `migrate`,
`install`, `backend health`.

AG3-208 hat sie bewusst **nicht** zugeordnet, und die Begruendung gilt hier
weiter: Ein Verb einer Distribution zuzuweisen, das es gar nicht gibt, waere ein
heimatloser Eintrag mit **erfundenem** Eigentuemer — genau das, was
`CLAUDE.md` §ZERO DEBT als Weitertragen fremder Schuld beschreibt.

Sie sind **vorbestehende Drift mit Owner PO**. Diese Story fasst sie an genau
einer Stelle an: Sie macht sie **sichtbar**, statt sie durch eine Ersetzung
plausibel aussehen zu lassen.

## Scope

### In Scope

- Alle 154 Fundstellen tragen den Platzhalter, der zu ihrem **Verb** passt.
- Die bare `agentkit …`-Kommandos in FK-91 und FK-41 tragen den heutigen
  Scriptnamen.
- Die neun verwaisten Verben sind an ihren Fundstellen als **nicht
  implementiert** kenntlich — nicht stillschweigend einer Distribution
  zugeschlagen.

### Out of Scope

- Die Aufloesung der neun Verben. Owner PO.
- Jede weitere normative Aussage. Diese Story wendet an, sie entscheidet nicht.
- Produktionscode.

## Akzeptanzkriterien

1. **Kein `<absolute-agentkit-wrapper>` mehr im Korpus**, nachgewiesen durch
   eine Suche mit Zahl — nicht durch Sichtpruefung.
2. **Jede ersetzte Stelle traegt den Platzhalter ihres Verbs.** Je Fundstelle
   ist die Zuordnung nachvollziehbar; eine pauschale Ersetzung erfuellt das
   nicht. Stichprobenartig zu belegen an den Faellen, die AG3-208 namentlich
   nennt (`serve`, `dashboard`).
3. **Die neun verwaisten Verben sind kenntlich**, an jeder ihrer Fundstellen,
   und nirgends einer Distribution zugeordnet.
4. **Die 18 Fundstellen unter `formal-spec/*/commands.md`** sind mitgezogen und
   die Formal-Spec kompiliert weiterhin.
5. **Ein Rueckfall faellt auf.** Ein deterministischer Check weist den
   zurueckgezogenen Platzhalter und den baren Scriptnamen `agentkit` im Korpus
   ab. Er ist gegen einen kuenstlich eingefuegten Verstoss geprueft.
6. Alle sieben deterministischen Konzept-Gates gruen; Referenzintegritaet ohne
   neue Baseline-Eintraege.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — die neun Verben werden sichtbar gelassen, nicht
  durch eine Ersetzung plausibel gemacht
- `CLAUDE.md` §SINGLE SOURCE OF TRUTH — ein Platzhalter, eine Bedeutung
- `CLAUDE.md` §FAIL-CLOSED — AC 5
