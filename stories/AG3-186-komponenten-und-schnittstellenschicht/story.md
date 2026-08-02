# AG3-186 — Komponenten- und Schnittstellenschicht ausdetaillieren

- **Typ:** concept
- **Groesse:** **TBD** — erst nach dem Metaentscheid AG3-203 bestimmbar
  (bewusst ausserhalb des `S|M|L`-Enums aus `stories/README.md` §2.1)
- **Abhaengigkeiten:** `depends_on: ["AG3-203", "AG3-200", "AG3-202"]`;
  entblockt AG3-204
- **Quell-Konzept:** FK-07, FK-17, FK-18, `concept/formal-spec/`,
  `concept/technical-design/_meta/*.yaml`
- **Herkunft:** PO-Vorgabe vom 2026-08-02; Befund C-4 im Werkstattbericht. Neu
  geschnitten am 2026-08-02 nach unabhaengigem Codex-Review (Auflagen ERROR-17
  und ERROR-18).

## Kontext

### Warum die Story blockiert ist

Der urspruengliche Schnitt stand auf `ready` und formulierte seine
Akzeptanzkriterien bereits auf „die Schicht wird eingefuehrt" — obwohl er in
seiner eigenen Abgrenzung feststellte, dass er „eine PO-Entscheidung auf
Meta-Konzeptebene braucht, bevor sie beginnt". Diese Entscheidung ist jetzt
**AG3-203**; diese Story detailliert aus, was dort beschlossen wird.

Zusaetzlich haengt sie an **AG3-200** (die Blueprint-Belegbasis war fluechtig)
und an **AG3-202**. Der letzte Punkt folgt der Empfehlung aus
`D-offene-entscheidungen.md` E7: die Komponentenschicht ist „genau die Art von
Vorhaben, fuer die das neue Verfahren gebaut wird (mehrere Autoritaeten, echte
Weichen, Migration von Bestand) — sie ist damit **sein erster echter
Anwendungsfall statt seine Vorbedingung**".

### Befund — der Ist-Zustand, den die Schicht adressiert

AK3 kennt heute zwei Konzeptschichten: **Prosa** und den **Formal-Layer**.
Dazwischen fehlt eine Schicht, die Komponenten- und Schnittstellenbeschreibung
traegt.

*Vorhanden:* FK-07 mit normativem Top-Level-Schnitt (§7.4), verbindlichen
Importgrenzen (§7.8), messbaren Invarianten (§7.9) und einem deterministischen
Checker gegen den Python-Code (§7.7) — also genau die Bauphasen-Bindung, die der
Blueprint ausklammert. Dazu `bounded-contexts.yaml` und `domain-registry.yaml`.

*Nicht vorhanden* (C-4.3, fuenf Punkte):

1. **Keine maschinenlesbare Component als Objekt.**
   `concept/technical-design/_meta/module-registry.yaml` ist eine flache
   Namensliste ohne `responsibility`, `owns`, `provides`, `requires`.
2. **Kein Portobjekt.** FK-07 §7.2 Nr. 6 spricht von „veroeffentlichten Ports
   der owning Components" — als **Prosa**. Keine Portidentitaet, keine
   `operations[]`, kein `contract_ref`, keine `visibility`, keine
   `consumers[]`. Der Praezisionsboden `S5` ist damit nicht einmal
   formulierbar.
3. **Keine Konsumart an der Kante.** Die Architekturpruefung arbeitet auf dem
   **Importgraphen** — der kennt nur eine Kantenart. Genau daraus entstanden im
   Blueprint zweistellig viele Falschzyklen (`KW-C4`).
4. **Kein `KW-L0`-Aequivalent.** Ob ein *Feld* eine Referenzkante traegt, ist
   nirgends deklariert — genau die Luecke, aus der der Blueprint-Anlassfall
   entstand.
5. **Kein Ort fuer die Repository-Projektion.** FK-07 §7.6 fuehrt eine
   „Repository-Regel", `PROJECT_STRUCTURE.md` die Verzeichnisstruktur — beides
   Prosa, beides nicht als Ebene mit Eigentum und Vertrag modelliert.

**Der Blueprint hilft nur zur Haelfte, und das ist der wichtige Punkt.** Dort
ist die Komponente **strikt kontextgebunden**, und die Codeprojektion ist
ausdruecklich ausgeklammert („eine benannte Grenze ist das Gegenteil einer
Luecke"). Der PO will genau die Flaeche, die der Blueprint offenlaesst. AK3 hat
umgekehrt die Codeprojektion und kein Komponentenobjekt. Die beiden Projekte
sind an dieser Stelle **komplementaer**, nicht deckungsgleich — der Blueprint
ist **Anschlussstelle, nicht Vorlage**.

### Was am ersten Schnitt falsch war

- **AC3 („Ein Komponentenobjekt existiert") war durch ein leeres Schema
  erfuellbar.** Ein Schema ohne Instanzen ist kein Objekt.
- **AC6 („`module-registry.yaml` ist abgeloest oder als das ausgewiesen, was
  es ist") war durch blosses Etikettieren erfuellbar.**
- **Die normative Betroffenheit war unvollstaendig** — es fehlten FK-17/FK-18
  und die bestehenden Fact-/Ownership-Zustaendigkeiten, der Autoritaetsvorrang,
  die geprueften Namensraeume, die Konsumart, die Trennung Signatur/Semantik,
  die Vollstaendigkeitsregel der Registry und die Migration des Bestands.

## Scope

### In Scope

- Die Ausdetaillierung der Schicht **entlang des Metaentscheids aus AG3-203**.
- Die vollstaendige Betroffenheitsmatrix inklusive der Migration des Bestands.
- Die Durchfuehrung nach dem in AG3-185/AG3-201 normierten und in AG3-202
  erprobten Verfahren.

### Out of Scope

- **Kein Code.** Register, Port-Schema und Architektur-Checker sind **AG3-204**.
- **Keine Grundentscheidung** — die faellt in AG3-203. Weicht die
  Ausdetaillierung davon ab, ist das ein Fehler, keine Auslegung.
- **Keine Uebernahme des Blueprints als Ganzes.** Uebernommen wird der
  projektunabhaengige Verfahrensanteil; das Nachbarprojekt hat eine andere
  Fachdomaene und eine andere Reifephase.
- Die Uebernahme des Blueprint-`.gitignore`-Musters (C-10).

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md` | geaendert | Naht zur neuen Schicht, §7.2 Nr. 6, §7.6, §7.7 |
| `concept/technical-design/17_fachliches_datenmodell_ownership.md` | geaendert | Verhaeltnis Komponenten-Eigentum zu Fact-Ownership |
| `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` | geaendert | dito, soweit beruehrt |
| Neue Konzeptflaeche (Ort nach AG3-203) | neu | die Schicht selbst |
| `concept/technical-design/_meta/module-registry.yaml` | abgeloest oder ersetzt | traegt den Vertrag heute nicht |
| `concept/formal-spec/` | geaendert | nur falls AG3-203 die Objektart dort verortet |
| `PROJECT_STRUCTURE.md` | geaendert | nur falls die Schicht den Repo-Schnitt traegt |
| `concept/_meta/assertion-authority.md` | geaendert | Autoritaetsrang |
| `concept/_meta/decisions/2026-XX-XX-komponentenschicht.md` | neu | Decision Record mit vollstaendiger Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Die Schicht ist als eigene Konzeptflaeche definiert**, mit Zweck,
   Abgrenzung nach oben (Prosa) und unten (Formal-Layer), und einer klaren
   Aussage, wovon sie **nicht** handelt. Der Massstab ist der aus dem
   Blueprint: *„Welche Aussage wird unmoeglich, wenn ich die Ebene streiche?"*
   — die Antwort steht ausgeschrieben da.
2. **Die Orthogonalitaet zu den Bounded Contexts ist ausgeschrieben**, nicht
   behauptet: an mindestens zwei **realen** Beispielen aus AK3, in denen der
   Repo-/Artefaktschnitt vom BC-Schnitt abweicht, mit der Begruendung, warum
   die Abweichung richtig ist.
3. **Ein Komponentenobjekt existiert — mit Instanzen, nicht nur als Schema.**
   Identitaet, Eigentuemer, Schnittstellen. Ein leeres oder nur beispielhaft
   befuelltes Schema erfuellt dieses Kriterium **nicht**: der bestehende
   AK3-Bestand ist abgebildet (AC 9). Ein Bezeichner, der ausschliesslich in
   einem `owner:`-Feld vorkommt, ist kein Eigentuemer, sondern ein Etikett.
4. **Schnittstellenvertraege haben einen Mindestpraezisionsboden**, und der ist
   ausgeschrieben. Ein *wirksamer* Port — jemand nennt ihn im Bedarf, oder der
   Anbieter ist bindbar — traegt mindestens Operationen, Parameternamen,
   Parametertypen und Rueckgabetyp (`KW-C2`, `S5`). Ein Port, der nur in Prosa
   existiert, erfuellt ihn nicht.
5. **Geprueft Namensraeume ohne implizite Komponentenerzeugung.** Jedes Feld,
   dessen Wert ein Bezeichner ist, deklariert seinen Zielnamensraum und ist
   damit eine **gepruefte Referenzkante** (`KW-L0`). Ein unbekannter Eigentuemer
   erzeugt **nie** implizit einen Eintrag (`KW-L1`–`L3`); operativ: *der
   Aenderungssatz, der einen Eigentuemerwert einfuehrt, enthaelt die
   Definition.*
6. **Die Konsumart `sync|async` sitzt an der Consumer-Kante**, nicht am Port
   (`KW-C4`). Begruendung: ein realer Lauf meldete zweistellig viele Zyklen,
   von denen kein einziger einer war, weil das Modell nur eine Kantenart kannte
   — und AK3s Importgraph kennt heute genau eine.
7. **Maschinenlesbare Signatur und Provider-seitige Semantik sind getrennt.**
   Signatur und Kante leben in der Registry, die **Semantik ausschliesslich in
   der Prosa des Anbieters**. Ein Registryeintrag mit prosaischem Vertragssatz
   im Freitextfeld ist bereits der Fehler.
8. **Der Autoritaetsvorrang bei Konflikt ist entschieden und steht da:** wer
   gewinnt zwischen Portspezifikation und Prosavertrag. (Im Blueprint §4.6 fuer
   Ports ausdruecklich **nicht** geklaert; die Entscheidung faellt in AG3-203
   und wird hier ausgeschrieben.)
9. **Die Vollstaendigkeitsregel der Registry ist ausgeschrieben und der
   Bestand ist migriert.** `KW-H1`: eine formale Schicht darf bewusst
   **partiell** sein, die Komponentenebene **nicht**. Der bestehende
   AK3-Bestand ist abgebildet — nicht ein Beispiel-Ausschnitt. Der Migrationsweg
   ist beschrieben und die Restmenge ist beziffert.
10. **`module-registry.yaml` ist abgeloest oder ersetzt.** Ein blosses Etikett
    („ist eine flache Namensliste") erfuellt dieses Kriterium **nicht**: nach
    dieser Story existiert entweder kein Konsument mehr, oder die Datei traegt
    den Vertrag.
11. **Das Verhaeltnis zu FK-07 und zum Architektur-Checker ist geklaert:** was
    projiziert die neue Schicht, was prueft der Checker, und wo genau ist die
    Naht. Es entsteht **keine zweite Wahrheit** ueber den Repo-Schnitt. Ebenso
    geklaert: das Verhaeltnis zu den bestehenden Fact-/Ownership-Zustaendigkeiten
    aus **FK-17** und **FK-18**.
12. **Der Blueprint ist ausgewertet und die Differenz benannt:** was uebernommen
    wird, was bewusst nicht, und wo AK3 weiter geht als das Nachbarprojekt (die
    Codeprojektion) beziehungsweise hinterherhinkt (das Komponentenobjekt). Die
    Auswertung stuetzt sich auf die dauerhafte Belegbasis aus **AG3-200**.
13. **Die Arbeit laeuft nach dem in AG3-185/AG3-201 normierten und in AG3-202
    erprobten Verfahren** — Entwurf im Inkubator, unabhaengige mehrdimensionale
    Pruefung, Migration, Migrationstreue-Pruefung.
14. **Alle deterministischen Konzept-Gates gruen**; Decision Record mit
    **vollstaendiger** Betroffenheitsmatrix, die mindestens FK-07, FK-17,
    FK-18, `module-registry.yaml`, `assertion-authority.md`,
    `PROJECT_STRUCTURE.md` und den Formal-Layer-Vertrag mit je einer
    Zielentscheidung fuehrt.

## Definition of Done

- AC 1–14 erfuellt, jedes mit benanntem Beleg.
- Die Groesse dieser Story ist nach AG3-203 gesetzt worden (nicht mehr `TBD`).
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.2 Nr. 6, §7.4, §7.6, §7.7, §7.8, §7.9
- `concept/technical-design/17_fachliches_datenmodell_ownership.md`
- `concept/technical-design/18_relationales_abbildungsmodell_postgres.md`
- `concept/technical-design/_meta/module-registry.yaml`,
  `bounded-contexts.yaml`, `domain-registry.yaml`
- `concept/_meta/assertion-authority.md`
- `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-4 (C-4.1 bis C-4.3), C-10, C-12; `D-offene-entscheidungen.md` E7
- Der Metaentscheid aus AG3-203 (Decision Record)

## Guardrail-Referenzen

- `AGENTS.md` (Agentenmandat) — diese Story detailliert aus; sie entscheidet
  nicht.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — AC 11: keine zweite Wahrheit
  ueber den Repo-Schnitt.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 3, AC 9, AC 10: kein leeres Schema, kein
  Etikett.
- `CLAUDE.md` „Council-Orchestrator" — Rollentrennung bei Konzeptarbeit im
  Incubator; nach E7 ist dies ein Council-Fall mit Vollstaendigkeitsanspruch.
