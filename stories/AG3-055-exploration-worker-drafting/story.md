# AG3-055: Exploration-Worker — worker-exploration.md-Ausfuehrung erzeugt den echten ChangeFrame (BC exploration-and-design)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `exploration-and-design` (BC 5) — implementiert die BC5-Sub `ExplorationDrafting`; die Ausfuehrung ist Worker-Verhalten via Prompt und **nutzt** `agent-skills` (Worker-Spawn) + `prompt-runtime` (`worker-exploration.md`) als konsumierte Infrastruktur (Ownership bleibt beim Exploration-BC)
**Abhaengigkeiten:**
- AG3-045 (ExplorationPhaseHandler + ChangeFrame-**Schema** [FK-23, englische sieben Felder] + Exploration-Gate + Artefakt-/Schutz-/Persistenz-Klempnerei — diese Story **befuellt** das von AG3-045 definierte und validierte Artefakt)
- AG3-044 (WorkerSession / WorkerLoop / HandoverPackager / Worker-Spawn — der Exploration-Worker wird analog zum Implementation-Worker gespawnt)
- AG3-015 (Prompt-Runtime — Materialisierung des `worker-exploration.md`-Templates aus dem gebundenen Prompt-Bundle, FK-44)
- AG3-027 (Skills BC Top-Surface — fachliche Heimat des Workers)

**Quell-Konzepte (autoritativ):**
- `FK-23 §23.3 / §23.3.2` — der Entwurf wird von einem **gespawnten Worker-Agenten** erzeugt; feste sieben Schritte
- `FK-43 §43.3 / §43.3.3` — `execute-userstory` ist der Orchestrator-Skill, der den Worker spawnt
- `FK-44` — Prompt-Bundle / `worker-exploration.md`
- `concept/_meta/bc-cut-decisions.md` — BC `agent-skills` (Worker) vs. BC `exploration-and-design` (Phasen-Handler/Engine)

---

## 1. Kontext

AG3-045 liefert die **deterministische Klempnerei** der Exploration-Phase: Phasen-Handler, Exploration-Gate, ChangeFrame-**Schema** (FK-23, englische sieben Felder), Persistenz- und Schutzmechanik. AG3-045 erzeugt aber **bewusst keinen inhaltlichen Entwurf** (PO-Entscheidung 2026-06-05, Option Y): ein regelbasierter Pseudo-Produzent hat keinen fachlichen Mehrwert und taeuscht dem Gate hohle Entwuerfe als "geprueft" vor.

Das **echte Drafting** ist die `ExplorationDrafting`-Sub des BC `exploration-and-design` (bc-cut §BC5) — der **inhaltliche Kern** der Exploration. Seine **Ausfuehrung** erfolgt laut FK-23 §23.3 als Worker-Verhalten via Prompt (`worker-exploration.md`), gespawnt vom Orchestrator-Skill (`execute-userstory`, FK-43); das **nutzt** `agent-skills` (Worker-Spawn) + `prompt-runtime` als Infrastruktur, die fachliche Ownership bleibt beim Exploration-BC. Diese Story baut genau diese Sub als eigenes Arbeitspaket — getrennt von der AG3-045-Klempnerei.

## 2. Scope

### 2.1 In Scope
- **Exploration-Worker** (implementiert die BC5-Sub `ExplorationDrafting`): wird ueber den bestehenden Worker-Spawn-Pfad (AG3-044 / `execute-userstory`) mit dem materialisierten `worker-exploration.md`-Prompt (AG3-015 / FK-44) gestartet.
- **Die sieben FK-23-§23.3.2-Schritte echt ausgefuehrt** (Story-Verdichtung, Referenzdokument-Recherche, Aenderungsflaechen-Lokalisierung, Loesungsrichtung, Selbst-Konformitaetspruefung, ChangeFrame-Erzeugung) — durch den Agenten, **nicht** regelbasiert gefaked.
- **Erzeugung eines FK-23-konformen ChangeFrame** (englische sieben Bestandteile aus AG3-045s Schema) aus dem realen `StoryContext` + Referenzdokumenten; Persistenz via ArtifactManager (ArtifactClass.ENTWURF) am von AG3-045 definierten Pfad.
- **Anbindung an AG3-045:** der `ExplorationPhaseHandler` konsumiert/validiert den vom Worker erzeugten ChangeFrame; ohne validen Worker-Entwurf bleibt die Phase fail-closed (AG3-045).
- **Test-Determinismus via record-replay:** ein einmal aufgezeichnetes echtes Worker-/LLM-Ergebnis als reproduzierbares Fixture; **kein** genereller deterministischer Produzent.
- **Fail-closed** bei fehlenden Inputs (kein StoryContext, kein Prompt-Bundle, leeres/ungueltiges Worker-Ergebnis).

### 2.2 Out of Scope (mit Owner)
- ChangeFrame-**Schema**, Exploration-**Gate**, Handler, Schutz-/Persistenz-Klempnerei — **AG3-045**.
- **ExplorationReview** (drei-stufiges Exit-Gate) — **AG3-046**.
- **MandateClassification / DesignFreeze** — **AG3-047**.
- **Worker-Loop/Spawn-Basismechanik** — **AG3-044** (wird konsumiert, nicht nachgebaut).
- **PhaseHandlerRegistry-Wiring / Phasen-Dispatch** — **AG3-054**.

## 3. Akzeptanzkriterien
1. Der Exploration-Worker wird ueber den **bestehenden** Worker-Spawn-Pfad (AG3-044) mit dem materialisierten `worker-exploration.md`-Prompt gestartet (kein paralleler Spawn-Pfad).
2. Die sieben FK-23-§23.3.2-Schritte werden **real** ausgefuehrt; der erzeugte ChangeFrame ist FK-23-konform (englische sieben Bestandteile), inhaltlich aus `StoryContext`/Referenzdokumenten **abgeleitet** — keine statischen Story-Konstanten, kein `conformant=True`-Default.
3. Der ChangeFrame wird via ArtifactManager (ENTWURF) am AG3-045-Pfad persistiert; AG3-045s Handler validiert ihn und das Gate kann (nach Review = AG3-046) auf APPROVED gehen.
4. **Fail-closed:** fehlender StoryContext / Prompt-Bundle / leeres Worker-Ergebnis -> kein Artefakt, klare Ablehnung; kein Pseudo-/Teil-Entwurf.
5. **Test-Determinismus:** ein aufgezeichnetes Worker-/LLM-Ergebnis dient als reproduzierbares Fixture; Tests pinnen **nicht** gegen einen nichtdeterministischen Live-Aufruf.
6. **Pflichtbefehle gruen:** pytest unit/integration/contract; mypy default + `--platform linux`; ruff; LOC-Linter 0; vier Konzept-Gates; Coverage >= 85%.

## 4. Definition of Done
- AK 1-6 erfuellt; Aenderungen committed auf `main`; giftige Codex-Review PASS; Jenkins SUCCESS; Sonar Quality Gate OK.

## 5. Guardrail-Referenzen
- **ZERO DEBT / MOCKS-Ausnahme:** echter Worker-Entwurf; record-replay-Fixture nur als Testschnitt an der LLM-/Worker-Grenze.
- **FAIL CLOSED:** ohne validen Entwurf keine APPROVED-Faehigkeit.
- **BC-OWNERSHIP / KEIN GOD-COMPOSITION:** das Drafting ist die `ExplorationDrafting`-Sub des BC `exploration-and-design`; es **nutzt** `agent-skills` (Worker-Spawn) als Infrastruktur, zieht aber keine Pipeline-/Registry-Ownership an sich.
- **ARCH-55 (Englisch verbindlich):** ChangeFrame-Felder/Datenmodell englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Der echte Entwurf ist **Worker-Sache** (FK-23 §23.3), nicht Engine-/Handler-Sache. **Kein** engine-seitiger LLM-Generierungs-Call im Phasen-Handler — das ist nicht das Evaluator-Muster aus AG3-043 (Bewerten != Erzeugen).
- AG3-045 ist der **Konsument/Validator** des Artefakts; diese Story ist der **Produzent**.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. Kein Commit ohne expliziten Auftrag.
