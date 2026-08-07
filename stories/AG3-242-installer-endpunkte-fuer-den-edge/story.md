# AG3-242 — Der Installer laeuft auf dem Laptop und ist trotzdem der groesste Kern-Importeur — 48 Grenzverletzungen, davon 35 in der Gegenrichtung.

- **Typ:** implementation
- **Groesse:** M
- **Bounded Context:** `installation-and-bootstrap`
- **Betroffene Subpakete:** `backend/installer/` sowie `backend/process/language/`
- **BC-Konzepte:** DK-08, FK-50, FK-51
- **Abhaengigkeiten:** `depends_on: []` — sofort startbar
- **Blockiert:** `unblocks: ["AG3-209"]`
- **Herkunft:** Orchestrator-Messung 2026-08-07 gegen die in AG3-237
  veroeffentlichte Klassifikation; PO-Entscheid vom 2026-08-07, die
  BC-Endpunktstorys **vor** AG3-209 zu ziehen

## Anlass

AK3 soll auf zwei Maschinen laufen: **Project Edge** auf dem Entwicklerrechner,
**Kern** auf einem zentralen Server. Der Code tut heute so, als waere es eine
Maschine — der Edge ruft Kern-Funktionen als normale Python-Funktionen im selben
Prozess auf. Ueber ein Netz geht das nicht.

Vorgesehen ist die `/v1`-HTTP-Schnittstelle als **einzige** Bruecke zwischen
beiden Maschinen. Sie ist unvollstaendig: fuer einen grossen Teil dessen, was der
Edge heute direkt aufruft, gibt es keine Operation.

**AG3-209 kann diese Luecke nicht schliessen.** Sein Scope verbietet neue
REST-Endpunkte ausdruecklich und verweist auf „eigene Story beim jeweiligen BC"
(`stories/AG3-209-edge-kern-distributionsschnitt/story.md`, Abschnitt
„Out of Scope"). Diese Story ist genau das — fuer den Bounded Context
**installation-and-bootstrap**.

Der Installer ist ein Sonderfall, und deshalb steht er in dieser Liste an einer
eigenen Stelle: Er laeuft **auf dem Entwicklerrechner** (Projektregistrierung,
Hook-/MCP-Materialisierung, Update, Detach) und ist damit Edge — aber er ist
zugleich das Modul, in das der **Kern** am haeufigsten hineingreift. Von den 50
Kern→Edge-Verletzungen des gesamten Repositories zeigen **35 auf
`backend/installer/`**.

Die Richtung ist die gefaehrlichere: Ein Kern, der Installer-Code importiert,
kann ohne installierten Edge nicht starten. Genau das verbietet AG3-209 AC 6
(„`serve` und andere Kernprozesse starten ohne installierte
Edge-Distribution").

## Umfang, gemessen

Gesamtbild vom 2026-08-07, AST-gemessen gegen die in
`concept/formal-spec/architecture-conformance/entities.md` veroeffentlichte
Klassifikation: **354 distinkte Symbole** holt der Edge aus dem Kern, an **638
Importstellen**. 179 davon sind Daten (Modelle, Enums, Konstanten, Ausnahmen) und
werden von **AG3-237** ueber das Vertragspaket geloest — nicht hier. Uebrig
bleiben **116 Verhalten** und **59 ungeklaerte** Symbole; die ungeklaerten sind
die, an denen der Klassifikator der Vormessung an Re-Exporten gescheitert ist.

Die 347 Grenzverletzungen stehen einzeln als
`distribution_boundary_violations.pairs` in `entities.md` (297 Edge→Kern,
50 Kern→Edge). Die Teilmenge dieses BC ist daraus mechanisch ableitbar.

**Fuer diesen BC:**

| Groesse | Startwert |
|---|---|
| `installer` — Verhalten + ungeklaert (Vormessung) | 6 + 0 = **6** |
| Grenzverletzungspaare mit `installer` auf einer Seite | **48** (13 Edge→Kern, 35 Kern→Edge) |
| davon eigene Messung: distinkte Symbole Edge→Kern | **14** |
| `process.language.model` (Flow-DSL des Checkpoint-Engines) | **5** |

> **Diese Zahlen sind ein Startpunkt, kein Sollwert.** Sie stammen aus einer
> Vormessung, deren Klassifikator an 59 Symbolen gescheitert ist. Der Umfang
> dieser Story wird in AC 1 **selbst gemessen**. Weicht das Ergebnis ab, gilt
> die eigene Messung — die Abweichung wird benannt, nicht stillschweigend
> uebernommen.

Die 13 Edge→Kern-Ueberquerungen sind fast vollstaendig die
**Integrations-Checkpoints**: `sonar_preflight`, `ci_preflight`,
`branch_plugin_self_test`, `scanner_harness`, `jenkins_selftest_harness` sowie
`third_party_clients.{SecretResolver, ThirdPartyClientFactory}`. Das sind
Pruefungen gegen SonarQube und Jenkins — **Fremdsysteme, die der Kern erreicht,
nicht der Laptop**. Fuer sie ist (a) die erwartete Antwort, und der Endpunkt hat
eine natuerliche Form: *ein* Preflight-Vorgang mit einem Ergebnisbericht, nicht
fuenf Einzelaufrufe (AC 3).

Die 35 Kern→Edge-Ueberquerungen sind die Gegenrichtung und **kein
Endpunktthema**: der Kern darf Installer-Code schlicht nicht importieren. Ihre
Antwort ist ueberwiegend **(c)**, und wo sie das nicht ist, ist es (b).

`process.language.model` liegt hier, weil seine einzigen Importeure
`installer/checkpoint_engine/{engine,flow}.py` und `installer/upgrade/engine.py`
sind — die Flow-DSL des Checkpoint-Engines. Sein Konzeptdokument traegt keinen
`domain:`-Wert; die Zuordnung folgt dem einzigen Nutzer.

## Scope

### In Scope

- Fuer jede der 48 Ueberquerungen die Antwort (a)/(b)/(c) nach AC 1 — **beide Richtungen**, nicht nur Edge→Kern.
- Die Integrations-Checkpoints gegen SonarQube/Jenkins laufen ueber `/v1`, nicht als lokaler Import. Der Realitaetsnachweis gegen die laufenden Dienste (`localhost:9901`, `localhost:9900`) ist Abnahmekriterium, nicht Opt-in — `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN.
- Der Nachweis, dass **kein** Kernmodul mehr `backend/installer/` importiert.

### Out of Scope

- **`control_plane.third_party_models` (7 Symbole)** — Daten, **Owner
  AG3-237**. Der Installer importiert sie an vier Stellen; das ist die Nutzlast
  der Checkpoint-Operation, nicht die Operation.
- **Die Wheel-Trennung des Installers und sein Entry-Point-Schnitt** — **Owner:
  AG3-209**.
- **AG3-230 (`installer-bringt-alles-mit`)** bleibt unberuehrt; diese Story
  aendert nicht, *was* der Installer ausrollt, sondern *ueber welchen Weg* er
  den Kern erreicht.
- **Die 179 Datensymbole** (Modelle, Enums, Konstanten, Ausnahmen) —
  **Owner: AG3-237**, geloest ueber das Vertragspaket. Diese Story baut keinen
  Endpunkt fuer ein Datum, das im Wire-Paket liegt.
- **Die Paketmigration, die Wheel-Trennung und das Distribution-Gate** —
  **Owner: AG3-209**. Diese Story macht den Schnitt moeglich; sie vollzieht ihn
  nicht.
- **`utils` (5 Symbole), `config` (3) und `boundary` (6)** — der Edge bekommt
  eine **eigene Kopie**. Das ist Duplikation ohne fachliche Entscheidung und
  mechanisch; **Owner: AG3-209**. Ein Endpunkt waere hier schlicht falsch: ein
  Netzaufruf fuer `ensure_dir` oder `atomic_write_text` bezahlt Latenz und einen
  Ausfallpfad fuer Code, den der Edge lokal ausfuehren muss.
- **Jede normative Grundentscheidung.** Taucht eine auf, stoppt die Story und
  legt sie dem PO vor; sie wird nicht durch einen Endpunkt-Default ersetzt.

## Akzeptanzkriterien

1. **Der eigene Umfang ist gemessen, nicht uebernommen.** Jede Ueberquerung
   dieses BC ist einzeln aufgefuehrt und traegt genau **eine** von drei
   Antworten:
   - **(a) gehoert ueber die Schnittstelle** → ein `/v1`-Endpunkt wird gebaut
     oder erweitert, dazu ein duenner Client auf der Edge-Seite;
   - **(b) ist Edge-Logik, im Kern falsch einsortiert** → das Modul wandert;
     **kein** Endpunkt;
   - **(c) darf nicht stattfinden** → der Aufruf entfaellt, mit Begruendung.

   Eine Ueberquerung ohne Antwort ist ein Verstoss gegen dieses Kriterium, kein
   Restposten. Die Messung ist reproduzierbar: Kommando und Ergebnis liegen im
   Story-Record.

2. **Der BC zaehlt am Ende NULL Grenzverletzungen.** Nachgewiesen mit einer
   **Suche mit Zahl** gegen den Arbeitsbaum, nicht durch Sichtpruefung. Die
   Ausgangsmenge ist die aus `distribution_boundary_violations.pairs`
   abgeleitete Teilmenge dieses BC; sie wird zu Beginn und am Ende mit demselben
   Kommando gerechnet, und beide Zahlen stehen im Record.

3. **Kein Endpunkt ohne Bedarf.** Mehrere Aufrufe desselben fachlichen Vorgangs
   werden **EINE** Operation, nicht drei. Wer heute drei Repository-Funktionen
   nacheinander ruft, bekommt **einen** Endpunkt, der den Vorgang als Ganzes
   ausdrueckt. Je Endpunkt steht im Record, welche heutigen Aufrufstellen er
   ersetzt; ein Endpunkt ohne Aufrufstelle wird nicht gebaut.

4. **Neue Endpunkte sind katalogisiert und vertraglich verankert.** Jeder neue
   oder erweiterte Endpunkt steht in **FK-91 §91.1** und im `/v1`-Vertrag
   (Pfad, Verb, Request-/Response-Schema, Fehlerfaelle). Ein Endpunkt, der nur
   im Code existiert, gilt als nicht geliefert.

5. **Alle sechs bindenden deterministischen Konzept-Gates sind gruen**
   (`AGENTS.md`; W2/W3 sind seit der PO-Entscheidung 2026-08-02 kein
   Abnahmekriterium und werden nie als „gruen" mitgezaehlt); Referenzintegritaet
   ohne neue Baseline-Eintraege.

   **Zusaetzlich, bei jeder Aenderung an der Formal Spec:** `check.py formal`
   und `check.py frontmatter` aus
   `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/`.
   Die Repo-Gates erzwingen einen **anderen** Vertrag als der ausgelieferte
   Parser — in AG3-237 waren dadurch **vier Fehler bei sechs gruenen Gates
   unsichtbar**. Beide Werkzeuge laufen, beide Ergebnisse stehen im Record.

6. **Neue Business-Logik hat Unit-Tests, Negativpfade an den Phasengrenzen sind
   bewiesen.** Fuer jeden neuen Endpunkt mindestens: fehlende/ungueltige
   Autorisierung, unbekannte Story-/Objekt-Identitaet und der fail-closed
   Ausgang bei nicht erreichbarem Kern. Ein Test, der nur den Gutfall zeigt,
   erfuellt dieses Kriterium nicht.

## Wo diese Story unsicher ist

**`backend/process/language/` liegt hier, und das ist eine Wahl.** Das Paket
hat kein Konzeptdokument mit `domain:`-Wert. Die Zuordnung folgt ausschliesslich
dem gemessenen Nutzungsbild: alle drei Importeure liegen in
`backend/installer/`. Findet AC 1 einen weiteren Nutzer ausserhalb des
Installers, ist die Zuordnung falsch und der Posten geht zurueck an den PO.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg: Kommando, Locator, Testname oder
  Reviewbeleg.
- Die Messung aus AC 1 liegt reproduzierbar im Story-Record — Kommando,
  Rohergebnis und die Zuordnung (a)/(b)/(c) je Ueberquerung.
- Anfangs- und Endzahl aus AC 2 stehen im Record, mit demselben Kommando
  gerechnet.
- `ruff` und `mypy` gruen; die von der Aenderung betroffene Test-Teilmenge ist
  lokal gruen. **Der vollstaendige Testnachweis kommt ausschliesslich aus
  Jenkins** (`AGENTS.md`, PO-Anweisung 2026-08-04) — ein lokaler
  `pytest`-Lauf ohne Pfadangabe ist untersagt.
- Unabhaengiges Codex-Review bis zu einem der Abbruchkriterien aus `CLAUDE.md`.

**PO-Vorgabe vom 2026-08-07, woertlich:**

> **Hoechstens DREI QS-/Remediation-Runden.** Ist die Story nach der dritten
> Runde nicht abnahmereif, wird sie **an den PO eskaliert** statt eine vierte zu
> fahren. Das ist eine harte Kappung, keine Richtgroesse.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — jede Ueberquerung bekommt eine Antwort; eine
  offen gelassene ist eine Schuld mit Zinseszins, kein Restposten.
- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — kein Endpunkt neben dem
  weiterlebenden Direktaufruf. Der Schnitt wird an einer Stelle gemacht.
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — AC 3: ein Endpunkt bildet den
  fachlichen Vorgang ab, nicht die heutige Aufrufreihenfolge.
- `CLAUDE.md` §FAIL-CLOSED — AC 6: ein nicht erreichbarer Kern hat einen
  normierten Ausgang, keinen lokalen Ersatzstate.
- `guardrails/testing-guardrails.md` — Negativpfade an den Phasengrenzen.
- `guardrails/test-execution-efficiency.md` R1–R4 — innere Schleife nur auf der
  betroffenen Teilmenge. **Die volle Testsuite laeuft ausschliesslich auf
  Jenkins** (`AGENTS.md`, PO-Anweisung 2026-08-04).
