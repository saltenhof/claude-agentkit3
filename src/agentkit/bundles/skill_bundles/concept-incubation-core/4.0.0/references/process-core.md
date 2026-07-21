# Process-Core — Kurzreferenz des Konzeptionsverfahrens (FK-78)

Single-Source-Referenz fuer beide Harnesses. In AK3-registrierten
Projekten ist FK-78 (`concept/technical-design/78_concept_incubation_process.md`
im AK3-Repo) die normative Quelle. **Fuer Zielprojekte ohne Zugriff auf
das AK3-Repo sind dieses Dokument, die `templates/` und die im Bundle
mitgelieferten JSON-Schemas der Toolchain der selbsttragende Vertrag** —
die Toolchain prueft fail-closed gegen exakt diese Schemata.

## 1. Blueprint der Konzeptwelt

```text
<projekt>/
  concept/
    domain-design/       # fachliche Prosa (Problemraum → Loesungsidee)
    technical-design/    # Fach- UND IT-Feinkonzepte (implementierbar)
    formal-spec/         # 00_meta + ein Verzeichnis je Kontext:
                         #   entities/state-machine/commands/events/
                         #   invariants/scenarios (structured markdown)
    _meta/               # Governance: Konsistenzprinzipien,
                         #   assertion-authority, decisions/,
                         #   projection-manifest.json, concept-governance.json
  concept-incubator/     # Werkstatt — niemals normative Wahrheit
  guardrails/
```

Kernregeln der normativen Welt:

- **Frontmatter-Vertrag** je Dokument: `concept_id` (Grammatik aus
  `concept-governance.json`), `authority_over` (Scopes), `defers_to`,
  `supersedes`/`superseded_by` (reziprok), Klassifikation genau eine
  Variante: `formal_refs` (non-empty) XOR `formal_scope: prose-only`.
- **Authority-Graph**: azyklisch, kein Scope mit zwei Ownern.
- **Single-Assertion (P1)**: jede normative Aussage existiert genau
  einmal (im Scope-Owner-Dokument); andere Dokumente referenzieren per
  ID+Anker, paraphrasieren nie. Paraphrasen altern und widersprechen.
- **Formal-Layer**: Zustaende, Uebergaenge, Terminalitaet, Commands,
  Events, Invarianten, Szenario-Traces. Widerspruchsanfaellige Semantik
  (Lifecycle, Ownership) wandert in den Formal-Layer.
- **Assertion-Authority**: Eine angenommene Entscheidung setzt das Ziel;
  ausfuehrbar ist ein Scope erst mit nachweislich aequivalenter
  Projektion; Widerspruch/Fehlen blockiert (`blocked_projection`) —
  keine Ebene "gewinnt" still.
- **Drei Welten**: normative Welt / Backlogs / Werkstatt. Die Werkstatt
  hat ein Manifest (`concept-incubator/INDEX.md`: Zweck, Status,
  Verbleib je Artefakt); Offenes muss von der normativen Welt oder einem
  Backlog aus sichtbar sein.

Initialisierung einer leeren Welt: Verzeichnisse anlegen,
`templates/concept-governance.json`, `templates/projection-manifest.json`,
`templates/INDEX.md`, `templates/gitignore-fragment.txt` einsetzen und
projektspezifisch anpassen (ID-Grammatiken!). Erst dann den ersten Lauf
starten.

## 2. Lauf-Artefakte (Schemata)

Alle JSON-Artefakte: `schema_version`, nur deklarierte Felder
(fail-closed), UTC-`Z`-Zeiten, SHA-256 lowercase-hex. TSV: Header-Zeile,
keine TAB/CR/LF in Feldern, nach ID sortiert. Vorlagen unter
`templates/`; massgebliche Feldkataloge: FK-78 §78.3–§78.13.

```text
runs/<run_id>/            # run_id: YYYY-MM-DD-<slug>-<uuid8>
  RUN.json                # EINZIGER autoritativer Zustand + Cursor
  LEASE.json              # Writer-Lease (TTL, fencing_token)
  briefing.md
  baseline/corpus-baseline.tsv, source-intake.tsv, source-register.tsv,
           source-units.tsv, source-coverage.tsv, normative-coverage.tsv,
           coverage-plan.json
  artifact-register.tsv   # Provenienz + Datenklassen; ab FRAMING PFLICHT
  findings.tsv            # dedupliziertes Befundregister; ab PROMOTING PFLICHT
  workers/<pid>/{inbox/,outbox/proposal.md}
  rounds/r<N>/{<pid>.md, ROUND.json}
  synthesis/{claims-inventory.tsv, synthesis-r<N>.md, dissent-map.md,
             disposition-ledger.tsv}
  promotion/{atom-register.tsv, promotion-manifest.json, receipts/}
  declassification/       # Declassification-Receipts
  secrets/                # immer gitignored
  journal.md              # append-only Historie, NIE Cursor
```

Zustaende (`RUN.json.state`): `FRAMING → STAFFING → PROPOSING ↔
CONVERGING → SYNTHESIZING → DECIDING → PROMOTING → CLOSED`, seitlich
`BLOCKED`, `RECHECK`, `PROMOTION_FAILED`, `ABORTED`.

## 3. Verlustfreiheits-Kette (das Herzstueck)

1. **Baseline-Freeze** (FRAMING): relevante Normdateien mit Digest
   inventarisiert. Spaetere Aenderung = Drift = RECHECK, nie stilles
   Weiterarbeiten.
2. **Input-Freeze** (vor Synthese): jede Quelle zuerst im append-only
   `source-intake.tsv`, dann im `source-register.tsv` (Briefing, ALLE
   Proposal-Fassungen, PO-Inputs) — der Checker erzwingt Mengengleichheit
   beider Register sowie, fuer Derivate, gegen die kanonischen Pfade
   (`synthesis/synthesis-r*.md`, `dissent-map.md`,
   `po-decision-<slug>.md`); ein Weglassen faellt damit auf.
   **Source-Units**
   tool-deriviert (eine Unit je Ueberschriftsabschnitt; der Checker
   re-deriviert — Ausduennen unmoeglich); **Claim-Inventar**: jede Unit
   → Claims oder begruendete Leer-Disposition
   (`NO_MATERIAL_CONTENT | DUPLICATE_OF:<unit> | OUT_OF_SCOPE:<grund>`).
3. **Dispositions-Ledger** (nach Synthese): je Claim genau eine
   Disposition (`ADOPTED|MERGED|SUPERSEDED_BY_CLAIM|
   REJECTED_WITH_REASON|OPEN_QUESTION`); Nicht-Uebernommenes braucht
   eine Restkante (`CHECKED_AGAINST_CURRENT|ESCALATED_TO_PO`);
   Synthese/Dissent/PO-Entscheidungen werden als `derived`-Quellen
   nachregistriert und ihre neuen Claims ebenfalls disponiert.
4. **Atomregister**: adoptierte Claims → qualifikatorentreue Atome
   (Bedingungen, Owner, Failure-Semantik reisen mit!) mit genau einem
   Autoritaetsziel-Scope (Reihenfolge: Decision → Domain → FK → Formal →
   Registry → Guardrail); `COVERED_SPLIT` listet alle Teilziele.
   Dispositionen: `COVERED_EXACT|COVERED_SPLIT|REJECTED|OPEN_MISSING|
   DEFERRED_BACKLOG|EVIDENCE_ONLY|OUT_OF_AUDIT|SUPERSEDED`.
   `DEFERRED_BACKLOG` braucht Owner+Trigger+sichtbaren Anker.
5. **Receipts**: je COVERED-Atom ein Aequivalenz-Receipt eines
   unabhaengigen Reviewers (anderer Principal UND andere Session);
   `disagrees` → PO, kein Writer-Override.
6. **Reverse Trace**: jeder nicht-formatale Diff-Hunk unter `concept/`
   muss von einem Atom-/Receipt-Anker (kleinste umschliessende
   Ueberschrift oder Vorfahre) gedeckt sein — nichts wird
   eingeschmuggelt.
7. **Coverage-Abschluss**: `source-coverage.tsv` (eine finale Zeile je
   Quelle, Reviewer ≠ Autor) und `normative-coverage.tsv` (baseline ∪
   current, `change_kind`).

Verbotene Abkuerzungen: Keyword-Treffer ≠ Deckung; gruener Compiler ≠
Verlustfreiheit; Review-Abschluss ≠ Reparatur-Abschluss; Qualifikatoren
nie vom Claim abtrennen; Zitate/Extrakte nie als unabhaengige Evidenz
doppelt zaehlen.

## 4. Statusmodell (vier Achsen, drei Owner)

| Achse | Werte | Owner |
|---|---|---|
| Decision-Lifecycle | proposed/accepted/rejected/superseded | Decision Record |
| promotion_disposition (je Scope im Lauf) | promoted/rejected/deferred | promotion-manifest.json |
| assertion_status (je Scope, korpusweit) | draft/active/blocked_projection/deprecated/superseded | projection-manifest.json |
| equivalence_status (je Projektion) | unreviewed/equivalent/disagrees/stale/blocked_missing_target | projection-manifest.json (abgeleitet) |

Ableitung: Lifecycle zuerst (draft/deprecated/superseded bleiben);
nur die aktuelle akzeptierte Assertion wird abgeleitet: Receipt fehlt →
unreviewed; Digest weicht ab → stale; Ziel fehlt →
blocked_missing_target; alles equivalent + keine Blocker → active,
sonst blocked_projection.

## 5. Datenklassen

`open | internal | sensitive`; unklassifiziert = sensitive. Derivate
erben die HOECHSTE Eingangsklasse (`artifact-register.tsv` mit
Provenienz); Herabstufung nur per Declassification-Receipt
(digest-gebunden). `sensitive` bleibt lokal (nicht versioniert); das
Commit-Gate blockiert Verstoesse. Datenfreigabe je Teilnehmer:
max_data_class + konkrete Quell-/Paketlisten, vom User bestaetigt.

## 6. Locking und Schreibdisziplin

- **Writer-Lease** (`LEASE.json`): Erwerb O_EXCL; Renew atomarer
  Replace; Takeover nur nach TTL/Release ueber Intent-Datei mit
  `fencing_token + 1`.
- **RUN-Mutation**: unter Mutations-Mutex (`RUN.mutex`, O_EXCL) Lease +
  `state_revision` re-verifizieren, dann atomarer Replace mit
  Revision+1. Wer nicht verifizieren kann, bricht ab (stale write
  unmoeglich).
- **Scope-Locks** (vor PROMOTING, je betroffenem Scope):
  Backend `filesystem`: `locks/<scope>.<hash8>.lock.json` per O_EXCL;
  Backend `git-remote`: Ref `refs/concept-locks/<hash>` per
  Create-only-Push (CAS); dieses Backend verlangt zwingend das Feld
  `lock_remote` in `concept-governance.json` (erwartetes Remote) und
  eine Evidenzdatei `promotion/lock-evidence.json`, sonst bleibt der
  Lock-Check unvollstaendig. Release nur nach Owner-/Token-Recheck bzw.
  Ref-CAS. Besitz + erwartete `base_revision` unmittelbar vor der
  finalen Landung erneut pruefen.

## 7. Toolchain-Aufrufe

`tools/agentkit/concept_toolchain/` (im Zielprojekt deployt; stdlib-only):

```text
python tools/agentkit/concept_toolchain/check.py <cmd> [--project-root .] [--json]
  frontmatter | references | formal | decision-gate --base <rev>
  incubator <run-dir> | promotion <run-dir> | projection
  semantic-status <run-dir> | all [--run <run-dir>]      # strikt read-only
python tools/agentkit/concept_toolchain/semantic_gate.py <cmd> \
  --principal <id> --session <ref> --fencing-token <n>   # PFLICHT je Aufruf
  units <run-dir> | prepare <run-dir> --gate w2|w3 | import <run-dir> <receipt>
Exit: 0 PASS · 1 Befunde · 2 fehlende Voraussetzungen/INCOMPLETE · 3 Usage
```

Die Schreiber-Identitaet ist Pflicht: `--principal`/`--session` muessen
dem Lease-Owner entsprechen, `--fencing-token` dem Token in `LEASE.json`
UND `RUN.json`. Ohne diese Parameter endet der Aufruf mit Exit 3 — sie
sind die Absicherung gegen stale Writes.

```text
```

Semantik-Gates (W2 Authority-Prose, W3 Scope-Consistency) sind
LLM-Bewertungen mit deterministischer Verrechnung: `prepare` erzeugt
Request-Packs, DU (oder ein Hub) fuehrst die Bewertung aus, `import`
registriert das Receipt, `semantic-status` verrechnet. Fehlender
LLM-Zugang blockiert die betroffenen Scopes — niemals stilles PASS.

## 8. Proportionalitaet und Bagatellen

Profile: `DIRECT_GOVERNED_CHANGE` (kein Council; Decision Record +
Betroffenheitsmatrix + Gates), `LIGHT_INCUBATION` (1–2 Worker,
Claim-Verfahren, Coverage nur fuer Beruehrtes), `FULL_ATOM` (volles
Verfahren; Trigger: Migration in die Normwelt, Verlustfreiheitsanspruch,
mehrere Autoritaeten, Dokumentfamilien-Umbau, Ownership-Verschiebung,
PO-Auftrag). Bagatellen ohne normativen Gehalt: record-frei, aber alle
deterministischen Gates gelten immer.
