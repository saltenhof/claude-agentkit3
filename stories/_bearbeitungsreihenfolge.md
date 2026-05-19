# Bearbeitungs-Reihenfolge (Welle 2026-05-19+)

**Zweck**: Konkrete Bearbeitungsreihenfolge fuer die offenen Stories, die
sich aus dem topologischen `depends_on`-Graph in
`_story-schnitt-aus-themen.md §2` + den Stefan-Entscheidungen
vom 2026-05-19 ergibt.

Diese Datei ist *operative Arbeitsliste*. Sie wird nach jeder abgenommenen
Story aktualisiert (Status `done`/`completed`). Bei neuen User-Entscheidungen
(z. B. Splits, Vollumsetzungen) werden Reihenfolge **und** Begruendung hier
eingetragen — das Kontextgedaechtnis des Orchestrators ist KEINE persistente
Wahrheit.

---

## 1. Reihenfolge der aktuellen Welle

| # | Story | Groesse | Status | Vorbedingung erfuellt? |
|---|---|---|---|---|
| 1 | AG3-026 VerifySystem Top-Surface | M | in_progress (2026-05-19) | ja (AG3-021/022/023 done) |
| 2 | AG3-029 KpiAnalytics Top + Paket-Migration | M | blocked | nach AG3-026 ja |
| 3 | AG3-030 RequirementsCoverage Top + AreClient | M | blocked | nach AG3-026 ja |
| 4 | AG3-027 Skills Top-Surface (schlank) | M | blocked | nach AG3-026 ja |
| 5 | AG3-031 Governance Top-Surfaces | M | blocked | nach AG3-026 ja |
| 6 | AG3-035 ProjectionAccessor + Reset-Purge | M | blocked | nach Top-Surfaces ja |
| 7 | AG3-040 Postgres-Store-Komplettierung | M | blocked | nach AG3-035 + AG3-028? Lesehinweis: AG3-040 depends_on AG3-021 + AG3-028 — siehe Anmerkung 1 |
| 8 | AG3-028 FailureCorpus (Vollumsetzung) | L | blocked | nach AG3-035 + AG3-040 |
| 9 | AG3-048 Skills-Persistenz + Installer + Hygiene | M | blocked | nach AG3-027 |

**Anmerkung 1 (Zyklus-Vermeidung AG3-028 / AG3-040):** Der topologische Graph
zeigt einen scheinbaren Zyklus: AG3-040 deklariert `depends_on: AG3-028`
(weil es die `fc_`-Tabellen mitnimmt), AG3-028 deklariert nach
User-Entscheidung 2026-05-19 jetzt `depends_on: AG3-040`. Aufloesung in der
Praxis: AG3-040 wird in zwei Sub-Bloecken umgesetzt — (a) `Postgres-Store-
Komplettierung ohne fc_-Tabellen` zuerst (befriedigt AG3-028-Dep), (b)
`fc_-Tabellen-Block` als Teil von AG3-028 selbst (dort liegt der
Schema-Owner laut FK-69). Der Worker fuer AG3-040 muss diesen Schnitt
respektieren; der `depends_on: AG3-028` in AG3-040.status.yaml verweist
nur auf den `fc_-Tabellen`-Block, der mit AG3-028 zusammenfaellt.

## 2. Begruendung der Reihenfolge

**AG3-026 zuerst (Top-Surface der Capability):**
VerifySystem ist die zentrale Capability, an der pipeline-framework,
implementation-phase, exploration-and-design alle haengen. Foundation
(021/022/023) ist done, also kann 026 sofort starten.

**AG3-029 / AG3-030 vor AG3-027 / AG3-031:**
Beide sind klar isoliert und etablieren BC-Top-Surfaces, die unabhaengig
voneinander pruefbar sind. Niedrige Komplexitaet (Paket-Migration und
no-op-Aktivierungslogik) — gute Aufwaerm-Stories nach AG3-026.

**AG3-027 (M, schlank) vor AG3-031:**
Skills-Top-Surface kann jetzt zuegig durch, weil Persistenz und Installer
in AG3-048 ausgelagert sind. AG3-031 (Governance-Hooks) ist konzeptuell
schwerer (Trust-Boundary-Anschluss) und kommt danach.

**AG3-035 + AG3-040 vor AG3-028:**
AG3-028 wurde am 2026-05-19 von "Top-Surface mit Protocol/Fake" auf
"vorgezogene Vollumsetzung" hochgestuft (Stefan-Entscheidung). Damit
braucht es `Telemetry.write_projection` produktiv — das liefert AG3-035
(ProjectionAccessor) und AG3-040 (Postgres-Store-Komplettierung).
Reihenfolge zwingend: erst Telemetry-Infrastruktur, dann FailureCorpus.

**AG3-048 zuletzt:**
Folge-Story zu AG3-027 (siehe Split-Entscheidung 2026-05-19). Setzt
auf den fertigen Skills-Top-Surface auf und bringt SQLite/Postgres-
Persistenz + BC12-Installer-Andockung + Repo-Hygiene mit.

## 3. Stefan-Entscheidungen 2026-05-19 (zur Nachvollziehbarkeit)

- **AG3-027 Split (Variante A)**: Top-Surface schlank halten (M), drei
  ausgelagerte Bereiche in AG3-048 (M):
  - `skill_bindings`-Tabelle in state_backend
  - `installer/runner.py` Andockung (BC12)
  - `__pycache__`-Cleanup in `src/agentkit/project_ops/install/`
- **AG3-028 Vollumsetzung (Variante A)**: produktiver Schreibpfad
  ueber `Telemetry.write_projection` statt InMemory-Fake. Size M -> L,
  `depends_on` ergaenzt um AG3-035 + AG3-040.

## 4. Nach der Welle (THEME-006+)

THEME-006 (Governance/Trust-Boundary), THEME-007 (Telemetrie-Restbloecke),
THEME-008 (Persistenz-Restbloecke), THEME-009 (QA-Kernlogik) und
THEME-010 (Exploration-Phase) folgen nach Abschluss der hier
gelisteten Welle. Reihenfolge ergibt sich erneut aus
`_story-schnitt-aus-themen.md §2` plus etwaiger spaeterer
User-Entscheidungen.

## 5. Pflege-Regel

Wenn der Orchestrator eine Story abnimmt (User-OK + `status: completed`),
wird der Eintrag in der Tabelle (§1) auf `done` gesetzt und das
**naechste** Element wird zum aktuellen "WIP". Wenn neue Entscheidungen
die Reihenfolge aendern (Splits, Re-Prioritisierungen), wird sowohl §1
als auch §2 entsprechend ergaenzt — ohne diese Pflege ist die Datei
wertlos.
