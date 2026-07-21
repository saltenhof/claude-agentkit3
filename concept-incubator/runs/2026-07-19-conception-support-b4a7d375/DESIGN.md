# Design v4 (konsolidiert): Konzeptions-Support in AgentKit 3

Status: ENTWURF v4 (Inkubator-Artefakt, nicht normativ). Selbsttragend —
ersetzt v1–v3 vollstaendig; keine Rueckverweise auf fruehere Versionen noetig.
Feldgenaue Kataloge: `schemas-draft.md` v2 (Teil dieses Vertrags).
Autor: Fable 5 (Worker-Modus). Reviewer: Codex (persistente Session).
Review-Historie: R1 job-75972bf3 (Rework, F1–F15) → R2 job-5de6acf6
(9 Auflagen R2-1..9) → R3 job-9f8b7259 (1×P0, 6×P1, 1×P2 = R3-1..8) → v4.
PO-Entscheidungen 2026-07-19: Q1 voller Toolstack sofort; Q2 versioniert mit
Opt-out, verfeinert zu klassenbasierter Policy (dem PO berichtet); Q3 voller
Formal-Kontext; Q4 ein Skill mit Rollen-Gate. PO-Direktiven: Inkubator heisst
`concept-incubator/` (Top-Level); Besetzung fragt der Orchestrator beim User.

---

## 1. Auftrag

AK3 unterstuetzt die der Story-Welt vorgelagerte **Konzeptionsphase** —
nicht durch die Backend-Applikation, sondern durch **Skills** und eine
**deploybare deterministische Toolchain**. Normativ definiert werden:
(a) die Blueprint-Struktur einer Konzeptwelt (Domain-Layer,
Fachkonzept-Layer = Fach- UND IT-Konzepte, Formal-Layer, Meta-Governance),
(b) die Konsistenzhaltung der Ebenen, (c) die Weiterentwicklung grosser
Bestaende ueber den **Concept-Incubator** (Multi-Modell-Proposals →
Konvergenzrunden → Synthese → mechanisch geprüfte, verlustfreie Promotion),
(d) zwei Rollen (Council-Orchestrator, Gremiums-Worker; Besetzung via
User-Frage), (e) Auslieferung als harness-optimierte Skills + Toolchain in
den AgentKit-Bundles, (f) Uebernahme des Verfahrens durch AK3 selbst.
Methodik-Quellen: Intima ATOM-01, assertion-authority, projection-manifest,
gelebter Inkubator `var/pi-fachkonzept/`.

## 2. Verankerung in der AK3-Konzeptwelt (bereits begonnen)

| Artefakt | Status |
|---|---|
| DK-16 `16-konzeption-und-konzeptinkubation.md` (Saeule 4.10, DK-00 aktualisiert) | GESCHRIEBEN |
| `concept/_meta/assertion-authority.md` (Statussemantik, "disagreement blocks") | GESCHRIEBEN |
| `meta-contract.md` §2: "formal wins" → Verweis auf Assertion-Vertrag | GESCHRIEBEN |
| Registries: domain-registry (BC concept-incubation: DK-16, FK-78), bounded-contexts, module-registry, tag-corpus | GESCHRIEBEN |
| CLAUDE.md dritter Work-Mode Council-Orchestrator; PROJECT_STRUCTURE `concept-incubator/` + `concept_toolchain/` | GESCHRIEBEN |
| FK-78, formal-spec `concept-incubation/`, Decision Record, 00_index-Sektion | NACH v4-Freigabe |
| Toolchain `bundles/target_project/tools/agentkit/concept_toolchain/` + AK3-CI-Wrapper-Migration (SSOT) | NACH v4-Freigabe |
| Skill-Bundle `concept-incubation-core` | NACH Toolchain |

BC-Scope: `concept-incubation` besitzt die corpus-weite, vor-storyliche
Evolution der normativen Konzeptwelt (Inkubator, Atomverfahren, Promotion).
`exploration-and-design` behaelt storylokales Fine Design. FK-78 traegt
`defers_to`-Kanten zu FK-23/25, FK-43 (Skill-Mechanik), FK-76 (Harness),
FK-30 (Guard-Enforcement), FK-50 (Installation), Meta-Contract/
Assertion-Vertrag.

## 3. Blueprint-Struktur (Soll fuer Zielprojekte)

```text
<projekt>/
  concept/
    domain-design/ | technical-design/ | formal-spec/ (00_meta + <context>/)
    _meta/  (konsistenz-governance, assertion-authority, projection-manifest.json,
             concept-governance.json, decisions/, registries)
  concept-incubator/   # Werkstatt (Kap. 4) — einziger Ort konzeptioneller Grossarbeit
  guardrails/
```

Regeln: drei Wahrheitsschichten mit einem Authority-Graph
(`authority_over`/`defers_to`/`supersedes` azyklisch, scope-disjunkt);
Formal-Klassifikation Pflicht (`formal_refs` XOR `formal_scope: prose-only`);
Formal-Layer-Mindestinhalt nach Meta-Contract; Konsistenzprinzipien P1–P5;
Assertion-/Projection-Vertrag (Kap. 7). ID-Grammatiken sind projekt-
konfigurierbar (`concept-governance.json`); AK3s zweistellige NN-Schemata
sind AK3-lokal, keine Blueprint-Norm. Das korpusweite
`concept/_meta/projection-manifest.json` (Kap. 7) gehoert zum Blueprint.

## 4. Der Concept-Incubator

### 4.1 Grundsatz und Profile

Der normative Layer ist niemals der Arbeitsordner. Drei deklarierte
Prozessprofile: `DIRECT_GOVERNED_CHANGE` (kleiner eindeutiger Scope; kein
Council; Decision-Record- und Gate-Pflicht), `LIGHT_INCUBATION` (echte
Unsicherheit, begrenzter Scope; 1–2 Worker, Claim-Verfahren light),
`FULL_ATOM` (ATOM-Trigger: Migration/Synthese in die Normwelt,
Verlustfreiheits-/Vollstaendigkeitsanspruch, mehrere Autoritaeten oder
Prosa+Formal gemeinsam, Dokumentfamilien-Ersatz, Ownership-/Lifecycle-
Schnittverschiebung, PO-Auftrag). Bagatellen (`Concept-Format-Only`-
Kriterium) sind inkubator- und record-frei, bleiben aber durch alle
anwendbaren deterministischen Konzept-Gates geprueft.

### 4.2 Lauf-Layout

```text
concept-incubator/
  INDEX.md
  locks/                            # nur Backend "filesystem"; nie versioniert
  runs/<run_id>/
    RUN.json                        # einziger autoritativer Zustand
    LEASE.json
    briefing.md
    baseline/
      corpus-baseline.tsv           # eingefrorene Normwelt-Inventur
      source-register.tsv           # Quellen + Genealogie
      source-units.tsv              # deterministische Einheiten je Quelle [R3-1]
      source-coverage.tsv           # finaler Reviewstatus je Quelle [R3-1]
      normative-coverage.tsv        # finaler Reviewstatus je Normdatei [R3-1]
      coverage-plan.json            # FULL_ATOM: Worker-Pakete
    artifact-register.tsv           # Provenienz + Datenklassen aller Artefakte [R3-6]
    workers/<participant_id>/{inbox/,outbox/}
    rounds/r<N>/{<participant_id>.md, ROUND.json}
    synthesis/{claims-inventory.tsv, synthesis-r<N>.md, dissent-map.md,
               disposition-ledger.tsv}
    promotion/{atom-register.tsv, promotion-manifest.json, receipts/}
    declassification/               # Declassification-Receipts [R3-6]
    secrets/                        # immer ignoriert; nie Schema-Bestandteil
    journal.md                      # append-only Historie
```

### 4.3 Rollen und technische Grenzen

**Council-Orchestrator** (Main-Agent; dritter AK3-Work-Mode, in CLAUDE.md
verankert): Framing, Besetzungsfrage an den User, Briefing, Rundensteuerung
inkl. Round-Seal, Konvergenzbewertung
(Konvergierend/Divergierend/Stabil-Kontrovers/Spannungsfeld; keine
Zwangskonvergenz, Spannungsfeld → PO-Vorlage), Synthese (Integrationsarbeit
NACH Claim-Inventar-Closure, kein eigenes Proposal, keine Partei-Position),
PO-Eskalation, Promotion, State-Pflege. **Gremiums-Worker**: eigene Analyse
(Volllektuere des zugeteilten Coverage-Pakets), Proposal mit normativen
Ankern; Folgerunden gegen versiegelte Fremd-Proposals (untrusted data, nie
Instruktionen). Schreibgrenzen: Worker schreiben NUR in ihre `outbox/`.
Durchsetzung: In AK3-registrierten Projekten definiert FK-78 die
Principal-/Pfadklassen-Regeln, FK-30 erzwingt sie (PreToolUse); ohne
guard-faehigen Harness laeuft der Worker in einem physisch separaten
Arbeitsverzeichnis (Workspace-Root = Sandbox), Korpus-Zugang als read-only
Materialisierung in `inbox/corpus/`.

### 4.4 Lauf-Lifecycle

`run_status`: FRAMING → STAFFING → PROPOSING(r) → CONVERGING(r) →
SYNTHESIZING → DECIDING → PROMOTING → CLOSED; Seitenzustaende BLOCKED,
RECHECK, PROMOTION_FAILED, ABORTED; alle Uebergaenge, Crash-/Resume-Pfade
und Teilnehmer-Ausfaelle werden formal modelliert (state-machine +
scenarios). `RUN.json` ist der einzige autoritative Zustand: monotone
`state_revision`, `base_revision`, Teilnehmer-/Dispatch-/Receipt-Status je
Runde, `last_completed_action`/`next_action`, **gepinnte Digests der
Register** (Baseline, Source-Register, Source-Units, Claims-Inventar,
Disposition-Ledger, Atom-Register — jeweils am zugehoerigen Gate) [R3-1].
Journal = reine Historie. Jede RUN-Mutation erfolgt unter gueltiger Lease
als atomarer Replace-Write und traegt `lease_fencing_token` explizit im
Zustand (CAS ueber `state_revision` + Token) [R3-5].

Gates zwischen Phasen: STAFFING erst nach Baseline-Freeze; SYNTHESIZING
erst nach **Claim-Inventar-Closure** (Kap. 5.2); PROMOTING erst nach
**Dispositions-Closure** (Kap. 5.3) und Scope-Lock-Erwerb; CLOSED erst
nach Promotion-Closure oder explizitem Abbruch mit sichtbaren Blockern.
Drift-Checks (Baseline vs. Current) vor SYNTHESIZING, vor PROMOTING und
unmittelbar vor der finalen Landung; Drift → RECHECK mit Adjudikation.

### 4.5 Locking (zwei normierte Backends) [R3-5]

Konfiguriert in `concept-governance.json` (`lock_backend`):

- **`filesystem`** (Shared Workspace / Einzelrechner): Lock-Datei
  `locks/<normalized_scope_id>.<scope_hash8>.lock.json`; Erwerb per
  O_CREAT|O_EXCL; Renew per atomarem Replace durch den Owner; Takeover nur
  bei TTL-Ablauf ueber Intent-Datei (O_EXCL `<name>.takeover`), Re-Check,
  Replace mit `fencing_token + 1`, Intent-Loeschung. `locks/` ist
  gitignored (nie versioniert).
- **`git-remote`** (verteiltes Team ohne gemeinsames FS): Lock = Remote-Ref
  `refs/concept-locks/<scope_hash>` per Create-only-Push (CAS gegen
  Zero-OID); Release = Ref-Delete; Takeover nur nach TTL aus dem
  Ref-Inhalt, per Force-Push mit erwarteter Old-OID (CAS).

Beide: Lock-Besitz (`locked_by_run` + Token) wird beim PROMOTING-Eintritt
erworben, im Promotion-Manifest festgehalten und **unmittelbar vor der
finalen Landung erneut verifiziert**; Merge nur, wenn Ziel noch auf der
erwarteten `base_revision` steht.

### 4.6 Skalierung

FULL_ATOM verlangt vor STAFFING einen Coverage-Plan: Partitionierung der
Baseline in Worker-Pakete (Authority-Scope-/BC-orientiert, deklarierte
Redundanz) + Cross-Scope-Integrationspaket; Coverage-Matrix mechanisch:
jede Baseline-Datei genau zugeteilt oder begruendet EXEMPT.

### 4.7 Datenklassen, Vererbung, VCS [R3-6]

Datenklassen-Vokabular einheitlich: `open | internal | sensitive`.
Unklassifiziert ⇒ effektiv `sensitive` (fail-closed; auch der
Konfigurations-Default ist `sensitive`). Jedes Lauf-Artefakt steht im
`artifact-register.tsv` mit Provenienz-Kanten (`input_refs`), deklarierter
und **effektiver** Klasse (Maximum der Eingaenge). Herabstufung nur via
**Declassification-Receipt** (Quelle/Output-Digests, angewandte
Sanitization-Regeln, Zielklasse, freigebender Principal). VCS-Disposition
folgt der effektiven Klasse: `sensitive` ⇒ lokal/ignored; Commit-Gate der
Toolchain blockiert Verstoesse. Data-Release je Teilnehmer referenziert
konkrete `source_id`/`package_id`-Mengen plus maximale Datenklasse, vom
User bestaetigt. Secret-Vertrag: JSON-Artefakte tragen nur deklarierte
Felder (fail-closed) und ausschliesslich opake, nicht-geheime Handles;
Geheimnisse nur unter `secrets/` (immer ignoriert).

## 5. Verlustfreie Promotion (Quell-Units → Claims → Atome → Ziele)

### 5.1 Source-Set und Units [R3-1]

Nach der letzten Runde werden ALLE Prozessquellen registriert (Briefing,
jede Proposal-Fassung jeder Runde, Synthesen, Dissent-Map,
PO-Entscheidungen; `source-register.tsv` mit Genealogie-Eltern). Fuer jede
Quelle erzeugt die Toolchain (`semantic_gate.py units`, deterministisch)
**Source-Units**: eine Einheit je Ueberschriftsabschnitt beliebiger Ebene
(Fallback fuer strukturarme Texte: Absatzbloecke), mit Locator und
Unit-Digest. Der Checker re-deriviert die Units und prueft Digest-Gleichheit
— das Unit-Register kann nicht von Hand ausgeduennt werden.

### 5.2 Claim-Inventar (Phase A, Gate fuer SYNTHESIZING)

`claims-inventory.tsv`: qualifikatorentreue Claims mit `claim_id`,
`source_id`, `unit_refs`, Locator, Statement, Qualifiern, Genealogie.
**Inventar-Closure**: JEDE Source-Unit traegt `claim_refs` ODER einen
begruendeten Empty-Datensatz im Unit-Register (`NO_MATERIAL_CONTENT`,
`DUPLICATE_OF:<unit>`, `OUT_OF_SCOPE:<grund>`) — es gibt keine
Pseudo-Claims und keine pauschalen Quell-EMPTYs; Mengenassertionen:
`source_register == source_coverage`-Domaene, `units == claims-or-empty`.
Inventar-Digest wird in RUN.json gepinnt.

### 5.3 Disposition und Synthese (Phase B, Gate fuer PROMOTING)

`disposition-ledger.tsv`: je Claim genau eine `synthesis_disposition`
(`ADOPTED|MERGED|SUPERSEDED_BY_CLAIM|REJECTED_WITH_REASON|OPEN_QUESTION`)
mit Begruendung, `residual_edge` fuer Nicht-Adoptiertes
(`CHECKED_AGAINST_CURRENT|ESCALATED_TO_PO`; `NONE_REQUIRED:<klasse>` nur
fuer deklarierte Begruendungsklassen) und `atom_refs` fuer Adoptiertes.
Minderheitspositionen der letzten Runde brauchen immer eine echte
Restkante. **Coverage-Abschluss** [R3-1]: `source-coverage.tsv` (genau eine
finale Zeile je Quelle: Hash, Reviewstatus, Review-Artefakt,
Reviewer-Principal) und `normative-coverage.tsv` (genau eine Zeile je
betroffener Normdatei) muessen final sein; null offene/RECHECK-Zustaende.

### 5.4 Atomisierung und Zielmapping

Atome (qualifikatorentreu; Typen REQUIREMENT/DOMAIN_FACT/DECISION/
RATIONALE/EVIDENCE/PARAMETER_CANDIDATE/REJECTION/OPEN_QUESTION) mit
`expected_authority` (Scope-Owner-Reihenfolge: Decision → DK → FK → Formal
→ Registry → Guardrail); `COVERED_SPLIT` listet alle Teilziele, kein
Qualifikator faellt zwischen die Ziele. Dispositionen je Atom:
`COVERED_EXACT|COVERED_SPLIT|REJECTED|OPEN_MISSING|DEFERRED_BACKLOG|
EVIDENCE_ONLY|NOT_APPLICABLE|SUPERSEDED` (Tombstones nur fuer Atome).
`DEFERRED_BACKLOG` braucht Owner, Trigger und gepruefte
Reverse-Sichtbarkeit.

### 5.5 Receipts (unabhaengig) und Reverse Trace [R3-4]

Projection-Receipts je COVERED_*-Atom: Quelle-/Ziel-/Abschnitts-Digests
(kanonisierter Sektionstext), `writer_principal_id` + Session,
`reviewer_principal_id` + Session, Verdict, UTC-Zeit.
**`reviewer_principal_id == writer_principal_id` ist ERROR**; `disagrees`
eskaliert an den PO und darf vom Writer nicht ueberschrieben werden.
**Reverse Trace**: Der Checker berechnet alle Diff-Hunks der Konzept-Wurzeln
(Baseline ↔ Current), ordnet jeden nicht-formatalen Hunk dem kleinsten
umschliessenden Ueberschriftsanker **beliebiger Ebene** zu und verlangt
Deckung durch mindestens ein Receipt/Atom-`target_ref` auf diesem Anker
oder einem Vorfahren-Anker. Ungedeckte Hunks → ERROR.

### 5.6 Promotion-Manifest und Closure

`promotion-manifest.json`: `scopes[]` mit **`promotion_disposition`**
(`promoted|rejected|deferred`) + Blockern (sichtbarer Anker, Owner),
`required_*`-Mengen, `targets[]` (before/after-Digests), Receipt-Liste,
Scope-Locks (+ Token), `semantic_gates[]`-Stand. Closure-Regeln: Mengen-/
ID-/Digest-Assertionen, Receipt-Vollstaendigkeit, Reverse-Trace,
`required_*`-Aufloesung, Lock-Besitz, deterministische Gates gruen,
Coverage final. Erst dann `promoted`.

## 6. Statusmodell (kanonisch, drei Owner) [R3-3]

| Achse | Werte | Owner |
|---|---|---|
| Decision-Lifecycle | proposed/accepted/rejected/superseded | Decision Record |
| `promotion_disposition` (je Scope im Lauf) | promoted/rejected/deferred | promotion-manifest.json des Laufs |
| `assertion_status` (je Scope, korpusweit) | draft/active/blocked_projection/deprecated/superseded | `concept/_meta/projection-manifest.json` |
| `equivalence_status` (je Pflichtprojektion) | unreviewed/equivalent/disagrees/stale/blocked_missing_target | abgeleitet, gefuehrt im projection-manifest |

**`concept/_meta/projection-manifest.json`** (korpusweit, versioniert,
Blueprint-Bestandteil): je Scope die Assertion-Quelle (Pfad+Digest), die
vollstaendige Pflichtprojektionsmenge (Art, Ziel, Ziel-Digest,
Receipt-Ref), den abgeleiteten `equivalence_status` je Projektion und den
`assertion_status`, plus `last_run_id`. Deterministische Ableitung:
fehlendes Receipt → `unreviewed`; Digest-Abweichung → `stale`; fehlendes
Ziel → `blocked_missing_target`; alle Projektionen `equivalent` und keine
Blocker → `active`, sonst `blocked_projection`. Die Ableitung ist
ausschliesslich hier normiert; Semantik-Prosa dazu im Assertion-Vertrag
(`concept/_meta/assertion-authority.md`, bereits geschrieben — wird um den
Manifest-Verweis ergaenzt).

## 7. Deploybare Toolchain

### 7.1 SSOT und Umfang

`bundles/target_project/tools/agentkit/concept_toolchain/` ist die einzige
Implementierung der generischen Konzept-Gates; AK3s `scripts/ci/`-Skripte
werden im Zuge dieses Vorhabens duenne Wrapper (generische Anteile →
Engine; AK3-Spezifika wie Architecture-Conformance, L17–L20, Tag-Korpus,
Hub-Batch bleiben lokal). stdlib-only als bewusster Standalone-Vertrag.
**SMY** (Structured Metadata YAML Subset): eigener Parser fuer das im
Korpus verwendete YAML-Subset (Block-Mappings/-Sequenzen, Plain-/Quoted-/
Folded-Skalare, Kommentare, einfache Flow-Listen; keine Anchors/Tags/
Multi-Doc); ausserhalb des Subsets → ERROR mit Zeile. Feldkataloge sind als
Validator-Code implementiert; mitgelieferte JSON-Schema-Dateien sind
dokumentierend und werden per Contract-Test ueber kanonische Fixtures mit
dem Code deckungsgleich gehalten.

### 7.2 CLI-Trennung [R3-7]

- **`check.py` — strikt read-only**: `frontmatter | references | formal |
  decision-gate --base <rev> | incubator <run> | promotion <run> |
  projection | semantic-status | all`.
- **`semantic_gate.py` — mutierend, lease-gebunden, atomare Writes,
  Idempotency-Key (Request-Digest)**: `units <run>` (Source-Units
  derivieren), `prepare <run>` (deterministische W2/W3-Request-Packs je
  Scope: Chunk-Sets + versioniertes Prompt-Template), `import <run>
  <receipt>` (validiert + registriert Semantik-Receipts).
- Exit-Codes einheitlich: 0 PASS; 1 Befunde (ERROR); 2 fehlende
  Voraussetzungen / deklarierter INCOMPLETE-Lauf; 3 Usage-/Config-Fehler.
  Exit 2 nie fuer einen vollstaendig gelaufenen Einzel-Check.
- `--json`: stabiles Envelope `{schema_version, command, check_set[],
  complete, findings[]{check_id, severity, path, locator, message}}`.
- Felddisziplin fuer alle Artefakte: UTC-ISO-8601-`Z`-Zeiten,
  SHA-256-lowercase-hex, LF-kanonisierte Sektions-Digests, TSV ohne
  TAB/CR/LF in Feldern (`\n`-Escape), Register nach ID sortiert,
  Requiredness/Nullability je Feld normiert (schemas-draft v2).

### 7.3 Semantische Gates

W2 (Authority-Prose) / W3 (Scope-Consistency) sind LLM-Bewertungen mit
deterministischer Verrechnung: `prepare` erzeugt Request-Packs, der
Agent/Hub fuehrt aus, `import` registriert versionierte Receipts,
`check.py semantic-status` verrechnet Vollstaendigkeit je Scope. Fehlender
LLM-Zugang oder unvollstaendiger Sweep ⇒ betroffene Scopes
`blocked_projection`; niemals stilles PASS; nie als "deterministisch"
etikettiert.

## 8. Skills

Ein Bundle `concept-incubation-core/4.0.0/` (FK-43-konform, keine
Binder-Aenderung): kanonische Root-`SKILL.md` mit Rollen-Gate
(Orchestrator/Worker) und Harness-Selbsterkennung; `references/`
(process-core, claude-code, codex, participant-briefing) single-source;
`templates/` (RUN.json, LEASE.json, ROUND.json, TSV-Header,
promotion-manifest.json, projection-manifest.json, briefing.md, INDEX.md,
concept-governance.json, .gitignore-Fragmente). Inhalte: Blueprint-Wissen,
Profilwahl, Prozessfuehrung (Besetzungsfrage, Spawn-/Resume-Mechanik je
Harness, Round-Seal, Konvergenz), Lease-/State-/Lock-Disziplin,
Datenklassen, Promotion Schritt fuer Schritt mit Checker-Gates,
Initialerstellung; Umgang mit BLOCKED/RECHECK/PROMOTION_FAILED.

## 9. Scope-Grenzen (ZERO DEBT, explizit)

Kein Backend-/Control-Plane-/Telemetrie-Ausbau in v1. In scope: Toolchain
inkl. SSOT-Wrapper-Migration, Skills, Konzeptdokumente inkl. Formal-Kontext,
AK3-eigenes projection-manifest.json (initial fuer die neuen Scopes).
Folge-Stories (deklariert): Harness-Variant-Achse im Binder (nur bei harter
Format-Divergenz), Hub-Batch-Komfort fuer W2/W3 in Zielprojekten,
KPI-/Telemetrie-Anbindung des Inkubators.

## 10. Aufloesungs-Matrix Review 3

| R3-Finding | Aufloesung v4 |
|---|---|
| R3-1 (P0) Verlustfreiheit | §5.1–5.3: tool-derivierte Source-Units mit Digest-Recheck, Claims je Unit oder begruendeter Empty-Datensatz, source-/normative-coverage.tsv final, Mengenassertionen, Register-Digests in RUN gepinnt |
| R3-2 v3 nicht selbsttragend | v4 vollstaendig konsolidiert (dieses Dokument + schemas-draft v2) |
| R3-3 Statusmodell/Authority | §6: promotion_disposition im Lauf-Manifest; korpusweites concept/_meta/projection-manifest.json mit deterministischer Ableitung; kein projection_status mehr |
| R3-4 Reverse Trace/Receipts | §5.5: Hunk-zu-kleinstem-Anker-Zuordnung beliebiger Ebene; Receipt mit writer/reviewer-Principals, Gleichheit = ERROR |
| R3-5 Lock/Lease | §4.5: zwei normierte Backends (filesystem-CAS mit Intent-Takeover; git-remote-Ref-CAS), Lockname mit Hash, Token in RUN + Manifest, CAS je Mutation, Re-Check vor Landung |
| R3-6 Klassifikation | §4.7: artifact-register mit Provenienz + effektiver Klasse, Declassification-Receipts, unklassifiziert=sensitive (auch Default), einheitliches Vokabular, Data-Release je source/package |
| R3-7 CLI/Feldkataloge | §7.2: check.py read-only vs. semantic_gate.py mutierend (Lease/atomar/idempotent), Exit-Code-Vertrag, JSON-Envelope, Felddisziplin; concept-governance.json vollstaendig (schemas-draft v2) |
| R3-8 IDs/Tombstones | schemas-draft v2 §0: unbegrenzte Zaehler mit Mindestbreite 4, Prefix==Run-Suffix-Invariante, Tombstones nur fuer Atome |
