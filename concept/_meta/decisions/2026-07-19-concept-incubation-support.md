---
concept_id: META-DEC-2026-07-19-CONCEPT-INCUBATION-SUPPORT
title: Concept-Decision-Record — Konzeptions-Support (Concept-Incubation)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
decision_status: accepted
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-incubation, conception, blueprint, toolchain]
formal_scope: prose-only
---

# Concept-Decision-Record — Konzeptions-Support (Concept-Incubation)

Datum: 2026-07-19. Record gemaess META-CONCEPT-CONSISTENCY P3 und W4.
Herkunft: PO-Auftrag (muendlich) plus Gruendungslauf
`concept-incubator/runs/2026-07-19-conception-support-b4a7d375/`
(Design v4 nach vier adversarialen Codex-Reviews; PO-Entscheidungen Q1–Q4).

## 1. Anlass

AK3 unterstuetzte die der Story-Welt vorgelagerte Konzeptionsphase nicht.
Das Nachbarprojekt Intima hat fuer die Grossentwicklung von Konzeptwelten
belastbare Verfahren etabliert (ATOM-Methodik, Assertion-Authority,
gelebter Multi-Modell-Inkubator), die AK3 als Prozess-Framework normativ
uebernehmen und produktisieren soll — ausdruecklich via Skills und
deploybarer Toolchain, nicht via Backend-Orchestrierung.

## 2. Entscheidung

1. **Neue Saeule und neuer BC `concept-incubation`** (DK-16, FK-78,
   formal-spec `concept-incubation/`): Blueprint-Struktur der Konzeptwelt,
   Concept-Incubator als einziger Ort konzeptioneller Grossarbeit
   (Top-Level `concept-incubator/`), zwei Rollen (Council-Orchestrator als
   dritter Work-Mode in CLAUDE.md; Gremiums-Worker mit technisch
   erzwungenen Schreibgrenzen), Besetzung stets per User-Entscheid.
2. **Verlustfreie Promotion**: zweistufiger Source-Freeze (input/derived),
   tool-derivierte Source-Units mit Digest-Recheck, Claim-Inventar vor
   Synthese, Dispositions-Ledger mit Restkanten, Atomregister,
   unabhaengige Projection-Receipts (Writer ≠ Reviewer in Principal UND
   Session), Diff-Hunk-Reverse-Trace, Coverage-Register, Scope-Locks mit
   zwei Backends (filesystem-CAS, git-remote-Ref-CAS), Lease + CAS-
   Schreibprotokoll auf RUN.json.
3. **Assertion-/Projection-Vertrag** (`concept/_meta/assertion-authority.md`)
   ersetzt die pauschale Meta-Contract-Regel "formal wins" durch
   "disagreement blocks"; korpusweiter Traeger ist
   `concept/_meta/projection-manifest.json` (Lifecycle-Vorrangregel,
   deterministische Statusableitung). `concept/` bleibt Markdown-only mit
   enger Ausnahme fuer schema-validierte `_meta`-Registries.
4. **Deploybare Concept-Toolchain** (PO-Q1: voller Stack) unter
   `bundles/target_project/tools/agentkit/concept_toolchain/` als
   ausgelieferte Wahrheitsquelle der generischen Konzept-Gates fuer
   Zielprojekte (stdlib-only, SMY-Subset-Parser, CLI-Split `check.py`
   read-only / `semantic_gate.py` mutierend mit Schreiber-Identitaet,
   Exit-Code- und JSON-Envelope-Vertrag).
   **Scope-Entscheidung zur AK3-internen Migration:** AK3s eigene
   `scripts/ci/`-Gates bleiben in diesem Vorhaben unveraendert; ihre
   Umstellung auf duenne Wrapper der gebundelten Engine ist eine
   ausdruecklich angenommene, verfolgbare Folgearbeit — nicht ein
   stillschweigend offener Rest.
   *Owner:* AK3-Konzept-Toolchain-Verantwortlicher (aktuell der
   Council-Orchestrator des Gruendungslaufs).
   *Trigger:* die naechste Aenderung an einer der generischen Regeln
   (Frontmatter-/Authority-, Referenz-, Formal-Struktur- oder
   Decision-Record-Regel) — sie MUSS ab dann in der Engine erfolgen und
   den Wrapper nachziehen, statt die Regel ein zweites Mal zu
   implementieren.
   *Closure-Nachweis:* `scripts/ci/check_concept_*` enthalten keine
   eigene Implementierung einer generischen Regel mehr; der bestehende
   Engine-Selfcheck gegen den AK3-Korpus bleibt Pflichtgate.
   *Interimsrisiko (bewusst getragen):* bis dahin existieren fuer die
   gemeinsamen Regeln zwei Implementierungen; der Selfcheck beweist,
   dass die Engine den realen Korpus korrekt bewertet, aber keine
   vollstaendige Verhaltensaequivalenz beider Implementierungen.
5. **Skill-Bundle `concept-incubation-core`** (PO-Q4: ein Skill mit
   Rollen-Gate; Root-SKILL.md mit Harness-Selbsterkennung Claude
   Code/Codex, shared references + templates), FK-43-konform ohne
   Binder-Aenderung.
6. **Datenklassen-Policy** (PO-Q2 verfeinert): klassenbasierte
   VCS-Disposition mit Vererbung, unklassifiziert = sensitive,
   Declassification nur per digest-gebundenem Receipt.
7. **Proportionalitaet**: Profile DIRECT_GOVERNED_CHANGE /
   LIGHT_INCUBATION / FULL_ATOM mit ATOM-Trigger-Bindung; Bagatellen
   bleiben record-frei, aber niemals gate-frei.

## 3. Alternativen

- **Backend-/Control-Plane-Implementierung des Inkubators** — verworfen:
  PO-Direktive verlangt Skills + Dateisystem + deterministische Checks;
  ein Backend-Ausbau ist deklarierte Folge-Option, kein v1-Bestandteil.
- **Nur-Synthese-Atomisierung** (v1-Design) — verworfen nach Review 1/3:
  Verlust vor der Atomisierung waere unerkennbar; daher Source-Units +
  Claim-Ledger ab den Quellen.
- **"formal wins" beibehalten** — verworfen: stale Formal koennte frisch
  entschiedene Prosa still ueberstimmen; Intima-Korrektur uebernommen.
- **Zwei getrennte Skills je Rolle und Harness** — verworfen (PO-Q4):
  ein Skill mit Rollen-Gate + Harness-Selbsterkennung haelt das
  Prozesswissen single-source.
- **Harness-Variant-Achse im Skill-Binder** — vertagt als Folge-Story;
  erst bei harter Format-Divergenz noetig.
- **Inkubator unversioniert wie Intima** — verworfen zugunsten der
  klassenbasierten Policy (Nachvollziehbarkeit der Prozessartefakte ohne
  irreversibles Leaken sensibler Rohquellen).

## 4. Impact-Sweep (P3/W4)

Semantische und lexikalische Suche ueber den Korpus (Begriffe: Konzeption,
Inkubator, Werkstatt, Skills, Bundles, Harness, Guards, Meta-Contract,
formal wins, Registry, Top-Level-Struktur). Beruehrte Autoritaeten:
DK-00 (Saeulen), CLAUDE.md (Work Modes), PROJECT_STRUCTURE (Top-Level +
bundles-Baum + concept-Regeln), Meta-Contract §2, Konsistenz-Governance
(unveraendert, referenziert), FK-43/FK-76/FK-30/FK-50 (nur referenziert,
nicht geaendert), Registries (domain, bounded-contexts, module, tags,
policies), Referenz-Integritaets-Baseline (Zyklus DK-16/FK-78,
Zielprojekt-Pfad), formal-spec (neuer Kontext).

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| `concept/domain-design/16-konzeption-und-konzeptinkubation.md` | neu | Fachliche Saeule Konzeption (DK-16). |
| `concept/domain-design/00-uebersicht.md` | geaendert | Teilkonzept-Tabelle + Saeule 4.10 + Saeulenzahl. |
| `concept/technical-design/78_concept_incubation_process.md` | neu | Technisches Feinkonzept (FK-78). |
| `concept/technical-design/00_index.md` | geaendert | Neue BC-Sektion 20a fuer FK-78. |
| `concept/formal-spec/concept-incubation/*` | neu | Formaler Kontext (entities, state-machine, commands, events, invariants, scenarios, README). |
| `concept/formal-spec/00_meta/meta-contract.md` §2 | geaendert | "formal wins" → Verweis auf Assertion-Vertrag ("disagreement blocks"). |
| `concept/_meta/assertion-authority.md` | neu | Assertion-/Projektions-Vertrag. |
| `concept/_meta/projection-manifest.json` | neu | Korpusweiter Statusträger; Initialeintraege mit ehrlichem blocked_projection. |
| `concept/_meta/concept-governance.json` | neu | Projektlokale Toolchain-Konfiguration. |
| `concept/_meta/konzept-konsistenz-governance.md` | geprueft, nicht geaendert | P1–P5 und W1–W4 bleiben unveraendert; der Inkubator ersetzt nur den informellen `_temp`-Referenzprozess aus P3 als gelebte Praxis, die P3-Normtexte bleiben gueltig. |
| `concept/_meta/reference-integrity-baseline.yaml` | geaendert | Zyklus-Baseline DK-16/FK-78; Zielprojekt-Pfad concept_toolchain; Zeilenkorrektur Glossar-Eintraege. |
| `concept/technical-design/_meta/domain-registry.yaml` | geaendert | Neue Domaene concept-incubation (DK-16, FK-78). |
| `concept/technical-design/_meta/bounded-contexts.yaml` | geaendert | BC-Eintrag mit owns/excluded. |
| `concept/technical-design/_meta/module-registry.yaml` | geaendert | Modul concept-incubation. |
| `concept/technical-design/_meta/policy-registry.yaml` | geaendert | Policies concept-consistency-governance, assertion-authority. |
| `concept/technical-design/_meta/tag-corpus.txt` | geaendert | Neue Tags; Datei erstmals vollstaendig alphabetisch sortiert (Vertragserfuellung). |
| `CLAUDE.md` (Work Modes) | geaendert | Dritter Modus Council-Orchestrator. |
| `PROJECT_STRUCTURE.md` | geaendert | Top-Level `concept-incubator/`, concept-Regel-Ausnahme fuer `_meta`-Registries, `concept_toolchain/` im bundles-Baum. |
| `.gitignore` | geaendert | Ignore-Regeln fuer die Lock- und Secret-Verzeichnisse des Inkubators. |
| `concept-incubator/` (INDEX, Gruendungslauf) | neu | Werkstatt gemaess FK-78; Gruendungslauf mit Sonderstatus dokumentiert. |
| FK-43 §43.4.1 | geprueft, nicht geaendert | Skill-Auslieferung nutzt Root-SKILL.md single-source; Harness-Variant-Achse bleibt Folge-Story. |
| FK-76 | geprueft, nicht geaendert | Spawn-/Hybrid-Mechanik wird referenziert, nicht veraendert. |
| FK-30 | geprueft, nicht geaendert | Enforcement-Ownership bleibt; FK-78 liefert nur Regeldefinitionen (Guard-Implementierung ist Folgearbeit im Rahmen der Toolchain-/Guard-Stories). |
| FK-50 | geprueft, nicht geaendert | Installation der neuen Bundle-Assets folgt dem bestehenden Checkpoint-Modell. |
| `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/` | neu (Folgeschritt dieses Vorhabens) | Deploybare Toolchain; bis zur Landung sind die betroffenen Scopes im Projektionsmanifest blocked_projection. |
| `src/agentkit/bundles/skill_bundles/concept-incubation-core/` | neu | Skill-Bundle (SKILL.md + references + templates + Contract-Tests). |
| `scripts/ci/check_concept_*` und `tools/concept_compiler`/`tools/concept_governance` | geprueft, nicht geaendert | Bleiben unveraendert AK3s eigene Gates. Die urspruenglich fuer dieses Vorhaben vorgesehene Wrapper-Migration auf die gebundelte Engine ist als Folge-Story 1 (FK-78 §78.17) ausgewiesen: das Subsystem ist gewachsen (~5.200 Zeilen mit eigener Testabdeckung) und seine Umverdrahtung braucht ein eigenes testgetriebenes Vorhaben mit Ist-/Soll-Ausgabevergleich. Interimsschutz gegen stille Divergenz: verpflichtender Engine-Selfcheck gegen den AK3-Korpus (Integrationstest). |
| `concept/formal-spec/00_meta/syntax-contract.md` | geaendert | Enge Ausnahme fuer schema-validierte `_meta`-Registry-/Manifest-Dateien. |
| `concept/formal-spec/00_meta/meta-contract.md` §10 | geaendert | Dieselbe Ausnahme fuer verifier-geprüfte `_meta`-Materialisierungen. |
| `tools/concept_compiler` (Szenario-Schrittsemantik) | referenziert-jetzt | Folge-Story: schrittgenaue Command→Transition-Pruefung in Szenarien (heute erreichbarkeitsbasiert); bis dahin sichern Invarianten + Prosa-Gate-Mapping die Semantik. |

## 5a. Bootstrap-Ausnahme (einmalig, nicht praezedenzbildend)

Der Gruendungslauf `2026-07-19-conception-support-b4a7d375` hat den
Inkubator-Prozess selbst eingefuehrt; seine fruehen Artefakte entstanden
vor Existenz der FK-78-Schemata. Sie werden als Evidenz gefuehrt und
nicht rueckwirkend als schema-konforme Register ausgegeben.
**Bootstrap-Declassification:** Das versionierte Review-1-Artefakt wurde
auf die Findings-Fassung reduziert (Werkzeug-Transkript entfernt); die
verbleibenden Quellzitate (Pfadangaben des Referenzprojekts) sind vom PO
durch die Beauftragung dieser Uebernahme freigegeben. Diese Ausnahme gilt
genau einmal fuer den Gruendungslauf; jeder Folgelauf unterliegt
vollstaendig FK-78 §78.13 (Artifact-Register, Vererbung,
Declassification-Receipts).

## 6. Offene Punkte (sichtbar, mit Owner)

- Toolchain-Implementierung + Tests, Skill-Bundle, Receipts fuer die
  Initial-Scopes: Owner Council-Orchestrator des Gruendungslaufs; sichtbar
  via `concept/_meta/projection-manifest.json` (blocked_projection) und
  `concept-incubator/runs/2026-07-19-conception-support-b4a7d375/README.md`.
- Folge-Stories (deklariert in FK-78 §78.17): Harness-Variant-Achse,
  Hub-Batch-Komfort W2/W3, KPI-/Telemetrie-Anbindung, Backend-Sicht.
