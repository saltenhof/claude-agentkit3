# AG3-240 — Split, Reset, Exit und Story-Kontext ruft der Edge heute als lokale Services auf — inklusive direktem Zugriff auf die Story-Repositories des Kerns.

- **Typ:** implementation
- **Groesse:** L
- **Bounded Context:** `story-lifecycle`
- **Betroffene Subpakete:** `backend/story_split/`, `backend/story_reset/`, `backend/story_exit/`, `backend/story_context_manager/`, `backend/story/` sowie die story-eigenen `state_backend`-Repositories
- **BC-Konzepte:** DK-10, FK-21, FK-24, FK-53, FK-54, FK-56, FK-58, FK-59
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
**story-lifecycle**.

Der Story-Lebenszyklus ist der Vorgang, den der Bediener am Laptop ausloest und
der Kern besitzt. Heute ist beides dieselbe Funktion: `StorySplitService`,
`StoryResetService`, `StoryExitService` und `StoryService` werden auf dem Edge
**instanziiert** und laufen dort — mitsamt den Postgres-Repositories, die sie
brauchen. Die HTTP-Modelle (`*.http_models`) existieren bereits; die Operationen
dahinter fehlen oder werden umgangen.

`backend/story_creation/` gehoert zu diesem BC, ist aber bereits **Edge**
klassifiziert und deshalb kein Ueberquerungsposten.

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
| `story_split` / `story_reset` / `story_exit` / `story_context_manager` / `story` — Verhalten + ungeklaert | 3 / 2 / 2 / 2 / 1 = **10** |
| Grenzverletzungspaare Edge→Kern in diese Subpakete | **18** |
| davon eigene Messung: distinkte Symbole | **22** |
| story-eigene `state_backend`-Repositories | **3** (`story_repository`, `story_read_repository`, `story_lifecycle_store.load_story_context`) |

> **Diese Zahlen sind ein Startpunkt, kein Sollwert.** Sie stammen aus einer
> Vormessung, deren Klassifikator an 59 Symbolen gescheitert ist. Der Umfang
> dieser Story wird in AC 1 **selbst gemessen**. Weicht das Ergebnis ab, gilt
> die eigene Messung — die Abweichung wird benannt, nicht stillschweigend
> uebernommen.

Auffaellig und fuer AC 3 entscheidend: die Haelfte der 22 Symbole sind bereits
`*.http_models`-Paare (`StorySplitMutationRequest`/`-Response`,
`StoryExitMutationRequest`/`-Response`, `StoryResetMutationRequest`/`-Response`).
Das heisst, der Vertrag ist da und wird trotzdem lokal umgangen. Fuer diese
Faelle ist die Arbeit nicht „einen Endpunkt erfinden", sondern **den vorhandenen
Vertrag tatsaechlich benutzen** — und die Modelle selbst gehen als Daten an
AG3-237.

## Scope

### In Scope

- Fuer jede der 18 Ueberquerungen die Antwort (a)/(b)/(c) nach AC 1.
- Split, Reset und Exit laufen ueber ihre `/v1`-Operation statt ueber eine lokal gebaute Service-Instanz. Der Edge behaelt ausschliesslich das Ausloesen und das Anzeigen des Ergebnisses.
- Die Story-Kontext-Abfrage (`load_story_context`, `StoryService`, `resolve_operating_mode`) wird EINE Leseoperation, nicht drei Repository-Aufrufe — AC 3.
- Die story-eigenen `state_backend`-Bindungen in `backend/bootstrap/composition_project.py` entfallen mit ihrem Ersatz.

### Out of Scope

- **`backend/bootstrap/story_reset_adapters.py` (10 Symbole)** — **kein
  Endpunkt.** Das sind die Reset-Adapter (`WorktreePurgeAdapter`,
  `WorkspacePurgeAdapter`, `LockPurgeAdapter`, `ReadModelPurgeAdapter`,
  `RuntimePurgeAdapter`, `AnalyticsPurgeAdapter`, `RunScopeAdapter`,
  `ResetDisownAdapter`, `CompetingOperationAdapter`, `EscalationEvidenceAdapter`),
  die im Composition-Root des Kerns liegen und Edge-Arbeit tun. **Das Modul
  wandert**; Owner AG3-209.

  Diese Story stellt nur sicher, dass das, was die Adapter am Kern erledigen
  muessen (Read-Model- und Analytics-Purge, Lock-Freigabe, Disown), als
  `/v1`-Operation existiert. Ein Adapter, der nach dem Wandern weiterhin
  Kern-Repositories importiert, waere die Verletzung an einer neuen Adresse.
- **`backend/story_creation/`** — bereits Edge, kein Ueberquerungsposten.
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
