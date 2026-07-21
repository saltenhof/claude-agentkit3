---
concept_id: FK-78
title: Concept-Incubation — Blueprint, Inkubator-Prozess, Promotion und Toolchain
module: concept-incubation
domain: concept-incubation
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: concept-incubation-technical
  - scope: incubator-artifact-schemas
  - scope: promotion-closure
  - scope: projection-manifest-format
  - scope: concept-toolchain
defers_to:
  - target: DK-16
    scope: conception-process
    reason: Fachliche Prozessidee, Rollenmodell und Blueprint-Motivation liegen im Domaenenkonzept; FK-78 normiert die technische Realisierung
  - target: FK-23
    scope: exploration-mode
    reason: Storylokale Modusermittlung und Change-Frames bleiben bei exploration-and-design; FK-78 besitzt nur die corpus-weite Konzept-Evolution
  - target: FK-25
    scope: fine-design
    reason: Storylokales Feindesign bleibt bei exploration-and-design
  - target: FK-43
    scope: skills
    reason: Skill-Format, Bundles, Versionierung und Bindung liegen bei agent-skills; FK-78 definiert nur den Skill-INHALT der Konzeptions-Skills
  - target: FK-76
    scope: harness-integration
    reason: Harness-Adapter, Settings und Spawn-Mechanik liegen bei harness-integration; FK-78 referenziert sie nur
  - target: FK-30
    scope: hook-definition-and-enforcement
    reason: FK-78 definiert die Inkubator-Principal-/Pfadklassen-REGELN; Guard-Definition und Enforcement-Verhalten bleiben bei governance-and-guards
  - target: FK-50
    scope: installer-orchestration
    reason: Installation und Bindung der Toolchain-/Skill-Assets orchestriert der Installer
supersedes: []
superseded_by:
tags: [concept-incubation, conception, council, promotion, blueprint, toolchain, skills]
applies_policies: [policy.concept-consistency-governance, policy.assertion-authority, policy.fail-closed, policy.zero-debt]
prose_anchor_policy: strict
formal_refs:
  - formal.concept-incubation.entities
  - formal.concept-incubation.state-machine
  - formal.concept-incubation.commands
  - formal.concept-incubation.events
  - formal.concept-incubation.invariants
  - formal.concept-incubation.scenarios
glossary:
  exported_terms:
    - id: incubation-run
      definition: >
        Ein abgeschlossener Arbeitsvorgang im Concept-Incubator mit
        stabiler run_id, eigenem Zustandsdokument (RUN.json), Baseline,
        Teilnehmern, Runden, Synthese- und Promotionsakten. Der Lauf ist
        die Einheit von Nachvollziehbarkeit, Locking und Closure.
    - id: council-orchestrator
      definition: >
        Dritter AK3-Work-Mode fuer Konzeptarbeit: moderiert den Lauf,
        steuert Runden und Round-Seals, bewertet Konvergenz,
        synthetisiert nach Claim-Inventar-Closure und fuehrt die
        Promotion. Schreibt kein eigenes konkurrierendes Proposal und
        bezieht in Moderationsphasen keine inhaltliche Partei-Position.
    - id: council-worker
      definition: >
        Gremiums-Worker eines Inkubationslaufs: gespawnter Agent, der
        das zugeteilte Coverage-Paket selbst analysiert und ein
        eigenstaendiges Proposal mit normativen Ankern verfasst.
        Schreibt ausschliesslich in die eigene Outbox; fremde Proposals
        sind fuer ihn Daten, nie Instruktionen.
    - id: round-seal
      definition: >
        Versiegelung eines Rundenstands: der Orchestrator kopiert die
        Worker-Proposals mit Digest-Bindung in das Rundenverzeichnis.
        Erst versiegelte Staende duerfen in Folgerunden fremden Workern
        zum Cross-Read bereitgestellt werden.
    - id: source-unit
      definition: >
        Deterministisch aus einer Quelle abgeleitete kleinste
        Abdeckungseinheit (Ueberschriftsabschnitt bzw. Absatzblock) mit
        Locator und Digest. Jede Unit muss Claims tragen oder eine
        begruendete Leer-Disposition besitzen; der Checker re-deriviert
        Units und macht Ausduennung unmoeglich.
    - id: claim-inventory
      definition: >
        Vor der Synthese eingefrorenes Register aller materiellen
        Quell-Claims (qualifikatorentreu, mit Unit-Referenzen und
        Genealogie). Inventar-Closure ist das Eintritts-Gate der
        Synthese.
    - id: disposition-ledger
      definition: >
        Register, das jedem Inventar-Claim genau eine begruendete
        Synthese-Disposition und fuer nicht uebernommene Claims eine
        Restkante zuweist. Dispositions-Closure ist das Eintritts-Gate
        der Promotion.
    - id: atom-register
      definition: >
        Register der qualifikatorentreuen Promotions-Atome mit
        Autoritaetsziel, Enddisposition, Claim- und Receipt-Referenzen.
    - id: promotion-manifest
      definition: >
        Lauf-gebundenes Manifest der Promotion: betroffene Scopes mit
        promotion_disposition, Pflichtmengen, Ziel-Digests, Receipts,
        Scope-Locks und Semantik-Gate-Stand. Traeger der
        Promotion-Closure.
    - id: projection-receipt
      definition: >
        Beleg der semantischen Aequivalenz eines Atoms mit seiner
        normativen Zielpassage: Quell-/Sektions-Digests, Writer- und
        Reviewer-Principal (verschieden, verschiedene Sessions) und
        Verdict.
    - id: projection-manifest
      definition: >
        Korpusweites, versioniertes Register in concept/_meta, das je
        AssertionScope die Pflichtprojektionen, deren abgeleiteten
        equivalence_status und den assertion_status traegt. Einzige
        maschinelle Heimat der Statusableitung nach
        META-ASSERTION-AUTHORITY.
    - id: scope-lock
      definition: >
        Exklusiver, TTL- und Fencing-Token-behafteter Lock je
        normalisierter Scope-ID, der einen Scope waehrend PROMOTING an
        genau einen Lauf bindet. Zwei normierte Backends: filesystem
        (O_EXCL-CAS) und git-remote (Ref-CAS).
    - id: concept-toolchain
      definition: >
        Deploybares, stdlib-only Zielprojekt-Tooling
        (tools/agentkit/concept_toolchain/) mit den generischen
        Konzept-Gates, Inkubator-/Promotions-Checks und
        Semantik-Gate-Mechanik. Single Source of Truth der generischen
        Gate-Implementierung.
  internal_terms:
    - id: smy-parser
      reason: >
        Implementierungsdetail der Toolchain (YAML-Subset-Parser);
        Konsumenten nutzen die CLI, nicht den Parser.
    - id: mutation-mutex
      reason: >
        Implementierungsdetail des CAS-Schreibprotokolls; nach aussen
        zaehlt nur die Garantie, dass stale Writes unmoeglich sind.
---

# 78 — Concept-Incubation: Blueprint, Inkubator-Prozess, Promotion, Toolchain

## 78.1 Zweck und Abgrenzung

<!-- PROSE-FORMAL: formal.concept-incubation.entities -->

FK-78 normiert die technische Realisierung der Konzeptionssaeule (DK-16):
die Blueprint-Topologie einer Konzeptwelt, den Concept-Incubator mit
seinen Artefakt-Schemata und seinem Lauf-Lifecycle, das verlustfreie
Promotionsverfahren, das korpusweite Projektionsmanifest, die deploybare
Toolchain und die Skill-Auslieferung. Es gilt fuer Zielprojekte UND fuer
AK3s eigene Konzeptwelt (Referenzimplementierung).

Nicht Teil von FK-78: storylokale Designarbeit (FK-23/FK-25),
Skill-Mechanik (FK-43), Harness-Anbindung (FK-76), Guard-Enforcement
(FK-30), Statussemantik-Prosa (META-ASSERTION-AUTHORITY),
Konsistenzprinzipien P1–P5 (META-CONCEPT-CONSISTENCY). In v1 existiert
bewusst kein Backend-/Control-Plane-/Telemetrie-Anteil: der Inkubator
laeuft ueber Skills, Dateisystem und deterministische Checks.

## 78.2 Blueprint-Topologie und Projekt-Governance-Konfiguration

Soll-Topologie eines Zielprojekts:

```text
<projekt>/
  concept/
    domain-design/            # fachliche Prosa-Konzepte
    technical-design/         # Fach- und IT-Feinkonzepte
    formal-spec/              # 00_meta + ein Verzeichnis je fachlichem Kontext
    _meta/                    # Governance-Dokumente, decisions/, Registries,
                              #   projection-manifest.json, concept-governance.json
  concept-incubator/          # Werkstatt (78.3); niemals normative Wahrheit
  guardrails/
```

`concept/` ist Markdown-only mit genau einer Ausnahme: schema-validierte
Registry-/Manifest-Dateien unter `concept/_meta/` (insbesondere
`projection-manifest.json`, `concept-governance.json` sowie
Gate-Baselines). Diese Dateien sind normative Eingaben bzw.
verifier-geprüfte Materialisierungen — keine frei generierten Artefakte;
generierte Ableitungen gehoeren weiterhin nach `var/`.

**`concept/_meta/concept-governance.json`** (projektlokal, versioniert)
konfiguriert die Toolchain projektneutral. Feldkatalog:

| Feld | Inhalt |
|---|---|
| `schema_version` | SemVer |
| `concept_roots` | Pfade fuer `domain`, `technical`, `formal`, `meta`, `guardrails` |
| `incubator_root` | Default `concept-incubator` |
| `lock_backend` | `filesystem` \| `git-remote` (78.11) |
| `lock_remote` | erwartetes Git-Remote fuer Scope-Locks; Pflicht (fail-closed), sobald `lock_backend: git-remote` |
| `id_grammars` | Regex je ID-Klasse: `domain_doc`, `technical_doc`, `formal_object`, `decision_record`, `scope`, `source` |
| `frontmatter_contract` | `required_fields`, `classification: formal_refs_xor_prose_only`, `detail_requires_parent`, `full_supersession_reciprocity` |
| `vcs_policy` | `mode: class_based`, `sensitive_disposition: local`, `unclassified_class: sensitive` |
| `data_class_default` | `sensitive` (fail-closed) |

ID-Grammatiken sind projektkonfigurierbar; AK3s zweistellige
`DK-NN`/`FK-NN`-Schemata sind AK3-lokale Konfiguration, keine
Blueprint-Norm. Neue Projekte SOLLEN erweiterbare Grammatiken waehlen
(Namespace-Praefix, unbegrenzte Stellenzahl).

## 78.3 Inkubator-Layout und Artefakt-Familie

<!-- PROSE-FORMAL: formal.concept-incubation.entities -->

```text
concept-incubator/
  INDEX.md                          # Werkstatt-Manifest: Zweck/Status/Verbleib je Artefakt
  locks/                            # nur lock_backend=filesystem; IMMER gitignored
  runs/<run_id>/
    RUN.json                        # einziger autoritativer Lauf-Zustand (78.4)
    RUN.mutex                       # Mutations-Mutex (nur waehrend Schreibvorgang)
    LEASE.json                      # Writer-Lease (78.4)
    briefing.md                     # Auftrag, Scope-Frame, Datenklassifikation
    baseline/
      corpus-baseline.tsv           # Normwelt-Inventur (Freeze im FRAMING)
      source-register.tsv           # Quellenregister, zweiphasig (78.7)
      source-units.tsv              # deterministische Units je Quelle (78.7)
      source-coverage.tsv           # finaler Reviewstatus je Quelle (78.8)
      normative-coverage.tsv        # finaler Reviewstatus je Normdatei (78.8)
      coverage-plan.json            # FULL_ATOM: Worker-Pakete (78.6)
    artifact-register.tsv           # Provenienz + Datenklassen (78.13)
    findings.tsv                    # dedupliziertes Befundregister (78.9)
    workers/<participant_id>/
      inbox/                        # zugeteilte Eingaben (ggf. read-only Korpus-Kopie)
      outbox/proposal.md            # EINZIGER Schreibort des Workers
    rounds/r<N>/
      <participant_id>.md           # versiegelte Proposals
      ROUND.json                    # Dispatch/Receipt/Seal (78.6)
    synthesis/
      claims-inventory.tsv          # Phase A (78.8)
      synthesis-r<N>.md             # Synthese-Staende
      dissent-map.md                # Konsens/Dissens/offene PO-Fragen
      disposition-ledger.tsv        # Phase B (78.8)
    promotion/
      atom-register.tsv             # (78.9)
      promotion-manifest.json       # (78.11)
      receipts/<receipt_id>.json    # (78.10)
    declassification/<receipt_id>.json   # (78.13)
    secrets/                        # IMMER gitignored; nie Schema-Bestandteil
    journal.md                      # append-only Historie; NIE Wiederaufnahme-Cursor
```

Allgemeine Felddisziplin fuer alle strukturierten Artefakte: JSON mit
`schema_version` (SemVer) und **fail-closed bei unbekannten Feldern**;
Zeiten UTC-ISO-8601 mit `Z`; Digests SHA-256 lowercase-hex (Dateien:
Rohbytes; Sektionen/Units: LF-normalisierter Text); TSV mit Header-Zeile,
Tab-getrennt, keine TAB/CR/LF in Feldern (Zeilenumbrueche als literales
`\n`), Zeilen nach ID aufsteigend sortiert; Pfade projektrelativ mit `/`
und Containment unter den `concept_roots`/`incubator_root`; jedes Feld
Pflicht, sofern nicht explizit als optional/leer-erlaubt deklariert.

ID-Grammatiken: `run_id` `^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$`
(Suffix = `run_uuid8`); `participant_id` `^[a-z0-9]+(-[a-z0-9]+)*$`;
`unit_id` `^SU-[0-9a-f]{8}-\d{4,}$`; `claim_id` `^CLM-[0-9a-f]{8}-\d{4,}$`;
`atom_id` `^ATM-[0-9a-f]{8}-\d{4,}$`; `receipt_id` `^RCP-[0-9a-f]{8}-\d{4,}$`;
`package_id` `^PKG-[0-9a-f]{8}-\d{2,}$`; `finding_id` `^FND-[0-9a-f]{8}-\d{4,}$`;
`source_id` `^SRC-[0-9a-f]{8}-\d{4,}$`; `principal_id`
`^[a-z0-9]+([._-][a-z0-9]+)*$` (stabil je Akteur, OHNE Session-Anteil).
Zaehler sind unbegrenzt mit Mindestbreite 4 (Packages: 2). Invariante: der
`uuid8`-Anteil aller Lauf-IDs entspricht dem `run_uuid8`. IDs werden nie
umnummeriert oder wiederverwendet; Tombstones existieren ausschliesslich
fuer Atome (Disposition `SUPERSEDED`).

Vertrauensanker der Intake-Pins: Die Pins liegen in `RUN.json`. Wer
zusaetzlich diese Datei umschreibt, kann jede Kette dateilokal
konsistent machen — der Anker gegen genau diesen Angriff ist die
versionierte `RUN.json` in der VCS-Historie, nicht ein dateilokaler
Vergleich. Das ist eine bewusste, benannte Grenze des dateibasierten
Verfahrens, kein unerkannter Rest.

Secret-Vertrag: `session_ref`-Felder tragen ausschliesslich opake,
nicht-geheime Handles. Tokens, Credentials und Keys sind in allen Schemata
verboten; geheime Wiederaufnahmedaten liegen nur unter `secrets/`.

## 78.4 Lauf-Lifecycle, Zustandsdokument und Schreibprotokoll

<!-- PROSE-FORMAL: formal.concept-incubation.state-machine, formal.concept-incubation.entities -->

Die `run_status`-Achse (Zustaende, Uebergaenge, Terminalitaet,
Crash-/Resume-, Timeout-, Takeover- und Abbruchpfade) ist ausschliesslich
formal normiert (formal.concept-incubation.state-machine); FK-78
wiederholt sie nicht. Checker-relevant ist das Gate-Mapping:

| Uebergang | Deterministisches Gate (Toolchain) |
|---|---|
| FRAMING → STAFFING | Baseline-Freeze vorhanden (`corpus_baseline`-Digest gepinnt) |
| CONVERGING → SYNTHESIZING | Input-Source-Freeze + Claim-Inventar-Closure (78.7/78.8) |
| DECIDING → PROMOTING | Dispositions-Closure (inkl. Derived-Claims), Findings geroutet, Scope-Locks erworben (78.11) |
| PROMOTING → CLOSED | Promotion-Closure inkl. finaler Coverage-Register ueber baseline ∪ current (78.8/78.11) |

Der Coverage-Abschluss ist Austritts-Gate von PROMOTING, **nicht**
Eintrittsbedingung. Drift-Checks (Baseline vs. Current) laufen vor
SYNTHESIZING, vor PROMOTING und unmittelbar vor der finalen Landung;
erkannter Drift fuehrt nach RECHECK mit Adjudikationspflicht.

**`RUN.json`** ist der einzige autoritative Lauf-Zustand. Feldkatalog:

| Feld | Typ/Werte | Anmerkung |
|---|---|---|
| `schema_version` | SemVer | |
| `run_id`, `title`, `profile` | `LIGHT_INCUBATION` \| `FULL_ATOM` | Profilwechsel nur per Re-Framing |
| `state` | run_status-Werte | |
| `state_revision` | int, strikt monoton | CAS-Anker |
| `lease_fencing_token` | int | Token des Schreibenden, bei JEDER Mutation |
| `current_round` | int >= 0 | |
| `base_revision` | `{kind: git\|digest, value}` | Normwelt-Stand des Freeze |
| `data_class` | `open\|internal\|sensitive` | |
| `actor` | `{role, harness, model, principal_id, session_ref}` | Council-Orchestrator |
| `participants[]` | s. u. | |
| `register_digests` | `{corpus_baseline, source_intake_input_head, source_intake_final_head, source_register_input, source_units_input, claims_inventory_input, derived_claims, disposition_ledger, source_register_final, source_units_final, atom_register}` je `sha256\|null`. Die beiden Intake-Pins (§78.7) liegen ausserhalb des Intake-Registers: `source_intake_input_head` friert die Kette beim Input-Freeze ein, `source_intake_final_head` vor dem Eintritt in PROMOTING. Ein einzelner, mitwandernder Head waere kein Freeze — Derived-Quellen werden legitim nachgetragen, und mit nur einem Pin liesse sich die Kette samt Pin gemeinsam neu berechnen | `null` bis zum jeweiligen Gate, danach Pflicht und unveraenderlich (Aenderung nur ueber RECHECK-Adjudikation mit neuem Gate). Input-Freezes (`*_input`) werden nie ueberschrieben; Derived-Claims und Final-Staende werden vor PROMOTING separat gepinnt |
| `blocked` | object\|null: `{reason, since_state}` | non-null nur in BLOCKED |
| `recheck` | object\|null: `{drifted_paths[], detected_in_state}` | non-null nur in RECHECK |
| `last_completed_action`, `next_action` | stabile Action-IDs | Wiederaufnahme-Cursor |
| `updated_at` | UTC-ISO | |

`participants[]`: `{participant_id, model, backend, spawn_mode:
harness-bridge|llm-hub|subagent|cli-resume, principal_id, session_ref|null,
data_release: {max_data_class, source_ids[], package_ids[],
approved_by_user}, status: active|failed|replaced|withdrawn}`.

**Schreibprotokoll (echtes CAS):** Jede RUN-Mutation laeuft unter einem
separaten Mutations-Mutex `RUN.mutex` (O_CREAT|O_EXCL) mit dem Inhalt
`{owner_principal, owner_session, nonce, acquired_at, heartbeat_at,
ttl_seconds}`. Innerhalb des Mutex werden LEASE, `fencing_token` und
`state_revision` erneut gelesen und verifiziert, erst dann erfolgt der
atomare Replace-Write (temp + rename) mit `state_revision + 1`. Ein
Schreiber, der Lease oder Revision nicht bestaetigen kann, bricht ab
(stale write unmoeglich).

Ablauf wird gegen `heartbeat_at` gerechnet, das vor jedem Schreibschritt
aufgefrischt wird; die eigene `nonce` wird vor jedem Dispatch und vor
jedem Schreibschritt revalidiert — fremde Nonce, gewechselter Owner oder
abgelaufener eigener Heartbeat sind harter Abbruch, kein Weiterlaufen.
Validierung und Wirkung duerfen nicht auseinanderfallen. Saemtliche
Mutex-Aenderungen und -Wirkungen — Erwerb, Takeover, Heartbeat-Refresh,
Ziel-Write und Freigabe — laufen unter **genau einem**
Coordination-Intent `RUN.mutex.intent` (O_CREAT|O_EXCL, Felder
`{holder_principal, holder_session, intent_nonce, acquired_at,
ttl_seconds}`). Zwei getrennte Intents fuer Schreiben und Uebernahme
waeren ein Koordinationsprimitiv zu viel: eine Uebernahme koennte
zwischen Ownership-Pruefung und Heartbeat schluepfen, und der alte
Schreiber wuerde den fremden Mutex mit seiner alten Nonce
ueberschreiben. Das Intent traegt deshalb eine eigene Nonce und wird
ausschliesslich per Nonce-Match freigegeben (compare-before-delete);
ein Aufraeumen ohne Identitaetspruefung ist auf keinem Pfad zulaessig.
Der Heartbeat-Refresh revalidiert Mutex-Nonce und Owner unmittelbar vor
dem Schreiben; fremde Nonce ist harter Abbruch. Der Ziel-Write ist
zweiphasig und prueft die Ownership unmittelbar vor dem finalen
`os.replace` erneut. Das verbleibende Zeitfenster ist dieser eine
atomare Replace.
**Takeover eines abgelaufenen Mutex** laeuft unter demselben
Coordination-Intent: wer es nicht per O_CREAT|O_EXCL anlegen kann,
verliert; unter dem Intent muss der Mutex noch dieselbe Identitaet
(`nonce` UND `heartbeat_at`) tragen wie zuvor beobachtet, sonst bricht
auch der Uebernehmer ab; erst dann atomarer Replace mit eigener Nonce
und Freigabe nur nach Re-Read mit Nonce-Match (compare-before-delete).
Damit koennen zwei Uebernehmer nicht beide gewinnen.

**Benannte Grenze — Aufraeumen verwaister Intents.** Bleibt ein Intent
nach einem Prozessabsturz liegen, ist seine automatische Bereinigung
Read-then-Unlink und damit selbst nicht atomar: Zwei Aufraeumer koennen
dieselbe alte Nonce lesen, der eine loescht und legt ein neues Intent
an, der andere loescht anschliessend dieses neue Intent auf Basis seiner
frueher gelesenen Identitaet — der erste liefe dann ohne sein Intent
weiter. Der Pfad ist auf den seltenen Fall "verwaistes Intent trifft auf
zwei gleichzeitige Aufraeumer" beschraenkt und beruehrt den normalen
Einzelschreiber-Betrieb nicht. Belastbar aufgeloest wird er nur durch
einen nachweislich atomaren Mechanismus: ein OS-Advisory-Lock
(`fcntl.flock` bzw. `msvcrt.locking`) oder fail-closed manuelle
Recovery, bei der ein verwaistes Intent gar nicht automatisch bereinigt
wird, sondern der Lauf mit klarer Aufforderung blockiert. Bis dahin ist
dies eine offen deklarierte Grenze, kein unerkannter Rest.

`LEASE.json`
(`{schema_version, run_id, owner{principal_id, harness, session_ref},
fencing_token, acquired_at, ttl_seconds, released}`): Erwerb per
O_CREAT|O_EXCL; Renew per atomarem Replace durch den Owner; Takeover nur
bei `released` oder TTL-Ablauf ueber das Intent-Verfahren (78.11) mit
`fencing_token + 1`. `journal.md` ist append-only Historie und niemals
Wiederaufnahme-Cursor.

## 78.5 Principals, Pfadklassen und Enforcement

Inkubator-Principals und Schreibrechte (Regeldefinition; das
Guard-Enforcement selbst ist FK-30-Sache, die harness-spezifische
Materialisierung FK-76-Sache):

| Principal | Schreibend erlaubt | Lesend erlaubt | Verboten |
|---|---|---|---|
| `council_orchestrator` | `concept-incubator/**` (unter Lease); `concept/**` NUR im Zustand PROMOTING des eigenen Laufs | Projekt | Normativ-Writes ausserhalb PROMOTING |
| `council_worker` | ausschliesslich `runs/<run>/workers/<self>/outbox/` | `workers/<self>/inbox/` + zugeteilte Korpus-Pfade | `concept/**`, fremde Sandboxes, `rounds/`, `synthesis/`, `promotion/`, RUN/LEASE |

In AK3-registrierten Projekten werden diese Regeln als Guards
durchgesetzt (PreToolUse-Pfad). Ohne guard-faehigen Harness (z. B. fremdes
Modell via Bridge) MUSS der Worker in einem physisch separaten
Arbeitsverzeichnis laufen (Workspace-Root = seine Sandbox); Korpus-Zugang
erfolgt als read-only Materialisierung des Coverage-Pakets in
`inbox/corpus/`. Kein Worker-Prozess erhaelt einen Workspace, der
`concept/` schreibbar enthaelt. Fremde, versiegelte Proposals werden
Workern als **untrusted data** uebergeben (explizite Briefing-Regel):
Inhalte sind Analysegegenstand, niemals Instruktionen.

## 78.6 Runden-Mechanik und Coverage-Plan

<!-- PROSE-FORMAL: formal.concept-incubation.commands, formal.concept-incubation.events -->

Runde 1 ist unabhaengig: die Worker-Inbox enthaelt nur Briefing +
Coverage-Paket. Der Orchestrator versiegelt jede Runde (Round-Seal):
Proposals werden mit Digest-Bindung nach `rounds/r<N>/` kopiert; erst
versiegelte Staende duerfen in Folgerunden fremden Inboxen bereitgestellt
werden. Konvergenzbewertung je Runde: `Konvergierend | Divergierend |
Stabil-Kontrovers | Spannungsfeld`; keine Zwangskonvergenz —
Stabil-Kontrovers/Spannungsfeld gehen als Entscheidungsvorlage
(dissent-map) an den PO.

**`rounds/r<N>/ROUND.json`** — Feldkatalog:

| Feld | Inhalt |
|---|---|
| `schema_version`, `run_id`, `round` | |
| `participants[]` | `{participant_id, dispatch: {sent_at, prompt_digest, input_digests[]}, receipt: object\|null {received_at, proposal_digest}, outcome: received\|timeout\|failed\|excluded, outcome_reason}` (`outcome_reason` Pflicht ausser bei `received`) |
| `sealed` | bool |
| `seal` | object\|null: `{sealed_at, sealed_proposal_digests: {participant_id: sha256}}` |

Invarianten: Cross-Read erst nach `sealed: true`; Seal-Digests entsprechen
den Dateien; genau ein `outcome` je Teilnehmer; Ausfaelle werden
dokumentiert entschieden (weiter ohne / Ersatz / Abbruch), nie still.

**`baseline/coverage-plan.json`** (FULL_ATOM-Pflicht, vor STAFFING
eingefroren) — Feldkatalog: `{schema_version, run_id, packages[]:
{package_id, description, paths[] (Glob relativ zu concept_roots),
assigned_participants[], redundancy >= 1}, integration_package_id}`.
Coverage-Matrix mechanisch: Vereinigung aller Paket-Aufloesungen plus
EXEMPT-Eintraege == Baseline-Menge; das Integrationspaket existiert;
deklarierte Redundanz ist erfuellt.

## 78.7 Quellen und Source-Units (zweistufiger Freeze)

<!-- PROSE-FORMAL: formal.concept-incubation.invariants -->

Quellen tragen `source_phase`:

- **`input`** — genau die Rollen `BRIEFING`, `PROPOSAL` und
  `PO_DECISION`: das Briefing, alle versiegelten Proposal-Fassungen aller
  Runden und die bis dahin vorliegenden PO-Inputs. Diese Menge ist
  mechanisch re-derivierbar (Briefing + Round-Seals + PO-Inputs) und wird
  vom Checker als exakte Mengengleichheit gegen das Register geprueft;
  andere Rollen (`SYNTHESIS`, `DISSENT_MAP`, `NORMATIVE_BASELINE`,
  `EVIDENCE`) sind niemals `input`. Der **Input-Freeze** erfolgt VOR
  SYNTHESIZING: `source-register.tsv` (Input-Zeilen), `source-units.tsv`
  (Input-Units) und `claims-inventory.tsv` (Input-Claims) werden
  digest-gepinnt (`register_digests.source_register_input` /
  `source_units_input` / `claims_inventory_input`) — als kanonische
  Subset-Digests (Header plus lexikographisch sortierte Zeilen der
  Teilmenge, LF-verbunden). Der Input-Freeze wird nie ueberschrieben.
- **`derived`** — Synthese-Staende, Dissent-Map, PO-Entscheidungen der
  DECIDING-Phase. Sie werden nach ihrer Entstehung als Quellen ergaenzt
  (`source_phase=derived`). Jede materielle Derived-Unit referenziert
  entweder Upstream-Claims (`claim_refs` auf Input-Claims) oder erzeugt
  einen neuen Claim im Derived-Anteil des Inventars, der VOR PROMOTING
  disponiert wird. Vor dem Eintritt in PROMOTING werden die
  Derived-Claims (`register_digests.derived_claims`) sowie der finale
  Quellen- und Unit-Stand (`source_register_final`,
  `source_units_final`) separat gepinnt; die Input-Freezes bleiben
  unveraendert bestehen.

**`baseline/source-intake.tsv`** (verkettetes Append-Log) — Spalten:
`intake_id` `source_phase` `role` `path` `sha256` `registered_at`
`prev_digest` `entry_digest`. Jede Quelle wird beim Eintreffen hier
festgehalten. `entry_digest` ist der SHA-256 ueber die kanonisch
serialisierten Feldwerte der Zeile **einschliesslich `prev_digest`**;
die erste Zeile traegt `prev_digest` = 64 Nullen. Der Kettenkopf wird
**ausserhalb** des Logs gepinnt, und zwar zweifach und jeweils
unveraenderlich: `source_intake_input_head` beim Input-Freeze,
`source_intake_final_head` vor dem Eintritt in PROMOTING (beide unter
Lease und Mutex geschrieben). Der Checker verifiziert Kettenintegritaet,
beide Head-Matches, die Mengengleichheit zwischen Intake und
`source-register.tsv` in beiden Richtungen und den **Praefix-Beweis**:
die finale Kette enthaelt die eingefrorene Input-Kette als
unveraenderten Praefix (es gibt ein k, sodass die ersten k Zeilen exakt
den Input-Head ergeben und alle spaeteren Zeilen `source_phase=derived`
tragen). Damit ist nachtraegliches Entfernen, Umsortieren oder
Einschieben einer Input-Zeile beweisbar ausgeschlossen — ein gemeinsames
Bereinigen von Intake, Quellenregister und Pin faellt auf, was mit frei
editierbaren Mengen oder einem einzelnen mitwandernden Head nicht
erkennbar waere.

Fuer `derived` gilt zusaetzlich die Mengengleichheit gegen die
kanonischen Lauf-Pfade mit **fester Rollenzuordnung**:
`synthesis/synthesis-r*.md` → `SYNTHESIS`, `synthesis/dissent-map.md` →
`DISSENT_MAP`, `synthesis/po-decision-<slug>.md` → `PO_DECISION`. Eine
existierende, aber nicht registrierte Synthese, Dissent-Map oder
PO-Entscheidung ist ERROR, ebenso eine abweichende Rolle — ein Weglassen
faellt damit auf.

**`baseline/source-register.tsv`** — Spalten: `source_id` `source_phase`
(`input|derived`) `role`
(`BRIEFING|PROPOSAL|SYNTHESIS|DISSENT_MAP|PO_DECISION|NORMATIVE_BASELINE|EVIDENCE`)
`path` `sha256` `round` (leer erlaubt) `participant_id` (leer erlaubt)
`author_principal_id` (leer erlaubt nur fuer Quellen ohne Agent-Autor)
`genealogy_parents` (Semikolon-Liste; leer nur fuer Primaerquellen).

**`baseline/source-units.tsv`** — Spalten: `unit_id` `source_id`
`unit_locator` (`<path>#<heading-path>` oder `<path>#L<a>-L<b>`)
`unit_digest` `claim_refs` (Semikolon; leer NUR wenn `empty_reason`
gesetzt) `empty_reason`
(`NO_MATERIAL_CONTENT|DUPLICATE_OF:<unit_id>|OUT_OF_SCOPE:<grund>`; leer
wenn `claim_refs` gesetzt).

**Unit-Partition (deterministisch, von `semantic_gate.py units` erzeugt
und vom Checker re-deriviert):** Eine Markdown-Quelle wird in
nicht-ueberlappende Bloecke partitioniert: (1) Praeambel vor der ersten
Ueberschrift ist eine eigene Unit, falls nicht leer; (2) jede ATX- oder
Setext-Ueberschrift beliebiger Ebene beginnt eine neue Unit, die bis
unmittelbar vor die naechste Ueberschrift reicht; (3) Ueberschriften
innerhalb von Code-Fences zaehlen nicht; (4) bei gleichnamigen
Ueberschriften wird der Heading-Path mit laufender Nummer disambiguiert
(`#abschnitt-2`); (5) Nicht-Markdown-Quellen werden in Absatzbloecke
(Leerzeilen-getrennt) partitioniert. Die Partition ist vollstaendig und
ueberlappungsfrei; der Checker vergleicht re-derivierte Unit-Digests mit
dem Register — manuelles Ausduennen ist damit ausgeschlossen.

## 78.8 Claim-Verfahren und Coverage-Abschluss

<!-- PROSE-FORMAL: formal.concept-incubation.invariants -->

**Phase A — `synthesis/claims-inventory.tsv`** (Gate fuer SYNTHESIZING):
Spalten `claim_id` `source_id` `unit_refs` (>=1) `source_locator`
`statement` (qualifikatorentreu) `qualifiers` (leer erlaubt)
`genealogy_parents` (leer erlaubt). **Inventar-Closure**: jede Input-Unit
traegt `claim_refs` oder `empty_reason`; Mengenassertionen
`units == claims-or-empty`; Digest gepinnt. Es gibt keine pauschalen
Quell-EMPTYs und keine Pseudo-Claims.

**Phase B — `synthesis/disposition-ledger.tsv`** (Gate fuer PROMOTING):
Spalten `claim_id` `synthesis_disposition`
(`ADOPTED|MERGED|SUPERSEDED_BY_CLAIM|REJECTED_WITH_REASON|OPEN_QUESTION`)
`disposition_reason` (Pflicht ausser ADOPTED) `residual_edge`
(`CHECKED_AGAINST_CURRENT|ESCALATED_TO_PO|NONE_REQUIRED:<klasse>`; Pflicht
fuer nicht ADOPTED/MERGED; Minderheitspositionen der letzten Runde nie
`NONE_REQUIRED`) `atom_refs` (Pflicht bei ADOPTED/MERGED) `finding_refs`
(leer erlaubt). Closure: genau eine Zeile je Inventar-Claim; zusaetzlich
sind alle Derived-Claims (78.7) disponiert.

**Coverage-Register** (final vor Verlassen von PROMOTING):

- `baseline/source-coverage.tsv`: `source_id` `sha256` `review_status`
  (`PASS|PASS_WITH_GAPS|FAIL|N_A`) `review_artifact` (Pfad; bei `N_A`
  stattdessen `N_A:<begruendung>`) `reviewer_principal_id` `finding_refs`
  (Pflicht bei PASS_WITH_GAPS/FAIL). Genau eine finale Zeile je Quelle;
  der Reviewer ist nicht der `author_principal_id` der Quelle; `N_A` ohne
  Begruendung ist ERROR.
- `baseline/normative-coverage.tsv`: `path` `baseline_sha256`
  (leer erlaubt fuer `added`) `current_sha256` (leer erlaubt fuer
  `removed`) `change_kind` (`unchanged|modified|added|removed`)
  `review_status` `review_artifact` `reviewer_principal_id`
  `finding_refs`. Abdeckungsmenge ist `baseline ∪ current` der
  Konzept-Wurzeln (FULL_ATOM: vollstaendig; LIGHT: beruehrte Dateien).

## 78.9 Atomisierung, Dispositionen, Findings

`promotion/atom-register.tsv` — Spalten: `atom_id` `statement`
`atom_type`
(`REQUIREMENT|DOMAIN_FACT|DECISION|RATIONALE|EVIDENCE|PARAMETER_CANDIDATE|REJECTION|OPEN_QUESTION`)
`qualifiers` (leer erlaubt) `normative_status`
(`proposal|accepted|evidence|rejected|open`) `expected_authority`
(scope_id; Ziel-Reihenfolge: Decision Record → Domain-Doc → FK → Formal →
Registry → Guardrail) `target_refs` (Semikolon `<path>#<anchor>`; >=2 bei
COVERED_SPLIT — Teilziele einzeln, kein Qualifikator faellt zwischen die
Ziele) `disposition`
(`COVERED_EXACT|COVERED_SPLIT|REJECTED|OPEN_MISSING|DEFERRED_BACKLOG|EVIDENCE_ONLY|OUT_OF_AUDIT|SUPERSEDED`)
`deferral` (`owner=<x>;trigger=<y>;anchor=<path#anchor>`; Pflicht bei
DEFERRED_BACKLOG) `claim_refs` (>=1) `receipt_refs` (Pflicht bei
COVERED_*).

`findings.tsv` — dedupliziertes Befundregister des Laufs: `finding_id`
`severity` (`P0|P1|P2`) `status` (`open|resolved|accepted_by_po`)
`claim_refs` (leer erlaubt) `atom_refs` (leer erlaubt) `path` `locator`
`statement` `resolution` (Pflicht bei `resolved`/`accepted_by_po`).
Regeln: `review_status` PASS_WITH_GAPS/FAIL in den Coverage-Registern
verlangt `finding_refs`; **offene Findings blockieren die Promotion**
(`promotion_disposition` der betroffenen Scopes bleibt `deferred` oder der
Lauf geht nach PROMOTION_FAILED).

## 78.10 Projection-Receipts und Reverse Trace

`promotion/receipts/<receipt_id>.json` — Feldkatalog: `{schema_version,
receipt_id, atom_id, target: {path, anchor, target_mode, selector},
source_digest (Atom-Statement), target_section_digest (Digest gemaess
`target_mode`, §78.12), writer_principal_id, writer_session_ref,
reviewer_principal_id, reviewer_session_ref, verdict:
equivalent|disagrees, reviewed_at}`. `target_mode` und `selector` sind
Pflichtfelder des Receipts — es gibt keinen impliziten Default; ein
Receipt, dessen Modus vom geforderten abweicht, wird abgewiesen (sonst
waeren Ganzdatei-, Struktur- und Verzeichnisziele nur scheinbar belegt).
`anchor` ist bei `markdown-section` Pflicht und bei `whole-file` bzw.
`directory-tree` unzulaessig.

Unabhaengigkeitsregel: `reviewer_principal_id != writer_principal_id` UND
`reviewer_session_ref != writer_session_ref` — Verstoss ist ERROR.
`disagrees` erzeugt einen Scope-Blocker mit PO-Eskalation; ein Override
durch den Writer ist verboten.

**Diff-Hunk-Reverse-Trace:** Der Promotion-Checker berechnet alle
Diff-Hunks zwischen Baseline und Current unter den Konzept-Wurzeln, ordnet
jeden nicht-formatalen Hunk (Format-only nach dem
`Concept-Format-Only`-Kriterium) dem kleinsten umschliessenden
Ueberschriftsanker **beliebiger Ebene** zu und verlangt Deckung durch
mindestens ein Receipt-/Atom-`target_ref` auf diesem Anker oder einem
Vorfahren-Anker derselben Datei. Ungedeckte Hunks sind ERROR — nichts wird
eingeschmuggelt.

## 78.11 Promotion-Manifest, Scope-Locks und Closure

<!-- PROSE-FORMAL: formal.concept-incubation.invariants, formal.concept-incubation.scenarios -->

**`promotion/promotion-manifest.json`** — Feldkatalog: `{schema_version,
run_id, base_revision, scopes[]: {scope_id, promotion_disposition:
promoted|rejected|deferred, blockers[]: {reason, atom_ids[], owner,
visible_anchor}}, required_decision_ids[], required_concept_ids[],
required_formal_ids[], required_registry_edges[]: {from, to, kind},
required_support_paths[], required_test_oracles[]: {oracle_id, kind,
locator}, targets[]: {path, before_sha256|null, after_sha256},
receipts_dir, scope_locks[]: {scope_id, locked_by_run, fencing_token,
backend}, semantic_gates[]: {gate: authority-prose|scope-consistency,
status: passed|blocked|not_run, receipt_path|null, blocking_scope_ids[]}}`.

**Registry-Kanten-Semantik** (`required_registry_edges[].kind`): Die
Kante muss die konkrete Beziehung im Graphen nachweisen, nicht nur die
Existenz beider Endpunkte. `owns` wird gegen `authority_over` des
Quelldokuments geprueft, `defers_to` gegen dessen
Frontmatter-`defers_to`-Kanten, `contract` und `member` gegen die
`contract_docs`/`member_docs` der Domain-Registry, `producer` gegen den
`producer` des formalen Event-Objekts. Eine Kante
`{from: <event_id>, to: <concept_id>, kind: consumer}` ist in v1 genau
dann erfuellt, wenn `<event_id>` in einem formalen Event-Set
`<object_id>` existiert, `<concept_id>` ein Konzeptdokument bezeichnet
und dessen `formal_refs` `<object_id>` enthaelt. Sie belegt
ausschliesslich die vertragliche Bindung an das Event-Set, **nicht** die
Verarbeitung des einzelnen Events; ereignisspezifischer Konsum
erforderte eine explizite `consumes_events`-Relation und darf aus
`formal_refs` nicht abgeleitet werden.

**Lock-Datei-Feldkatalog** (beide Backends, identischer JSON-Blob):
`{schema_version, scope_id (original, unnormalisiert), locked_by_run
(run_id), fencing_token (int), backend: filesystem|git-remote,
acquired_at (UTC-ISO), ttl_seconds (int)}` — ein Template liegt im
Skill-Bundle (`templates/scope-lock.json`).

**Scope-Locks — zwei normierte Backends** (`lock_backend`):

- `filesystem` (gemeinsames Dateisystem):
  `locks/<normalized_scope_id>.<scope_hash8>.lock.json`
  (`scope_hash8 = sha256(scope_id)[:8]`; Normalisierung: lowercase,
  `[._-]+` → `-`). Erwerb O_CREAT|O_EXCL. Renew: atomarer Replace durch
  den Owner-Lauf. Takeover NUR bei TTL-Ablauf ueber Intent-Verfahren:
  (1) `<lockname>.takeover` per O_EXCL anlegen, (2) Lock erneut lesen und
  Ablauf verifizieren, (3) Replace mit `fencing_token + 1`, (4) Intent
  loeschen; verwaiste Intents verfallen nach der Lock-TTL. **Release nur
  nach Owner-/Token-Recheck unter demselben Intent-/Mutex-Verfahren** —
  ein stale Owner darf einen uebernommenen Lock nicht loeschen.
- `git-remote` (verteilt, ohne gemeinsames FS): Lock als Remote-Ref
  `refs/concept-locks/<scope_hash>` mit identischem JSON-Blob; Erwerb per
  Create-only-Push (CAS gegen Zero-OID); Renew/Takeover per Push mit
  erwarteter Old-OID; **Release ausschliesslich per CAS gegen die
  erwartete Ref-OID**. Keine Lock-Dateien im Worktree. Der (netzlose)
  Promotion-Checker verifiziert dieses Backend ueber eine vom
  Orchestrator beigebrachte Evidenzdatei
  `promotion/lock-evidence.json` (`{schema_version, backend:
  "git-remote", remote, refs[]: {scope_id, ref, expected_ref,
  observed_oid, old_oid, new_oid, lock_blob_digest, fencing_token,
  ttl_seconds, acquired_at, attested_by_principal, attested_by_session,
  verified_at}}`; das erwartete Remote stammt aus
  `concept-governance.json` (`lock_remote`, bei diesem Backend Pflicht).
  Geprueft werden **zwei getrennte Fristen** plus die vollstaendige
  Zeitordnung: die **Lock-Lebendigkeit** (`acquired_at + ttl_seconds`
  liegt in der Zukunft), die **Evidenz-Alterung** (`verified_at` nicht
  aelter als `ttl_seconds`) sowie
  `acquired_at <= verified_at <= jetzt + Clock-Skew` und
  `verified_at <= acquired_at + ttl_seconds`. Ohne die
  Ordnungspruefungen waeren beliebig weit in der Zukunft liegende
  Zeitstempel fail-open, weil "noch nicht abgelaufen" dann trivial
  erfuellt ist. Der Clock-Skew ist eine benannte Konstante (300 s,
  uebliche NTP-Fleet-Toleranz), weil die Attestierung von einem anderen
  Host stammt; ein Zeit-Fallback existiert nicht;
  ohne gueltige Evidenz endet der Lock-Teilcheck als deklarierter
  INCOMPLETE-Lauf, niemals als stilles PASS. Die Evidenz bindet
  zusaetzlich `remote`, `expected_ref`, `observed_oid`,
  `lock_blob_digest`, `fencing_token`, den attestierenden Principal samt
  Session und ein Frische-Fenster (`verified_at` innerhalb der Lock-TTL).
  Der **Lock-Blob-Digest** ist definiert als SHA-256 ueber die kanonische
  Serialisierung von `scope_id`, `locked_by_run`, `fencing_token`,
  `backend`, `ttl_seconds` und `acquired_at`. Die beiden Zeitfelder sind
  mitgebunden, weil die Evidenz sonst eine Lock-Lebensdauer behaupten
  koennte, die der attestierte Blob nicht traegt.

Lock-Besitz wird beim PROMOTING-Eintritt erworben, im Manifest
festgehalten und **unmittelbar vor der finalen Landung erneut
verifiziert**; gleichzeitig wird geprueft, dass das Ziel noch auf der
erwarteten `base_revision` steht (sonst RECHECK). Ein normativer Scope ist
zeitgleich hoechstens von einem Lauf im Zustand PROMOTING gebunden.

**Lock-Lifecycle:** Locks bleiben ueber PROMOTION_FAILED, RECHECK und
BLOCKED hinweg gehalten (der Lauf ist weiterhin Eigentuemer der
Promotion). Freigegeben werden sie ausschliesslich als **untrennbarer
Bestandteil** von `complete-promotion` bzw. `abort-run` — es gibt keinen
separat aufrufbaren Release — beim Uebergang nach CLOSED
oder ABORTED — Release nur nach Owner-/Token-Recheck (filesystem) bzw.
per Ref-CAS gegen die erwartete Old-OID (git-remote); ein stale Owner
kann einen uebernommenen Lock nicht freigeben.

**Promotion-Closure** (`check.py promotion`; alle Regeln ERROR-only):

1. Jedes `accepted`-Atom hat genau eine Disposition; COVERED_* verlangt
   Receipts mit `equivalent` und Digest-Match (Atom-Statement +
   Ist-Sektion).
2. `targets[]`-Digests stimmen (before == Baseline, after == Ist; `null`
   nur fuer neue Dateien).
3. Diff-Hunk-Reverse-Trace (78.10) ist vollstaendig gedeckt.
4. Alle `required_*`-Eintraege existieren und loesen auf.
5. `promotion_disposition = promoted` nur wenn: keine Blocker, keine
   OPEN_MISSING-/DEFERRED_BACKLOG-Atome im Scope, `semantic_gates` fuer
   den Scope `passed`, Lock gehalten (Re-Check), Coverage-Register final,
   offene Findings = 0, `register_digests` in RUN konsistent.
6. `deferred` verlangt Blocker mit `visible_anchor` und Owner;
   `rejected` dokumentiert die verworfene Alternative.
7. Teillaeufe enden mit Exit 2 und `INCOMPLETE_CHECK_SET` samt Liste der
   gelaufenen Checks; niemals mit einem Clean-Receipt.

## 78.12 Korpusweites Projektionsmanifest

<!-- PROSE-FORMAL: formal.concept-incubation.invariants -->

**`concept/_meta/projection-manifest.json`** ist der korpusweite Traeger
von `assertion_status` und `equivalence_status`. Feldkatalog:
`{schema_version, entries[]: {scope_id, covered_scope_ids[] (optional;
disjunkte Scope-Gruppe, deren Vereinigung mit allen scope_id-Eintraegen
exakt die Authority-Scopes des Korpus-Deltas deckt), lifecycle:
current|draft|deprecated|superseded, lifecycle_source: {decision_id,
path, digest, status} — das referenzierte Decision Record traegt dazu im
Frontmatter das maschinenlesbare Pflichtfeld `decision_status:
proposed|accepted|rejected|superseded`, gegen das der Checker prueft,
assertion_source: {path, digest — non-null vor
jeder Landung}, assertion_status, required_projections[]: {kind:
formal|prose|registry|support|test-oracle, target, target_mode:
markdown-section|whole-file|structured-selector|directory-tree,
selector (Pflicht bei structured-selector), target_digest|null,
receipt_ref|null, equivalence_status}, blockers[]: {reason, owner,
visible_anchor — stabiler Abschnittsanker, nie blosser Dateipfad},
last_run_id|null, last_promotion_manifest: object|null {path, digest}}}`.

**Target-Modi.** Jede Pflichtprojektion deklariert, wie ihr Ziel
digestiert wird — nur so sind auch Registries, JSON-Konfigurationen und
Verzeichnisse belegbar:

| `target_mode` | Ziel | Digest-Regel |
|---|---|---|
| `markdown-section` | `<pfad>#<anker>` | SHA-256 des LF-kanonisierten Abschnittstexts |
| `whole-file` | Datei (auch JSON/YAML) | SHA-256 der Dateibytes |
| `structured-selector` | Teilbaum einer JSON-/SMY-Datei, adressiert ueber `selector` (`<key>` oder `<key>[<idfeld>=<wert>]`) | SHA-256 der kanonischen Serialisierung des Teilbaums |
| `directory-tree` | Verzeichnis | SHA-256 der sortierten Liste `relpfad<TAB>dateidigest` aller nicht ignorierten Dateien |

Eine Projektion mit `equivalence_status: equivalent` traegt in jedem
Modus einen non-null `target_digest`; Verzeichnis- und Strukturziele sind
damit gleichberechtigt receiptable.

Selbstbezug: Das Manifest ist der **Traeger** des Status, nicht selbst
eine Pflichtprojektion des Scopes, dessen Status es fuehrt — ein Eintrag
listet sich daher nicht selbst auf. Referenziert ein Eintrag
ausnahmsweise das Manifest als Ziel eines *anderen* Scopes, bezieht sich
`target_digest` auf den **kanonischen Entry-Digest** (SHA-256 des
kanonisch serialisierten Eintrags ohne abgeleitete Statusfelder und ohne
das eigene Digest-Feld), niemals auf den Digest der gesamten
Manifestdatei — ein Ganzdatei-Digest waere selbstreferenziell und nie
erfuellbar.

Die Statussemantik und die Ableitungsregeln (Lifecycle-first,
disagreement blocks, Ableitung von `equivalence_status` und
`assertion_status`) besitzt der Assertion-Vertrag
(`concept/_meta/assertion-authority.md` §3–§4); die maschinenpruefbare
Fassung liegt in den formalen Invarianten
(formal.concept-incubation.invariants: projection_lifecycle_first,
projection_status_derivation). FK-78 wiederholt sie nicht. Die
deklarierten `required_projections` sind normative Eingaben (Pflege ueber
Promotionen/Decision Records); die abgeleiteten Statusfelder sind
verifier-geprüfte Materialisierungen, keine unabhaengige Autoritaet.
`check.py projection` prueft das Manifest gegen den Ist-Korpus.

## 78.13 Datenklassen, Artefakt-Register, Declassification

Datenklassen: `open | internal | sensitive`; unklassifiziert zaehlt als
`sensitive` (fail-closed, auch als Konfigurations-Default).
**`artifact-register.tsv`** ist ab dem Zustand FRAMING Pflicht
(`findings.tsv` spaetestens ab PROMOTING; leer mit Header ist zulaessig);
nur das lokale Overlay `artifact-register.local.tsv` ist optional — ein
fehlendes Hauptregister waere sonst ein Weg, das Klassifikations-Gate
durch Weglassen zu umgehen. Spalten: `path` `sha256` `artifact_kind`
(`briefing|proposal|synthesis|dissent_map|inventory|ledger|atom_register|manifest|receipt|round_state|coverage|finding|journal|other`)
`input_refs` (Semikolon-Liste **typisierter** Referenzen
`source:<source_id>` oder `artifact:<path>`; leer erlaubt fuer Wurzeln;
der Provenienzgraph ist azyklisch — Zyklen sind ERROR) `declared_class`
`effective_class` `vcs_disposition` (`versioned|local`)
`declassification_receipt` (Pfad; leer erlaubt).

Regeln: `effective_class` = Maximum aus `declared_class` und den
`effective_class`-Werten aller `input_refs`; ein digest-gebundenes
Declassification-Receipt ueberschreibt die Max-Regel fuer GENAU das
referenzierte Output-Artefakt. `effective_class = sensitive` erzwingt
`vcs_disposition = local`; das Commit-Gate (`check.py incubator`)
blockiert Verstoesse. Enthaelt das Register selbst sensible Pfade oder
Digests, wird ein zweigeteiltes Register gefuehrt: das versionierte
Register traegt nur sanitisierte Eintraege, ein lokales Overlay
(`artifact-register.local.tsv`, ignoriert) die sensiblen Zeilen; die
Toolchain prueft die Vereinigung.

`declassification/<receipt_id>.json`: `{schema_version, receipt_id,
source_path, source_digest, output_path, output_digest, rules_applied[],
target_class: open|internal, approved_by_principal, approved_at}`.

Data-Release je Teilnehmer (78.4) referenziert konkrete `source_ids` /
`package_ids` plus `max_data_class` und ist vom User bestaetigt; `sensitive`
verlaesst die Maschine nicht ohne explizite PO-Freigabe je Backend.

## 78.14 Deploybare Concept-Toolchain

**Ort und SSOT:** `tools/agentkit/concept_toolchain/` im Zielprojekt
(Quelle: `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/`).
Die Toolchain ist die **einzige ausgelieferte Implementierung der
generischen Konzept-Gates** und damit die Wahrheitsquelle fuer
Zielprojekte. Python stdlib-only als bewusster Standalone-Vertrag (kein
venv im Zielprojekt vorausgesetzt).

**Verhaeltnis zu AK3s eigenen Gates (Uebergangsstand, ehrlich
deklariert):** AK3 betreibt fuer die eigene Konzeptwelt weiterhin
`scripts/ci/check_concept_*` auf Basis von `tools/concept_compiler`/
`tools/concept_governance` — ein gewachsenes Subsystem mit eigener
Testabdeckung, das ueber die generischen Regeln hinaus AK3-Spezifika
erzwingt (Index-Vollstaendigkeit, Tag-Korpus, Modul-/Domain-/
Policy-Registry, Bounded-Context-Lints L17–L20,
Architecture-Conformance, Hub-Batch-Betrieb fuer W2/W3). Solange die
Wrapper-Migration (§78.17) nicht ausgefuehrt ist, existieren fuer die
*gemeinsamen* generischen Regeln zwei Implementierungen. Das Risiko
stiller Divergenz wird uebergangsweise dadurch begrenzt, dass die
gebundelte Engine im AK3-CI verpflichtend gegen den echten AK3-Korpus
laeuft (Selfcheck-Integrationstest): jede generische Regelverletzung im
Korpus muss auch von der Engine erkannt werden. Diese Doppelung ist ein
bewusster, **triggergebundener** Uebergangszustand (Trigger und
Closure-Nachweis: Decision Record
`2026-07-19-concept-incubation-support` §2 Nr. 4), keine Dauerloesung.

**SMY (Structured Metadata YAML Subset):** Die Toolchain parst
Frontmatter und Formal-Spec-Zonen mit einem eigenen Parser fuer genau
dieses Subset: Block-Mappings, Block-Sequenzen, Plain-/Quoted-Skalare,
Folded-`>`-Skalare, Kommentare, einfache Flow-Listen (`[a, b]`). NICHT
unterstuetzt und fail-closed ERROR mit Zeilenangabe: Anchors, Aliases,
Tags, Multi-Doc, komplexe Flow-Styles. Der bestehende Korpus liegt in
diesem Subset.

**Validator-Vertrag:** Die Feldkataloge dieses Kapitels sind als
Validator-Code implementiert; die im Bundle mitgelieferten
JSON-Schema-Dateien sind dokumentierende Artefakte, die per Contract-Test
ueber kanonische Fixtures mit dem Code deckungsgleich gehalten werden.

**CLI-Vertrag:**

- `check.py` — **strikt read-only**: `frontmatter | references | formal |
  decision-gate --base <rev> | incubator <run-dir> | promotion <run-dir> |
  projection | semantic-status <run-dir> | all [--run <run-dir>]`.
- `semantic_gate.py` — **mutierend**, nur unter gueltiger Lease und
  Mutations-Mutex, atomare Writes, Idempotency-Key = Request-Digest.
  Jeder Subcommand verlangt die Schreiber-Identitaet, gegen die Lease und
  RUN-Zustand geprueft werden:
  `units <run-dir> --principal <id> --session <ref> --fencing-token <n>`
  (Source-Units derivieren),
  `prepare <run-dir> --gate w2|w3 --principal … --session … --fencing-token …`
  (Request-Packs, digestadressiert, nie ueberschreibend),
  `import <run-dir> <receipt-file> --principal … --session … --fencing-token …`
  (Semantik-Receipts validieren und registrieren). Fehlende Parameter
  enden mit Exit 3.
- Exit-Codes (beide): `0` PASS; `1` Befunde (ERROR); `2` fehlende
  Voraussetzungen bzw. deklarierter INCOMPLETE-Teillauf; `3` Usage-/
  Konfigurationsfehler. Exit 2 gilt nie fuer einen vollstaendig
  gelaufenen Einzel-Check.
- `--json`-Envelope: `{schema_version, command, check_set[], complete,
  findings[]: {check_id, severity: "ERROR", path, locator, message}}`.

**Semantik-Gates (W2 Authority-Prose, W3 Scope-Consistency):**
LLM-Bewertungen mit deterministischer Verrechnung — niemals als
deterministisch etikettiert. `prepare` erzeugt je Scope ein
**Request-Pack**: `{schema_version, gate, scope_id, base_revision,
template_id, template_digest, chunks[]: {path, locator, digest}
(geordnet), request_digest}`. Die LLM-Ausfuehrung uebernimmt der
Agent/Hub. `import` validiert ein **Semantik-Receipt**:
`{schema_version, gate, request_digest, model, principal_id, session_ref,
status: passed|failed, findings[]: {finding_id, chunk_path, chunk_locator,
scope_id, statement, severity: "ERROR"}, chunk_digests[], completed_at}` —
inklusive vollstaendiger Chunk-Digest-Rueckbindung an das Request-Pack.
`check.py semantic-status` verrechnet die Receipts je Scope: fehlender
LLM-Zugang oder unvollstaendiger Sweep ⇒ betroffene Scopes
`blocked_projection`; niemals stilles PASS.

## 78.15 Skill-Auslieferung

Ein Skill-Bundle `concept-incubation-core` (FK-43-Format, Profil CORE,
keine Binder-Aenderung): kanonische Root-`SKILL.md` mit **Rollen-Gate**
(erste Klaerung: Council-Orchestrator oder Gremiums-Worker) und
**Harness-Selbsterkennung** (Claude Code → `references/claude-code.md`;
Codex → `references/codex.md`); `references/process-core.md`
(single-source Prozesswissen), `references/participant-briefing.md`
(Worker-Briefing-Template inkl. untrusted-data-Regel); `templates/` mit
Startartefakten (RUN.json, LEASE.json, ROUND.json, TSV-Header,
promotion-manifest.json, projection-manifest.json, briefing.md, INDEX.md,
concept-governance.json, .gitignore-Fragmente). Der Skill fuehrt durch:
Profilwahl, Besetzungsfrage an den User (niemals stille
Default-Besetzung), Spawn-/Resume-Mechanik je Harness (FK-76;
Harness-Bridge, LLM-Hub, Sub-Agenten, CLI-Resume), Lease-/State-/
Lock-Disziplin, Datenklassen-Abfrage, Runden mit Round-Seal, Konvergenz,
Synthese, PO-Eskalation, Promotion mit Checker-Gates, Initialerstellung
des Blueprints; Umgang mit BLOCKED/RECHECK/PROMOTION_FAILED. Eine
harness-spezifische Materialisierungs-Achse im Binder ist erst noetig,
wenn harte Format-Divergenzen auftreten (deklarierte Folge-Story;
FK-43 §43.4.1).

## 78.16 Proportionalitaet

| Profil | Trigger | Pflichten |
|---|---|---|
| `DIRECT_GOVERNED_CHANGE` | kleiner, eindeutiger Single-Scope-Gehalt; kein ATOM-Trigger | kein Council, kein Lauf-Zwang; Decision Record + Betroffenheitsmatrix + alle deterministischen Gates |
| `LIGHT_INCUBATION` | echte inhaltliche Unsicherheit, begrenzter Scope | 1–2 Worker, >=1 Runde, Claim-Verfahren, Coverage nur fuer beruehrte Dateien, Promotion-Closure |
| `FULL_ATOM` | ATOM-Trigger: Migration/Synthese in die Normwelt; Verlustfreiheits-/Vollstaendigkeitsanspruch; mehrere Autoritaeten oder Prosa+Formal gemeinsam; Dokumentfamilien-Ersatz/-Split; BC-/Ownership-/Lifecycle-Schnittverschiebung; PO-Auftrag | volles Verfahren inkl. Coverage-Plan, vollstaendiger Coverage-Register und Drift-Recheck |

Bagatellen (`Concept-Format-Only`-Kriterium) sind inkubator- und
decision-record-frei, bleiben aber durch alle anwendbaren
deterministischen Konzept-Gates geprueft. Es gibt keinen gate-freien Pfad
in die normative Welt.

## 78.17 Scope-Grenzen und Folge-Stories

In v1 enthalten: die deploybare Toolchain, das Skill-Bundle, die
Konzeptdokumente inkl. Formal-Kontext und das AK3-eigene
Projektionsmanifest (initial fuer die concept-incubation-Scopes).

Deklarierte Folge-Stories:

1. **SSOT-Wrapper-Migration** — `scripts/ci/check_concept_*` werden fuer
   die generischen Regeln duenne Wrapper der gebundelten Engine; die
   AK3-Spezifika bleiben lokal. Bewusst nicht in v1: das AK3-Tooling ist
   ein gewachsenes Subsystem mit eigener Testabdeckung, dessen
   Umverdrahtung ein eigenes, testgetriebenes Vorhaben mit Ist-/
   Soll-Ausgabevergleich braucht. *Owner, Trigger und Closure-Nachweis*
   sind im Decision Record `2026-07-19-concept-incubation-support` §2
   Nr. 4 verbindlich festgehalten; Interimsschutz ist der
   verpflichtende Engine-Selfcheck gegen den AK3-Korpus (§78.14).
2. Harness-Variant-Achse im Skill-Binder (nur bei harter
   Format-Divergenz; FK-43 §43.4.1).
3. Hub-Batch-Komfort fuer W2/W3 in Zielprojekten.
4. Schrittgenaue Command→Transition-Bindung im Konzept-Compiler
   (heute erreichbarkeitsbasierte Szenarienpruefung).
5. KPI-/Telemetrie-Anbindung und Backend-/Control-Plane-Sicht auf
   Inkubationslaeufe.
