# AG3-178 — Periodischer Full-Reindex / Index-Hygiene fuer den Konzept-Korpus

- **Typ:** implementation (noch nicht geschnitten — siehe „Status")
- **Status:** blocked — **Design-offen**. Erst PO-/Konzeptentscheidung, dann Schnitt.
- **depends_on:** [AG3-174 (Engine, `concept_sync`, Bounded-Window), AG3-176
  (Post-Commit-Hook-Integration, inkrementeller Sync)]
- **Herkunft:** PO-Idee 2026-07-30, entstanden bei der AG3-176-Konzept-
  Konsistenzarbeit (Entscheidung: Post-Commit = inkrementell).

## Kontext / Problem

AG3-176 stellt den Post-Commit-Concept-Sync korrekt auf **inkrementell** (nur die
im Commit geaenderten Konzepte werden nachgezogen); der Erstindex bei der
Installation (CP10a) bleibt ein voller Reindex. Das ist der richtige Normalpfad
fuer Daten-Korrektheit und Performance.

**Was inkrementell NICHT abdeckt, ist Index-Hygiene.** Vektor-DBs (Weaviate /
HNSW) sammeln bei dauerndem Upsert/Delete ueber die Zeit **Tombstones und
Graph-Fragmentierung** an. Die *Daten* koennen dabei korrekt bleiben, aber die
**Index-/Collection-Struktur selbst degeneriert** — der Suchindex wird langsam
schlechter (Qualitaet/Latenz), obwohl kein Datenfehler vorliegt. Ein
gelegentlicher **garantierter kompletter Neuaufbau (drop + rebuild)** zieht einen
sauberen Index wieder hoch und schliesst zugleich jede theoretisch akkumulierte
Drift aus.

Dies ist ein **Ops-/Hygiene-Thema**, kein Korrektheitsfehler des inkrementellen
Pfads. Wuerde ein Full gebraucht, um Daten-Drift zu korrigieren, waere das
Inkrementelle defekt — das ist hier ausdruecklich NICHT gemeint.

## PO-Design-Intent (2026-07-30, festzuhalten, noch nicht final entschieden)

- Normalbetrieb bleibt **inkrementell**; **ab und zu** ein garantierter
  **Full-Rebuild** als Hygiene.
- **Trigger primaer ueber Aenderungs-Prozentsatz der Konzeptbasis** seit dem
  letzten Full-Rebuild (z. B. „N % der Konzeptbasis geaendert") — der PO haelt
  das fuer sauberer als einen reinen Kalender-Trigger, weil es am tatsaechlichen
  Aenderungs-/Degenerationsrisiko haengt.
- **Optionale Zeit-Obergrenze** als Sicherheitsnetz (Hybrid: „N % geaendert
  **oder** maximal X Tage"), damit auch ein fast statischer Korpus irgendwann
  einen sauberen Rebuild bekommt.

## Offene Design-Entscheidungen (fuer die gemeinsame Konzept-Session)

Diese Fragen sind VORAUSLAUFEND mit dem PO zu klaeren und normativ zu verankern,
bevor geschnitten/implementiert wird:

1. **Trigger-Metrik + Schwellwert.** Wie wird „% der Konzeptbasis geaendert"
   gemessen (geaenderte Dateien? Chunks? Content-Hash-Delta?) und relativ wozu
   (Sollmenge seit letztem Full)? Konkreter Default-Schwellwert. Ob/welche
   Zeit-Obergrenze.
2. **Wo lebt der Zaehler / Zustand.** Ein durabler, projektgebundener Stand
   (analog `corpus_revision`/Completion-Ledger der AG3-174-Engine): „geaenderte
   Menge seit letztem Full-Rebuild". Kein neuer ungetypter State-Faecher.
3. **Wer loest den Full aus.** (a) der Post-Commit-Hook prueft den Zaehler und
   faehrt bei Ueberschreiten ausnahmsweise einen Full statt inkrementell (macht
   einzelne Commits selten langsam), oder (b) ein separater, nicht-blockierender
   Wartungs-/Scheduled-Task ausserhalb des Commit-Pfads. Trade-offs
   (Einfachheit vs. Latenz-Isolation) abwaegen.
4. **Rebuild-Semantik.** Nutzt der Full-Rebuild den bereits verankerten
   Bounded-Window-Shadow-Replace der Engine (neue Generation schreiben, dann alt
   loeschen — kein Ausfallfenster), sodass Leser waehrend des Rebuilds bedient
   bleiben? (FK-13 §13.9.9.)
5. **Scope.** Nur der Concept-Korpus, oder auch die Story-/Research-Quellen
   derselben Collection? Nur `StoryContext`, oder auch die AK3-internen
   Governance-Collections?
6. **Beobachtbarkeit.** Receipt/Telemetrie fuer ausgefuehrte Full-Rebuilds
   (wann, warum ausgeloest, Dauer, Ergebnis), damit die Hygiene nachweisbar ist.

## Nicht-Ziele / Abgrenzung

- **Keine** Aenderung am inkrementellen Normalpfad (der ist mit AG3-176 korrekt).
- **Keine** Behauptung, ein Full sei fuer Daten-Korrektheit noetig.
- Kein Vorgriff auf die obigen Design-Entscheidungen in dieser Datei — sie sind
  bewusst offen und PO-owned.

## Konzept-Referenzen (Ausgangspunkte fuer den Entwurf)

FK-13 §13.9.9 (Bounded-Window / generationskonsistenter Replace) · FK-13 §13.7
(Indexierungszeitpunkte/Trigger) · FK-30 §30.5.4a (Post-Commit-Hook) ·
AG3-174 (Engine, `concept_sync`, `corpus_revision`) · AG3-176 (inkrementeller
Post-Commit-Sync) · AG3-177 (Stale-Chunk-Vertrag).
