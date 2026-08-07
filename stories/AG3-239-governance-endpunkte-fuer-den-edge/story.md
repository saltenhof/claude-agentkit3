# AG3-239 — Der Hook-Prozess auf dem Laptop erreicht heute die halbe Governance des Kerns als Python-Import — 42 Grenzverletzungen, der groesste Einzelposten des Distributionsschnitts.

- **Typ:** implementation
- **Groesse:** L
- **Bounded Context:** `governance-and-guards`
- **Betroffene Subpakete:** `backend/governance/` sowie die governance-eigenen Repository-Bindungen in `backend/state_backend/store/`
- **BC-Konzepte:** DK-03, FK-22, FK-30, FK-31, FK-35, FK-42, FK-55
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
**governance-and-guards**.

Kein anderer BC steht dem Schnitt so im Weg. Die Guard-Engine **muss** auf dem
Laptop bleiben — sie entscheidet synchron im Hook-Prozess, bevor ein Werkzeug
laeuft; ein Netzaufruf pro Tool-Use waere weder schnell genug noch verfuegbar
genug. Zugleich gehoeren `PolicyEngine`, `IntegrityGate`, die
Capability-Adjudication und jede Form von Persistenz in den Kern (FK-01 §1.1a).
Die Grenze verlaeuft also **mitten durch** `backend/governance/`, und heute
ueberquert sie der Code an 42 Stellen per Import.

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
| `governance` — Verhalten + ungeklaert (Vormessung) | 17 + 16 = **33** |
| Grenzverletzungspaare mit `governance` auf einer Seite | **42** (33 Edge→Kern, 9 Kern→Edge) |
| davon eigene Messung: distinkte Symbole aus `governance` | **54** |
| governance-eigene `state_backend`-Repositories | **4** (`governance_hook_repository`, `lock_record_repository`, `freeze_repository` mit 2 Symbolen) |

> **Diese Zahlen sind ein Startpunkt, kein Sollwert.** Sie stammen aus einer
> Vormessung, deren Klassifikator an 59 Symbolen gescheitert ist. Der Umfang
> dieser Story wird in AC 1 **selbst gemessen**. Weicht das Ergebnis ab, gilt
> die eigene Messung — die Abweichung wird benannt, nicht stillschweigend
> uebernommen.

Die 54 Symbole verteilen sich auf drei klar unterscheidbare Gruppen, und die
Gruppe entscheidet ueber die Antwort in AC 1:

- **Guard-Ausfuehrung** (`guards/*`, `guard_system.*`, `guard_evaluation`,
  `protocols.GovernanceGuard`, `capability_blocks`) — laeuft im Hook-Prozess,
  also Edge. Erwartete Antwort: **(b)**, das Modul wandert.
- **Adjudikation und Zustand** (`principal_capabilities/*` mit 9 Symbolen,
  `integrity_gate/`, `setup_preflight_gate/`, `locks`, `repository`,
  `hook_registration`, `guard_system.records`) — Kern. Erwartete Antwort:
  **(a)**, Endpunkt.
- **Vokabular** (`protocols.GuardVerdict`, `protocols.ViolationType`,
  `hook_ids.*`, `errors.*`) — Daten, **Owner AG3-237**.

Erwartet heisst hier ausdruecklich: als Hypothese der Vormessung. AC 1 prueft
sie, es uebernimmt sie nicht.

## Scope

### In Scope

- Fuer jede der 42 Ueberquerungen die Antwort (a)/(b)/(c) nach AC 1.
- Die `/v1`-Operationen, die der Hook-Prozess fuer Capability-Adjudication, Hook-Registrierung, Lock-Verwaltung und Freeze-Abfrage braucht — als **fachliche Vorgaenge**, nicht als Repository-Spiegel.
- Die governance-eigenen `state_backend`-Repository-Bindungen im Edge-Composition-Root `backend/bootstrap/composition_project.py` entfallen mit ihrem Ersatz. Die Datei ist zwischen mehreren Storys geteilt; jede fasst ausschliesslich ihre eigenen Bindungen an.

### Out of Scope

- **`governance/hook_event_inputs.py` (11 gemessene Symbole)** — **kein
  Endpunkt.** Das Modul ist Edge-Logik, die im Kern falsch einsortiert ist; es
  **wandert**, Owner AG3-209 (dort Eingangsliste **E6**).

  Es ist zusaetzlich ein **Sicherheitsdefekt**: `governance/runner.py:48`
  importiert es, und `hook_event_inputs.py:46` zieht ueber einen lazy Import von
  `bootstrap.composition_root.build_skills` den **gesamten Kern in den
  Hook-Prozess** — `verify_system`, `pipeline_engine`, `state_backend`
  eingeschlossen. Genau diese eine Kante steht AG3-209 AC 3 im Weg („aus dem
  Hook-Prozess ist weder `psycopg` noch ein Postgres-Repository erreichbar").
  Diese Story **loest den Defekt nicht** — sie stellt sicher, dass die
  Skill-Bindungsabfrage, die er heute erschleicht, als `/v1`-Operation existiert
  (Owner der Operation: **AG3-243**, agent-skills) und dass er nach dem Schnitt
  nicht durch einen neuen Endpunkt plausibel gemacht wird.
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

**`backend/integration_stabilization/` (10 Symbole, 4 Verletzungspaare) liegt
hier, und das ist eine Wahl, keine Ableitung.** Sein Konzeptdokument
`concept/technical-design/05_integration_stabilization_contract.md` traegt
`cross_cutting: true` und damit **keinen** `domain:`-Wert — der BC-Schnitt gibt
die Zuordnung nicht her. Fachlich sind `FailClosedSeamGuard`,
`SeamAllowlistGuard` und `StabilizationBudgetGuard` Guards, die im Hook-Prozess
entscheiden, und `check_approval_present` / `check_binding_integrity` sind
Vorbedingungspruefungen derselben Art. Deshalb hier.

**Der PO darf das umhaengen.** Wird es umgehaengt, wandert der Posten
vollstaendig mit — er ist in dieser Story sauber abgegrenzt und beruehrt die
uebrigen 42 Ueberquerungen nicht.

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
