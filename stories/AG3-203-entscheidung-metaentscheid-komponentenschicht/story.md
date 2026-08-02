# AG3-203 — Entscheidungs-Story: Metaentscheid Komponenten-/Schnittstellenschicht

- **Typ:** concept (Entscheidungs-Story)
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-186
- **Quell-Konzept:** FK-07, FK-17, FK-18, `concept/formal-spec/`,
  `concept/technical-design/_meta/*.yaml`
- **Herkunft:** PO-Vorgabe vom 2026-08-02; Befund in
  `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-4 und `D-offene-entscheidungen.md` E7. Neu am 2026-08-02 aus Auflage
  ERROR-17 des unabhaengigen Codex-Reviews.

> **Diese Story entscheidet nichts.** Sie legt die Pfosten auf
> Meta-Konzeptebene entscheidungsreif vor und haelt das Ergebnis fest.
> `AGENTS.md` (PO-Ratifikation 2026-08-02): fehlt der Anker, waere die Domaene
> neu, oder entstuende ein Widerspruch, **holt der Agent zuerst den Product
> Owner** — „eine fehlende Grundentscheidung wird nicht durch eine gut
> formulierte Detailaussage ersetzt".

## Kontext

### Was der PO benannt hat

> Eine Zwischenschicht, die **Komponenten- und Schnittstellenbeschreibung**
> traegt, **von den Bounded Contexts abweichen darf** und **orthogonal** zu
> ihnen liegt — die Projektion darauf, **wie tatsaechlich in Repositories und
> Software-Artefakte geschnitten wird**.

### Warum das eine Grundentscheidung ist und keine Ausdetaillierung

`C-befundbericht.md` C-4.2 zeigt, dass die beschriebene Schicht **nicht** die
Component des Blueprints ist:

1. Die Blueprint-Component ist **strikt kontextgebunden** — „das Praefix des
   Bezeichners ist der umschliessende Kontext. Kein Freiheitsgrad" (§4.3.1).
2. Der Blueprint **verwirft** einen Auslieferungs- oder Verzeichnisbegriff
   ausdruecklich als Ebene: er „traegt keine fachliche Pflicht" (§2.2).
3. Die Abbildung auf die Quelltextstruktur ist **ausdruecklich ausserhalb** der
   Policy: „Eine benannte Grenze ist das Gegenteil einer Luecke."

Der PO will also die Flaeche, die der Goldstandard **bewusst offen laesst**.
Der Blueprint hat die Objektartenfrage in seinem §4.6 selbst offen und dem
Operator vorgelegt — mit zwei Vorfragen: der **Autoritaetsfrage** (wer gewinnt
bei Widerspruch zwischen Komponentenspec und Prosavertrag; fuer Ports ist das
dort **nicht** geklaert) und dem **Ort** (formale Familien sind thematisch
geschnitten und entsprechen den Kontexten nur teilweise).

Damit ist die Bedingung 1 des Agentenmandats — „Ausdetaillierung eines
Konzeptinhalts, der an anderer Stelle bereits groeber definiert ist" — **nicht
erfuellt**: es gibt keine Ankerstelle in AK3, gegen die sich eine
kontext-unabhaengige Komponentenebene ausweisen koennte.

### Was AK3 heute hat — und was dadurch fehlt

*Vorhanden* (C-4.3): FK-07 mit normativem Top-Level-Schnitt (§7.4),
verbindlichen Importgrenzen (§7.8), messbaren Invarianten (§7.9) und einem
**deterministischen Checker gegen den Python-Code** (§7.7) — also genau die
Bauphasen-Bindung, die der Blueprint ausklammert. Dazu `bounded-contexts.yaml`
(`responsibility`, `owns`, `excluded`) und `domain-registry.yaml`
(`contract_docs`/`member_docs`).

*Nicht vorhanden:* **keine maschinenlesbare Component als Objekt** —
`concept/technical-design/_meta/module-registry.yaml` ist eine **flache
Namensliste** ohne `responsibility`, `owns`, `provides`, `requires`. **Kein
Portobjekt** — FK-07 §7.2 Nr. 6 spricht von „veroeffentlichten Ports der owning
Components" als **Prosa**; es gibt keine Portidentitaet, keine `operations[]`,
kein `contract_ref`, keine `visibility`, keine `consumers[]`. **Keine Konsumart
an der Kante** — die Architekturpruefung arbeitet auf dem Importgraphen, der nur
**eine** Kantenart kennt.

**Praktische Folge:** AK3 kann heute die Frage *„welche Komponente besitzt
diesen Fakt, welchen Port bietet sie an, und mit welcher Signatur"* nicht
maschinell beantworten. Der Checker faengt Verstoesse gegen den Schnitt, aber
nicht die Klasse „Vertrag existiert nur als Name" — und genau diese Klasse hat
im Blueprint den Bruch verursacht.

## Scope

### In Scope

- Die fuenf Pfosten entscheidungsreif vorlegen (siehe AC 1).
- Das Einholen der PO-Entscheidung.
- Das Festhalten des Ergebnisses als Decision Record mit Betroffenheitsmatrix.

### Out of Scope

- **Jede Ausdetaillierung der Schicht** — AG3-186.
- **Jeder Code** (Register, Schema, Checker) — AG3-204.
- Keine Vorwegnahme des Ergebnisses in Detailtext. Fuenf gut formulierte
  Absaetze ueber eine Schicht, die der PO nicht beschlossen hat, sind genau der
  Fehler, den `AGENTS.md` untersagt.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/_meta/decisions/2026-XX-XX-metaentscheid-komponentenschicht.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `concept/_meta/assertion-authority.md` | geaendert | nur falls die Entscheidung den Autoritaetsrang festlegt |
| `concept/technical-design/00_index.md` | geaendert | nur falls eine neue Konzeptflaeche entsteht |

## Akzeptanzkriterien

1. **Die Vorlage stellt genau diese fuenf Pfosten**, jeden als offene Frage mit
   Konsequenzen:
   - **Schicht ja/nein** — wird zwischen Prosa und Formal-Layer ueberhaupt eine
     Ebene eingezogen?
   - **Autoritaetsrang** — wer gewinnt bei Widerspruch zwischen
     Komponentenspezifikation und Prosavertrag? (Im Blueprint §4.6 fuer Ports
     ausdruecklich **nicht** geklaert.)
   - **Objektart** — wird die Komponentenspezifikation eine zusaetzliche
     Objektart der **formalen** Schicht, oder lebt sie anderswo? (`KW-H1`: die
     Registry lebt in derjenigen Schicht, der die Autoritaetsordnung Komponenten
     zuweist — „nicht in derjenigen Schicht, die zufaellig schon
     maschinenlesbar ist"; mit dem Zusatzargument, dass eine formale Schicht
     bewusst **partiell** sein darf, die Komponentenebene aber **nicht partiell
     sein kann**.)
   - **Verhaeltnis zum Formal-Layer** — Abgrenzung nach oben und unten.
   - **Anspruch an die Codeprojektion** — soll die Schicht den Repo-/Artefakt-
     schnitt tragen (PO-Beschreibung), und was wird dann aus FK-07 §7.6
     (Repository-Regel) und `PROJECT_STRUCTURE.md`?
2. **Die Vorlage benennt, warum das Agentenmandat hier nicht traegt** — mit dem
   Nachweis, dass keine Ankerstelle in AK3 existiert, gegen die sich eine
   kontext-unabhaengige Komponentenebene ausweisen koennte.
3. **Die Vorlage benennt den Unterschied zum Blueprint** (C-4.2, drei Punkte)
   und die zwei Anschlussstellen (§4.6, `KW-H1`) — ohne den Blueprint als
   Vorlage zu behandeln. Er ist **Anschlussstelle, nicht Vorlage**.
4. **Der Loesungsraum ist offen formuliert.** Genannte Varianten sind Beispiele
   im Raum, keine Auswahlliste.
5. **Die PO-Entscheidung liegt zu allen fuenf Pfosten vor** und ist mit Datum
   und Urheber im Decision Record festgehalten. Eine Entscheidung, die der
   Umsetzer selbst getroffen hat, erfuellt dieses Kriterium nicht.
6. **Nach der Entscheidung ist die Groesse von AG3-186 bestimmbar.** Solange
   sie `TBD` bleiben muss, ist die Entscheidung nicht vollstaendig.
7. **Alle deterministischen Konzept-Gates gruen**;
   `check_concept_decision_record.py` bestaetigt Record und Matrix.

## Definition of Done

- AC 1–7 erfuellt.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- `AG3-186/status.yaml` traegt danach eine bestimmte Groesse statt `TBD`.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.2 Nr. 6, §7.4, §7.6, §7.7, §7.8, §7.9
- `concept/technical-design/17_fachliches_datenmodell_ownership.md`,
  `18_relationales_abbildungsmodell_postgres.md` — bestehende
  Fact-/Ownership-Zustaendigkeiten
- `concept/technical-design/_meta/module-registry.yaml`,
  `bounded-contexts.yaml`, `domain-registry.yaml`
- `concept/_meta/assertion-authority.md`
- `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-4; `D-offene-entscheidungen.md` E7

## Guardrail-Referenzen

- `AGENTS.md` (Agentenmandat, PO-Ratifikation 2026-08-02) — Bedingung 1 und 3;
  diese Story existiert genau deshalb.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — keine zweite Wahrheit ueber den
  Repo-Schnitt.
- `CLAUDE.md` „Konzepttreue ist Pflicht" — bei Konzeptkonflikt hart stoppen.
- `stories/README.md` §5 — Entscheidung abwarten, nicht eigenmaechtig schneiden.
