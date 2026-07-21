# Wiederaufnahme-Cursor — Gruendungslauf 2026-07-19-conception-support-b4a7d375

Stand: 2026-07-20, nach Codex-Review 7 (Haertungsabnahme + Receipt-Verdicts).
Dieses Dokument ist der EINZIGE aktive Cursor.

## Auftrag (PO, unveraendert)
Konzeptions-Support fuer AK3 via Skills + deploybarer Toolchain: Blueprint,
Concept-Incubator, verlustfreie Promotion, zwei Rollen, Codex als
persistenter adversarialer Reviewer (Resume-Kette), AK3 wendet das
Verfahren auf sich selbst an. PO-Entscheidungen: Q1 voller Toolstack;
Q2 klassenbasierte VCS-Policy; Q3 voller Formal-Kontext; Q4 ein Skill mit
Rollen-Gate. Bootstrap-Sonderstatus des Laufs: dokumentiert in README.md
und Decision Record §5a (einmalig, nicht praezedenzbildend).

## Codex-Review-Kette (resume_job_id = letzter terminaler Job)
R1 job-75972bf3 → R2 job-5de6acf6 → R3 job-9f8b7259 → R4 job-9ca613d8
→ R5 job-c2f5b2c7 → R6 job-8ccab04b → R7 job-67a3b63d (Rework: 4 P0
Toolchain + Receipt-Verdicts 12x equivalent / 8x disagrees).

## Landungsstand
- Konzeptdokumente, Registries, Meta-Vertraege, Decision Record: GELANDET.
- Skill-Bundle concept-incubation-core/4.0.0: GELANDET (23 Contract-Tests).
- Toolchain (14 Module + 11 JSON-Schemas): GELANDET, 285 Tests gruen.
- Gates gruen: check_concept_frontmatter (90 Docs), compile_formal_specs
  (192 Docs, 149 Szenarien), check_concept_reference_integrity (0 Errors),
  check_concept_decision_record, Engine `check.py all`.
- Repo-weit: 9786 Tests passed / 14 skipped, ruff clean, mypy 964 Dateien.

## R7-Einarbeitung
ERLEDIGT (normativ, von mir): release-scope-locks als separater Command
entfernt (Release ist untrennbarer Teil von complete-promotion/abort-run,
Compound-Rule ergaenzt); events.decisions.recorded fuehrt jetzt
po_decision_source_ids statt decision_record_ids; entities um
Lease-Owner-Session, MutationMutex, ArtifactRecord,
DeclassificationReceipt erweitert; projection_status_derivation verlangt
jetzt promotion_disposition=promoted + gebundene Receipts; neue Invariante
projection_target_digest_by_mode und mutation_mutex_compare_before_delete;
run_state_single_writer_cas praezisiert (kein "every mutation");
Szenarien ehrlich umbenannt + Compound-Rule zur fehlenden
Reject-Trace-Ausdrucksfaehigkeit; FK-78: Target-Modi-Tabelle,
source-intake.tsv, Pflichtregister ab FRAMING/PROMOTING, vollstaendige
semantic_gate-CLI-Signaturen; Skill + process-core: CLI-Signaturen,
Intake, Pflichtregister; Decision Record §2 Nr. 4: SSOT-Scope-Entscheidung
mit Owner/Trigger/Closure-Nachweis/Interimsrisiko.
ERLEDIGT (Haertungsrunde 2, 338 Tests gruen): Intake-Manifest +
Derived-Mengengleichheit, gemeinsames receipts.py mit Receipt-Bindung,
vier Target-Modi, Pflichtregister, Registry-Kanten + Lock-Evidenz,
Mutex-Nonce/Heartbeat.

## R8-Stand (Codex-Schlussabnahme job-ed46c634: Rework)
Normativ ALLES geschlossen — 6 der 8 disagrees gedreht; SSOT-Entscheidung
von Codex ausdruecklich akzeptiert; blocked_projection-Endstand als
richtig bestaetigt. Von mir nachgezogen: FK-78 §78.11 nennt keinen
separaten release-scope-locks-Command mehr; "terminiert" →
"triggergebunden".
ERLEDIGT (Haertungsrunde 3, 356 Tests gruen): R8-1 exklusiver Mutex-Takeover
(O_EXCL-Intent + Nonce-Revalidierung vor jedem Schreibschritt,
Zwei-Prozess-Test), R8-2 Intake als verkettetes Append-Log mit extern
gepinntem Head (RUN.register_digests.source_intake_head) + kanonische
Rollen je Derived-Pfad, R8-3 TargetSpec am Receipt (target_mode/selector
Pflicht, kein markdown-section-Default), R8-4 projection_check fuehrt
volle Promotion-Pruefung des referenzierten Laufs aus (Refactor
run_promotion_checks als Bibliothek; check.py all deckt referenzierte
Laeufe ab), R8-5 konkrete Registry-Kanten + Remote/TTL-Bindung.
FK-78 nachgezogen: §78.2 lock_remote, §78.4 source_intake_head +
Mutex-Payload/Intent-Protokoll, §78.7 Intake-Kettenfelder + Head-Pin +
feste Derived-Rollen, §78.10 Receipt-Pflichtfelder target_mode/selector,
§78.11 gehaertete Lock-Evidenz + TTL-Herkunft, kein separater
release-Command mehr, "triggergebunden".

## Endstand (vor Review 9)
Gates: alle vier AK3-Konzept-Gates PASS; Engine projection PASS;
`check.py all` Exit 2 — die neue R8-4-Logik weist den Gruendungslauf
korrekt als Nicht-Promotion-Lauf aus (INCOMPLETE), das ist die ehrliche
Materialisierung von R7-Finding 10, kein Regressionsfehler.
Offen und benannt: (a) Projection-Audit-Lauf (Folge-Story, Owner
Council-Orchestrator) hebt die drei Scopes von blocked_projection auf
active; (b) SSOT-Wrapper-Migration (Decision Record §2 Nr. 4, Owner +
Trigger + Closure-Nachweis); (c) Compiler-Folgearbeit fuer schrittgenaue
Command→Transition-Bindung und Reject-Traces; (d) Harness-Variant-Achse
im Skill-Binder; (e) Hub-Batch-Komfort W2/W3; (f) KPI-/Telemetrie- und
Backend-Sicht.

## Receipts / Projektionsstatus (bewusst offen, ehrlich blockiert)
Codex hat als unabhaengiger Reviewer (principal_id
`openai.codex.review-agent`, session_ref
`ak3-conception-review-chain-r1-r7-2026-07-20`) 20 Zielprojektionen
beurteilt. Stand nach R9: 19x equivalent, 1x disagrees — offen ist nur
noch `concept_toolchain/` (R9-Stand; die dort genannten zwei P0 sind in
Haertungsrunde 4 geschlossen und harren der Re-Beurteilung).
Verdict-Historie: review-7-codex.md (12/8), review-8-codex.md (Drehungen
auf entities/events/invariants/scenarios/Skill-Bundle), review-9-codex.md
(commands → equivalent).
Er stellt zugleich fest: Der Gruendungslauf ist ein Bootstrap-Lauf ohne
schema-konforme Register — Receipt-DATEIEN darin waeren KEIN Closure-Beleg.
Konsequenz (bewusst, nicht verschleiert): Die drei Scopes bleiben
`blocked_projection`. Aufloesung erfordert einen eigenen, schema-konformen
**Projection-Audit-Lauf** mit der fertigen Toolchain (RUN.json,
Source-/Claim-/Atom-Register, Promotion-Manifest, gebundene Receipts) —
Folge-Story, Owner Council-Orchestrator, sichtbar via
projection-manifest.json + README.md#sichtbare-blocker.

## Abschluss (2026-07-20)
Haertungsrunden 1-5 abgeschlossen; alle Codex-Findings aus R1-R10
bearbeitet. R10-1 (Mutex: ein Coordination-Intent statt zweier,
Nonce-Freigabe, Heartbeat-Revalidierung) und R10-2 (vollstaendige
Zeitordnung mit Clock-Skew) sind implementiert und normativ in FK-78
§78.4/§78.11 verankert. Schlussverdict: Review 11 (job-8fce8e42).
Dauerhafte Akte: CLOSURE.md.

Nach dem Rechner-Neustart am 2026-07-20 vollstaendig reverifiziert:
Arbeitsbaum intakt, 387 Tests gruen, alle fuenf Gates PASS.

## Folge-Stories (nicht Teil dieser Lieferung)
1. Schema-konformer Projection-Audit-Lauf → hebt die drei Scopes von
   blocked_projection auf active (Owner: Council-Orchestrator).
2. SSOT-Wrapper-Migration der generischen CI-Gates (Decision Record
   §2 Nr. 4: Owner, Trigger, Closure-Nachweis).
3. Formal-Compiler: schrittgenaue Command→Transition-Bindung und
   Reject-Traces.
4. Harness-Variant-Achse im Skill-Binder (nur bei Format-Divergenz).
5. Hub-Batch-Komfort fuer W2/W3 in Zielprojekten.
6. KPI-/Telemetrie- und Backend-/Control-Plane-Sicht auf Laeufe.
