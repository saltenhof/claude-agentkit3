# Schemas v2: Inkubator- und Promotions-Artefakte (Vertragsbasis fuer FK-78 + Toolchain)

Status: ENTWURF v2 (Inkubator-Artefakt). Ersetzt v1 vollstaendig.

## 0. Allgemeine Felddisziplin

- Jedes JSON-Artefakt: `schema_version` (SemVer), **unbekannte Felder =
  ERROR** (fail-closed), nur deklarierte Felder.
- Zeiten: UTC ISO-8601 mit `Z` (`2026-07-19T18:00:00Z`).
- Digests: SHA-256, lowercase hex. Datei-Digest = Rohbytes;
  Sektions-/Unit-Digest = LF-normalisierter Text des Abschnitts.
- TSV: Tab-getrennt, Header-Zeile Pflicht, Felder duerfen TAB/CR/LF nicht
  enthalten (Zeilenumbrueche als literal `\n`); Zeilen nach ID
  aufsteigend sortiert; leeres Feld = deklarierte Nullability, sonst ERROR.
- Pfade: projektrelativ mit `/`, muessen unter den in
  `concept-governance.json` deklarierten Wurzeln liegen (Containment).
- Requiredness: alle Felder Pflicht, ausser explizit "(optional)" bzw.
  "(leer erlaubt)".

### ID-Grammatiken

| ID | Grammatik | Anmerkung |
|---|---|---|
| `run_id` | `^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$` | Suffix = `run_uuid8` |
| `participant_id` | `^[a-z0-9]+(-[a-z0-9]+)*$` | eindeutig je Lauf |
| `unit_id` | `^SU-[0-9a-f]{8}-\d{4,}$` | Zaehler unbegrenzt, Mindestbreite 4 |
| `claim_id` | `^CLM-[0-9a-f]{8}-\d{4,}$` | dito |
| `atom_id` | `^ATM-[0-9a-f]{8}-\d{4,}$` | dito; Tombstones NUR fuer Atome (Disposition `SUPERSEDED`) |
| `receipt_id` | `^RCP-[0-9a-f]{8}-\d{4,}$` | dito |
| `package_id` | `^PKG-[0-9a-f]{8}-\d{2,}$` | dito |
| `principal_id` | `^[a-z0-9]+([._-][a-z0-9]+)*$` | stabil je Akteur (z. B. `codex.gpt-x.session-a` verboten — KEINE Session im Principal; Session separat) |
| `scope_id` | projektkonfiguriert; Default `^[a-z0-9]+([.-][a-z0-9]+)*$` | Normalisierung: lowercase, Kollaps `[._-]+` → `-` fuer Lock-Namen |

Invariante: der `uuid8`-Anteil aller SU/CLM/ATM/RCP/PKG-IDs eines Laufs ==
`run_uuid8` des Laufs. IDs werden nie umnummeriert oder wiederverwendet.

## 1. `RUN.json`

```json
{
  "schema_version": "1.0.0",
  "run_id": "2026-07-19-conception-support-3f9a1c2e",
  "title": "<kurz>",
  "profile": "LIGHT_INCUBATION | FULL_ATOM",
  "state": "FRAMING|STAFFING|PROPOSING|CONVERGING|SYNTHESIZING|DECIDING|PROMOTING|CLOSED|BLOCKED|RECHECK|PROMOTION_FAILED|ABORTED",
  "state_revision": 17,
  "lease_fencing_token": 4,
  "current_round": 2,
  "base_revision": { "kind": "git|digest", "value": "<sha>" },
  "data_class": "open|internal|sensitive",
  "actor": { "role": "council-orchestrator", "harness": "claude-code|codex", "model": "<id>", "principal_id": "<id>", "session_ref": "<opaque>" },
  "participants": [
    { "participant_id": "codex-1", "model": "<id>", "backend": "<id>",
      "spawn_mode": "harness-bridge|llm-hub|subagent|cli-resume",
      "principal_id": "<id>", "session_ref": "<opaque|null>",
      "data_release": { "max_data_class": "open|internal|sensitive",
        "source_ids": ["..."], "package_ids": ["..."],
        "approved_by_user": true },
      "status": "active|failed|replaced|withdrawn" }
  ],
  "register_digests": {
    "corpus_baseline": "<sha256|null>",
    "source_register": "<sha256|null>",
    "source_units": "<sha256|null>",
    "claims_inventory": "<sha256|null>",
    "disposition_ledger": "<sha256|null>",
    "atom_register": "<sha256|null>"
  },
  "blocked": { "reason": "<text>", "since_state": "<state>" },
  "recheck": { "drifted_paths": ["..."], "detected_in_state": "<state>" },
  "last_completed_action": "<action-id>",
  "next_action": "<action-id>",
  "updated_at": "<iso-utc>"
}
```

Regeln: `state_revision` strikt monoton; Mutation nur unter gueltiger Lease,
`lease_fencing_token` wird bei jeder Mutation mitgeschrieben (CAS:
Schreiber prueft `state_revision` und Token vor Replace); atomarer
Replace-Write (temp + rename). `register_digests.*` sind `null` bis zum
jeweiligen Gate und danach Pflicht + unveraenderlich (Aenderung nur ueber
RECHECK-Adjudikation mit neuem Gate-Durchlauf). `blocked`/`recheck` non-null
nur im jeweiligen Zustand.

## 2. `LEASE.json`

```json
{ "schema_version": "1.0.0", "run_id": "...",
  "owner": { "principal_id": "<id>", "harness": "...", "session_ref": "<opaque>" },
  "fencing_token": 4, "acquired_at": "<iso-utc>", "ttl_seconds": 3600,
  "released": false }
```

Erwerb O_CREAT|O_EXCL (bzw. Vorgaenger `released:true`/TTL-Ablauf via
Intent-Verfahren wie Locks, §3); Renew = atomarer Replace durch Owner;
Takeover inkrementiert `fencing_token`.

## 3. Scope-Locks (`lock_backend` aus concept-governance.json)

**filesystem**: `concept-incubator/locks/<normalized_scope_id>.<scope_hash8>.lock.json`
(`scope_hash8` = sha256(scope_id)[:8]; Verzeichnis gitignored):

```json
{ "schema_version": "1.0.0", "scope_id": "<original>", "locked_by_run": "<run_id>",
  "fencing_token": 2, "acquired_at": "<iso-utc>", "ttl_seconds": 86400 }
```

Erwerb: O_CREAT|O_EXCL. Renew: atomarer Replace durch Owner-Lauf. Takeover
nur bei TTL-Ablauf: (1) Intent-Datei `<lockname>.takeover` per O_EXCL,
(2) Lock re-lesen und Ablauf verifizieren, (3) Replace mit
`fencing_token+1`, (4) Intent loeschen. Verwaiste Intents verfallen nach
`ttl_seconds` des Locks.

**git-remote**: Lock = Ref `refs/concept-locks/<scope_hash>` (Blob mit
identischem JSON); Erwerb per Create-only-Push (CAS Old-OID=Zero); Renew/
Takeover per Push mit erwarteter Old-OID; Release = Ref-Delete. Keine
Lock-Dateien im Worktree.

Beide Backends: Besitzpruefung beim PROMOTING-Eintritt, Festschreibung in
`promotion-manifest.scope_locks[]` (inkl. Token) und Re-Verifikation
unmittelbar vor der finalen Landung.

## 4. `rounds/r<N>/ROUND.json`

Wie v1: Dispatch (sent_at, prompt_digest, input_digests[]), Receipt
(received_at, proposal_digest), `outcome`
(`received|timeout|failed|excluded` + Pflicht-`outcome_reason`), `sealed`,
`seal.sealed_proposal_digests`. Cross-Read erst nach Seal; Digests muessen
den Dateien in `rounds/r<N>/` entsprechen.

## 5. Baseline-Register (`baseline/`)

- `corpus-baseline.tsv`: `path` `bytes` `sha256` `layer`
  (`domain|technical|formal|meta|guardrail|other`) `package_id`
  (oder `EXEMPT:<begruendung>`; FULL_ATOM: genau eines von beiden).
- `source-register.tsv`: `source_id` `role`
  (`BRIEFING|PROPOSAL|SYNTHESIS|DISSENT_MAP|PO_DECISION|NORMATIVE_BASELINE|EVIDENCE`)
  `path` `sha256` `round` (leer erlaubt) `participant_id` (leer erlaubt)
  `genealogy_parents` (Semikolon-Liste; leer nur fuer Primaerquellen).
- `source-units.tsv` [R3-1]: `unit_id` `source_id` `unit_locator`
  (`<path>#<heading-path>` oder `<path>#L<a>-L<b>`) `unit_digest`
  `claim_refs` (Semikolon-Liste; leer erlaubt NUR wenn `empty_reason`
  gesetzt) `empty_reason`
  (`NO_MATERIAL_CONTENT|DUPLICATE_OF:<unit_id>|OUT_OF_SCOPE:<grund>`;
  leer wenn `claim_refs` gesetzt). Units werden deterministisch von
  `semantic_gate.py units` erzeugt (eine Unit je Ueberschriftsabschnitt
  beliebiger Ebene; Fallback: Absatzbloecke); der Checker re-deriviert und
  vergleicht Digests (Ausduennung unmoeglich).
- `source-coverage.tsv` [R3-1]: `source_id` `sha256` `review_status`
  (`PASS|PASS_WITH_GAPS|FAIL|N_A`) `review_artifact` (Pfad)
  `reviewer_principal_id`. Genau eine Zeile je Quelle; final vor
  PROMOTING-Austritt; Reviewer ≠ Autor der Quelle, soweit die Quelle einen
  Principal hat.
- `normative-coverage.tsv` [R3-1]: `path` `baseline_sha256` `review_status`
  `review_artifact` `reviewer_principal_id`. FULL_ATOM: eine Zeile je
  Baseline-Normdatei; LIGHT: je beruehrter Normdatei.
- `coverage-plan.json` (FULL_ATOM): wie v1 (Pakete, Redundanz,
  Integrationspaket; Vereinigung + EXEMPT == Baseline).

## 6. `artifact-register.tsv` [R3-6]

`path` `sha256` `artifact_kind`
(`briefing|proposal|synthesis|dissent_map|inventory|ledger|atom_register|manifest|receipt|round_state|journal|other`)
`input_refs` (Semikolon: source_ids/paths; leer erlaubt fuer Wurzeln)
`declared_class` (`open|internal|sensitive`) `effective_class`
(= max(declared, max(inputs)); Herabstufung nur mit
`declassification_receipt`) `vcs_disposition` (`versioned|local`)
`declassification_receipt` (Pfad; leer erlaubt).

Regeln: unklassifizierte Eingaenge zaehlen als `sensitive`;
`effective_class=sensitive` ⇒ `vcs_disposition=local`, es sei denn ein
Declassification-Receipt liegt vor; Commit-Gate (`check.py incubator`)
blockiert Verstoesse.

`declassification/<receipt_id>.json`:

```json
{ "schema_version": "1.0.0", "receipt_id": "RCP-...", "source_path": "...",
  "source_digest": "...", "output_path": "...", "output_digest": "...",
  "rules_applied": ["<sanitization-regel>", "..."],
  "target_class": "open|internal",
  "approved_by_principal": "<principal_id>", "approved_at": "<iso-utc>" }
```

## 7. Claim-Verfahren (`synthesis/`)

- `claims-inventory.tsv` (Phase A, vor Synthese eingefroren): `claim_id`
  `source_id` `unit_refs` (Semikolon, >=1) `source_locator` `statement`
  `qualifiers` (leer erlaubt) `genealogy_parents` (leer erlaubt).
  Closure: jede Source-Unit hat `claim_refs` ODER `empty_reason`
  (§5 source-units); Digest in RUN gepinnt.
- `disposition-ledger.tsv` (Phase B): `claim_id` `synthesis_disposition`
  (`ADOPTED|MERGED|SUPERSEDED_BY_CLAIM|REJECTED_WITH_REASON|OPEN_QUESTION`)
  `disposition_reason` (Pflicht ausser ADOPTED) `residual_edge`
  (`CHECKED_AGAINST_CURRENT|ESCALATED_TO_PO|NONE_REQUIRED:<klasse>`;
  Pflicht fuer nicht-ADOPTED/MERGED; Minderheitspositionen letzte Runde nie
  `NONE_REQUIRED`) `atom_refs` (Pflicht bei ADOPTED/MERGED) `finding_refs`
  (leer erlaubt). Closure: genau eine Zeile je Inventar-Claim.

## 8. `promotion/atom-register.tsv`

`atom_id` `statement` `atom_type`
(`REQUIREMENT|DOMAIN_FACT|DECISION|RATIONALE|EVIDENCE|PARAMETER_CANDIDATE|REJECTION|OPEN_QUESTION`)
`qualifiers` (leer erlaubt) `normative_status`
(`proposal|accepted|evidence|rejected|open`) `expected_authority`
(scope_id) `target_refs` (Semikolon `<path>#<anchor>`; >=2 bei
COVERED_SPLIT) `disposition`
(`COVERED_EXACT|COVERED_SPLIT|REJECTED|OPEN_MISSING|DEFERRED_BACKLOG|EVIDENCE_ONLY|NOT_APPLICABLE|SUPERSEDED`)
`deferral` (`owner=<x>;trigger=<y>;anchor=<path#anchor>`; Pflicht bei
DEFERRED_BACKLOG, sonst leer) `claim_refs` (>=1) `receipt_refs`
(Pflicht bei COVERED_*).

## 9. `promotion/promotion-manifest.json`

```json
{
  "schema_version": "1.0.0",
  "run_id": "...",
  "base_revision": { "kind": "git", "value": "..." },
  "scopes": [
    { "scope_id": "...",
      "promotion_disposition": "promoted|rejected|deferred",
      "blockers": [ { "reason": "...", "atom_ids": ["ATM-..."],
                      "owner": "<wer>", "visible_anchor": "<path#anchor>" } ] }
  ],
  "required_decision_ids": ["..."], "required_concept_ids": ["..."],
  "required_formal_ids": ["..."], "required_registry_edges": ["..."],
  "required_support_paths": ["..."], "required_test_oracles": ["..."],
  "targets": [ { "path": "...", "before_sha256": "<sha|null>", "after_sha256": "<sha>" } ],
  "receipts_dir": "promotion/receipts",
  "scope_locks": [ { "scope_id": "...", "locked_by_run": "<run_id>", "fencing_token": 2, "backend": "filesystem|git-remote" } ],
  "semantic_gates": [ { "gate": "authority-prose|scope-consistency",
      "status": "passed|blocked|not_run", "receipt_path": "<path|null>",
      "blocking_scope_ids": ["..."] } ]
}
```

`promotion/receipts/<receipt_id>.json` [R3-4]:

```json
{ "schema_version": "1.0.0", "receipt_id": "RCP-...", "atom_id": "ATM-...",
  "target": { "path": "...", "anchor": "<smallest-enclosing-heading>" },
  "source_digest": "<sha256 atom statement>",
  "target_section_digest": "<sha256 kanonisierter Sektionstext>",
  "writer_principal_id": "<id>", "writer_session_ref": "<opaque>",
  "reviewer_principal_id": "<id>", "reviewer_session_ref": "<opaque>",
  "verdict": "equivalent|disagrees", "reviewed_at": "<iso-utc>" }
```

Invarianten: `reviewer_principal_id != writer_principal_id` (ERROR);
`disagrees` ⇒ Scope-Blocker + PO-Eskalation, kein Writer-Override.

Closure-Regeln (`check.py promotion`):
1. Jedes `accepted`-Atom: genau eine Disposition; COVERED_* ⇒ Receipts mit
   `equivalent` und Digest-Match (Atom-Statement + Ist-Sektion).
2. `targets[]`-Digests stimmen (before == Baseline, after == Ist; null nur
   fuer neue Dateien).
3. **Diff-Hunk-Reverse-Trace**: jeder nicht-formatale Hunk (Baseline↔
   Current unter den Konzept-Wurzeln) ist dem kleinsten umschliessenden
   Ueberschriftsanker beliebiger Ebene zugeordnet und von >=1 Receipt-/
   Atom-Anker (selbst oder Vorfahre) gedeckt; sonst ERROR.
4. `required_*` existieren und loesen auf.
5. `promotion_disposition=promoted` nur wenn: keine Blocker, keine
   OPEN_MISSING/DEFERRED_BACKLOG-Atome im Scope, semantic_gates `passed`,
   Lock gehalten (Re-Check), Coverage-Register final, Register-Digests in
   RUN konsistent.
6. `deferred` ⇒ Blocker mit `visible_anchor` + Owner.
7. Teillaeufe: Exit 2 + `INCOMPLETE_CHECK_SET` mit Liste gelaufener Checks.

## 10. `concept/_meta/projection-manifest.json` (korpusweit) [R3-3]

```json
{
  "schema_version": "1.0.0",
  "entries": [
    { "scope_id": "...",
      "assertion_source": { "path": "...", "digest": "<sha256>" },
      "assertion_status": "draft|active|blocked_projection|deprecated|superseded",
      "required_projections": [
        { "kind": "formal|prose|registry|support|test-oracle",
          "target": "<path-oder-id>", "target_digest": "<sha256|null>",
          "receipt_ref": "<pfad|null>",
          "equivalence_status": "unreviewed|equivalent|disagrees|stale|blocked_missing_target" }
      ],
      "last_run_id": "<run_id|null>" }
  ]
}
```

Ableitung (deterministisch, Owner dieses Artefakt): Receipt fehlt →
`unreviewed`; `target_digest` weicht vom Ist ab → `stale`; Ziel fehlt →
`blocked_missing_target`; alle `equivalent` und keine Blocker im letzten
Lauf → `assertion_status=active`, sonst `blocked_projection`.
`check.py projection` prueft Manifest gegen Ist-Korpus.

## 11. `concept/_meta/concept-governance.json`

```json
{
  "schema_version": "1.0.0",
  "concept_roots": { "domain": "concept/domain-design",
    "technical": "concept/technical-design", "formal": "concept/formal-spec",
    "meta": "concept/_meta", "guardrails": "guardrails" },
  "incubator_root": "concept-incubator",
  "lock_backend": "filesystem|git-remote",
  "id_grammars": { "domain_doc": "^DK-\\d{2}$", "technical_doc": "^FK-\\d{2}$",
    "formal_object": "^formal\\.[a-z0-9-]+\\.[a-z0-9-]+$",
    "decision_record": "^\\d{4}-\\d{2}-\\d{2}-[a-z0-9-]+$",
    "scope": "^[a-z0-9]+([.-][a-z0-9]+)*$" },
  "frontmatter_contract": {
    "required_fields": ["concept_id", "title", "module", "status", "doc_kind",
      "parent_concept_id", "authority_over", "defers_to", "supersedes",
      "superseded_by", "tags"],
    "classification": "formal_refs_xor_prose_only",
    "detail_requires_parent": true,
    "full_supersession_reciprocity": true },
  "vcs_policy": { "mode": "class_based",
    "sensitive_disposition": "local", "unclassified_class": "sensitive" },
  "data_class_default": "sensitive"
}
```

## 12. CLI-Vertrag [R3-7]

- `check.py` (strikt read-only): `frontmatter | references | formal |
  decision-gate --base <rev> | incubator <run> | promotion <run> |
  projection | semantic-status <run> | all [--run <run>]`.
- `semantic_gate.py` (mutierend; verlangt gueltige Lease, schreibt atomar,
  Idempotency-Key = Digest des Requests): `units <run>` |
  `prepare <run> --gate <w2|w3>` | `import <run> <receipt-file>`.
- Exit-Codes (beide): 0 PASS; 1 Befunde; 2 fehlende Voraussetzungen /
  deklarierter INCOMPLETE-Teillauf; 3 Usage-/Konfigfehler. Exit 2 nie fuer
  vollstaendig gelaufene Einzel-Checks.
- `--json`-Envelope: `{ "schema_version": "1.0.0", "command": "...",
  "check_set": ["..."], "complete": true, "findings": [ { "check_id": "...",
  "severity": "ERROR", "path": "...", "locator": "...", "message": "..." } ] }`.
