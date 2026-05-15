# AgentKit 3 — Concept-Onboarding

Stand: 2026-05-15

Briefing fuer Agents/Sub-Agents, die im Konzept-Korpus unter `concept/`
arbeiten oder ihn als Wahrheitsquelle nutzen. Liefert die **Topologie**
und die **Mechanik** der drei Konzeptschichten. Fachliche AK3-Sicht
(Pipeline, Phasen, Saeulen) steht in `prompts/agent-onboarding.md`;
hier nicht doppeln.

## 0. Vor allem anderen

- `CLAUDE.md` + `PROJECT_STRUCTURE.md` gelten.
- Bei Konflikt: **Formal-Spec gewinnt** ueber Prosa fuer maschinen-
  pruefbare Aussagen. Prosa gewinnt fuer Rationale, UX, Risiken.
- **Nie eine zweite Wahrheitsquelle** anlegen (parallele Listen in
  Prosa zu State/Event/Command-Sets sind verboten).
- Generierte Artefakte (IR, Reports, Glossar-Overviews) sind nie
  autoritativ und landen in `var/`, nie in `concept/`.

## 1. Drei Schichten

| Schicht | Pfad | Form | ID-Praefix | Rolle |
|---|---|---|---|---|
| Domain | `concept/domain-design/` | Prosa | `DK-NN` | Fachliche Begruendung, Trade-offs, Heuristiken |
| Technical | `concept/technical-design/` | Prosa-Feinkonzept | `FK-NN` | Technische Detaillierung der Domaene, pro BC sektioniert |
| Formal | `concept/formal-spec/<context>/` | Structured Markdown | `formal.<ctx>.<artifact>` | Deterministisch pruefbare Systemsemantik |

Methodische Grundlage (cross-project): `concept/methodology/software-blutgruppen.md` (A/R/T/0).

## 2. Navigationskarte

| Frage | Hingehen nach |
|---|---|
| Was sagt das Fachkonzept zu X? | `domain-design/` (DK-NN) |
| Wie ist X technisch geschnitten? | `technical-design/` (FK-NN) |
| Welche States/Events/Commands/Invarianten hat X? | `formal-spec/<context>/` |
| Welche BC besitzt X? | `concept/technical-design/_meta/domain-registry.yaml` + `bounded-contexts.yaml` |
| Was sind die BC-Schnitt-Entscheidungen? | `concept/_meta/bc-cut-decisions.md` |
| Wie ist Begriff X definiert? | Glossar-Block im Contract-Doc des Owner-BC |
| Welche Policy gilt cross-cutting? | `concept/technical-design/_meta/policy-registry.yaml` |
| Welcher Tag/Modul ist erlaubt? | `_meta/tag-corpus.txt` / `_meta/module-registry.yaml` |
| Normativer Komponentenschnitt | `concept/formal-spec/architecture-conformance/entities.md` |
| FK-Index nach BC sortiert | `concept/technical-design/00_index.md` |

## 3. Werkzeug: MCP statt grep

**Default-Pfad fuer alle Konzept-Lookups**: der `agentkit3-concepts`-
MCP-Server. Er indexiert den gesamten Korpus semantisch + lexikalisch
und kennt die Layer-/BC-/Surface-Filter. grep oder File-Walks ueber
`concept/` sind die schlechte Alternative — sie sehen weder
Cross-Referenzen noch BC-Zuordnung.

Zwei Collections:

- `Ak3ConceptChunk` — H2-Sektionen aller Konzeptdokumente (alle drei Layer)
- `Ak3GlossaryTerm` — exportierte und interne Glossarbegriffe pro BC

Wichtige Filter (top-level auf jedem Chunk):

- `layer`: `domain` | `technical` | `formal`
- `domain`: BC-id (siehe domain-registry.yaml)
- `surface`: `contract` | `internal` (abgeleitet, nicht manuell)
- `cross_cutting`: bool — Foundation-/Adapter-/Referenz-Docs ohne BC-Owner
- `applies_policies`, `defers_to_ids`, `defers_to_edges`,
  `formal_ref_ids`, `supersedes_ids`, `superseded_by_id`,
  `authority_scopes` — alle filterbar

Typische Calls:

```text
concept_search(query="Worker-Health Scoring", domain="implementation-phase",
               layer="technical", limit=10)
concept_search(query="QA-Subflow Remediation", layer="formal", limit=5)
concept_glossary_search(query="VerifyContext", domain="verify-system")
concept_get(doc_id="FK-27")
concept_filter_help()
```

Wenn Layer-Disambiguierung gefragt ist (Domain-Idee vs. FK-Feinkonzept
vs. formale Spec): `layer`-Filter setzen — das loest die drei Sichten
in einem Call. Wenn ein BC interessiert: `domain=<bc-id>` plus optional
`surface=contract` fuer die Vertragssicht des BC.

## 4. Formal-Spec — Dateiform und Mechanik

### Dateiform (`formal-spec/00_meta/syntax-contract.md`)

```text
---
id: formal.<context>.<artifact>
title: <string>
status: active
doc_kind: spec
context: <context>
spec_kind: state-machine | command-set | event-set | invariant-set | scenario-set | entity-set
version: <int>
prose_refs:
  - concept/technical-design/NN_*.md
---

# Lesbare Einleitung (kein Normativwert)

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.<context>.<artifact>
schema_version: <int>
kind: <spec_kind>
context: <context>
# ... kind-spezifische Felder ...
```
<!-- FORMAL-SPEC:END -->
```

Genau **eine** Spec-Zone pro Datei. Normative Semantik nur innerhalb
der Zone. YAML/Listen ausserhalb sind Kommentar.

### Sechs Kernobjektarten (`formal-spec/00_meta/object-kinds.md`)

`state-machine`, `command-set`, `event-set`, `invariant-set`,
`scenario-set`, `entity-set`. Keine eigenen Top-Level-Silos
(`states/`, `constraints/`, ...) — alles liegt **lokal pro Kontext**:

```text
formal-spec/<context>/
  README.md
  entities.md         # entity-set (optional)
  state-machine.md
  commands.md
  events.md
  invariants.md
  scenarios.md
```

### IDs (`formal-spec/00_meta/id-and-reference-scheme.md`)

- Dokument-ID: `formal.<context>.<artifact>`
- Objekt-ID: `<context>.<kind>.<name>`, z.B. `exploration.state.gate_approved`
- Referenzen **ausschliesslich** ueber IDs. Nie Dateinamen, nie Headings.
- Einmal vergebene ID wird nicht stillschweigend recycelt; bei
  Aufspaltung explizit deprecated.
- Kontextnamen: lowercase, Bindestriche, fachlich stabil.

### Compiler (`tools/concept_compiler/`, `compiler-pipeline.md`)

Sechs deterministische Phasen:

1. Parse + Schema (Frontmatter, Spec-Zone, Pflichtfelder, erlaubte `kind`)
2. Referenzaufloesung (existieren IDs, typkompatibel, keine Kollisionen)
3. Modellkonsistenz (terminale States, gueltige Bezuege)
4. Vollstaendigkeitsregeln (Coverage)
5. Trace-Validierung deklarierter `scenario-set`-Pfade
6. Drift-Audit gegen Prosa

Keine generelle Pfadsuche. Generierte Reports nach `var/`.

## 5. BC-Schnitt + Cross-Cutting

### 16 fachliche BCs + Shared + 12 Boundary-Module

Normativ: `concept/formal-spec/architecture-conformance/entities.md` (schema_version 2).
Entscheidungs-Log: `concept/_meta/bc-cut-decisions.md` (Aenderung nur per User-Trigger).

Pro BC: eine Top-Komponente (z.B. `PipelineEngine`, `VerifySystem`,
`StoryContextManager`, `Governance`), Sub-1-Layer-Order, Exposure pro Sub
(`top` | `sub_exposed` | `internal`). Aufrufe zwischen BCs **per Default
gegen die Top-Surface**; `sub_exposed` nur bei nachgewiesenem Bedarf.

### Vokabular-Disziplin

- Erlaubt: Komponente, Klasse, Schnittstelle
- Verboten als Architektur-Pattern-Begriff: Port, Adapter, Hexagonal,
  Onion, Clean Architecture

### Phasen-Mapping (Variante Y, eingearbeitet 2026-05-03)

4 Top-Phasen: **Setup, Exploration, Implementation, Closure**.
`verify-system` ist **Capability-BC, kein Phase-Owner**. QA ist Subflow
innerhalb der Exit-Gates von Exploration und Implementation. Eine
eigenstaendige Top-Phase `verify` existiert nicht.

### Bluttypen + Anti-Laundering

A (Fachlogik), R (Repraesentation/Adapter), T (Technik/Treiber),
0 (Utility). AT-Mischformen sind an Mediation-Stellen legitim, dort
lokalisiert. Anti-Laundering: `A -> R -> T` ist erlaubt, aber die
R-Schnittstelle **darf keine T-Typen exponieren**. `mix_allowed: [T]`
kennzeichnet bewusste Mischzonen.

### Cross-Cutting

Docs ohne BC-Owner tragen `cross_cutting: true` (Foundation, Adapter,
Referenzanhaenge wie FK-90/91/92/93, FK-07, FK-72, FK-74, FK-75).
Im Zweifel: einer Domaene zuordnen statt cross-cutting setzen.

`surface` ist **abgeleitet, nicht manuell**:

- Contract-Doc einer Domaene **und** hat `formal_refs` -> `surface: contract`
- sonst -> `surface: internal`

Cross-Domain-Referenzen duerfen nur auf `surface: contract`-Docs
zeigen (Lint L18). Cross-cutting-Docs sind Source und Target von L18
ausgenommen.

## 6. Registries unter `_meta/`

| Datei | Rolle |
|---|---|
| `concept/_meta/bc-cut-decisions.md` | Decision-Log fuer BC-Schnitt; nur via User-Trigger aenderbar |
| `concept/technical-design/_meta/domain-registry.yaml` | BC-Schnitt: id, display_name, contract_docs, member_docs |
| `concept/technical-design/_meta/policy-registry.yaml` | Querschnitts-Policies; referenziert via `applies_policies` |
| `concept/technical-design/_meta/module-registry.yaml` | Bruecke Konzept-`module:` ↔ Komponentenarchitektur |
| `concept/technical-design/_meta/tag-corpus.txt` | Kanonischer Tag-Katalog, eine Zeile pro Tag |
| `concept/technical-design/_meta/bounded-contexts.yaml` | Semantische BC-Quelle: responsibility, owns, excluded |
| `concept/technical-design/_meta/glossary-overview.md` | Generiert, niemals manuell editieren |
| `concept/technical-design/_meta/glossary-reverse-index.md` | Generiert, niemals manuell editieren |

## 7. Frontmatter-Vertrag (FK-00 §21)

Pflichtfelder fuer jedes DK-/FK-Dokument:

```yaml
concept_id:        FK-NN | DK-NN
title:             <string>
module:            <kebab-case>      # muss in module-registry.yaml stehen
status:            active | draft
doc_kind:          core | detail     # bei detail: parent_concept_id Pflicht
parent_concept_id: FK-NN | DK-NN | <leer>
authority_over:                       # mind. ein Eintrag
  - scope: <kebab-case>
defers_to:         [FK-NN, ...]      # ggf. leer
supersedes:        [FK-NN, ...]      # ggf. leer
superseded_by:     FK-NN | <leer>
tags:              [..., ...]        # mind. einer; aus tag-corpus.txt
```

Klassifikation **mutually exclusive** — genau eines von:

- `formal_refs: [formal.x.y, ...]` + `prose_anchor_policy: strict`
- `formal_scope: prose-only`

Beides oder keins von beiden = fail-closed verboten.

Optional, sobald Domain-Registry scharf:

```yaml
domain:            <bc-id>           # ODER cross_cutting: true
applies_policies:  [policy.x, ...]
contract_state:    active | compatible | deprecating | breaking
migration_ack:     <new-contract-id>
```

## 8. Lints — alle fail-closed, Severity Error

Keine Warnings. CLAUDE.md-Begruendung: aufschiebbares Handeln passiert
nicht; Warning-Pfade gehen unter.

### Frontmatter-Lint (`scripts/ci/check_concept_frontmatter.py`)

| Lint | Bedeutung |
|---|---|
| L1-L9 | concept_id Pattern + Eindeutigkeit; parent/defers_to-Targets existieren; supersedes-Form + Reziprozitaet |
| L10 | Authority-Graph (`parent_concept_id` + `defers_to`) zyklenfrei |
| L11 | Authority-Disjunktheit: kein `authority_over.scope` doppelt |
| L12 | Authority-Typkompatibilitaet |
| L13 | Index-Vollstaendigkeit: jede technical-design-Datei in FK-00 §1-§19 und umgekehrt |
| L14 | Body-Referenz-Existenz: jede FK-NN/DK-NN-Erwaehnung muss existieren |
| L15 | `formal_refs` ↔ Body-Anker (`<!-- PROSE-FORMAL: ... -->`) bei `prose_anchor_policy: strict` |
| L17 | `domain` Pflicht (oder `cross_cutting: true`); BC muss in Domain-Registry; `applies_policies` muss in Policy-Registry |
| L18 | Cross-Domain-Refs duerfen nur auf `surface: contract`-Docs zeigen; cross-cutting exempt |
| L19 | Glossar-FK-Integritaet: `see_also.term`+`domain` deterministisch aufloesbar; kein Term sowohl exported als auch internal |
| L20 | Implicit-Leakage: kein `internal_term` einer fremden Domaene mit normativem Modalverb in Doc anderer Domaene |

### Concept-Compiler (`scripts/ci/compile_formal_specs.py`)

- `audit_concept_doc_classification` — jedes DK/FK hat genau eine
  Klassifikation (`formal_refs` xor `formal_scope: prose-only`)
- `audit_formal_prose_links` — `formal_refs` zeigen auf existierende
  kompilierte Specs; reziproker `prose_refs` in der Spec; bei strict-
  Policy alle `formal_refs` als Body-Anker vertreten

## 9. Glossare (dezentral, in-Doc)

- Pro **Contract-Doc des Owner-BC** ein `glossary:`-Block in der
  Frontmatter (oder dedizierte `## Glossar`-Sektion).
- Form:

  ```yaml
  glossary:
    exported_terms:
      - id: <Term>
        definition: <string>
        values: [optional, fuer Enums]
        see_also:
          - term: <Other-Term>
            domain: <other-bc-id>    # explizit, fuer deterministische Aufloesung
    internal_terms:
      - id: <implementation-detail>
        reason: <warum nicht exportiert>
  ```

- **Ownership** ist scharf: nur der Domain-Owner schreibt im eigenen
  Block. Fremde BCs nie editieren — Fehler melden, nicht fixen.
- Lint generiert read-only `glossary-overview.md` und
  `glossary-reverse-index.md` unter `_meta/`. Niemals manuell editieren.

## 10. Was formal werden muss, was Prosa bleibt

| Zwingend formal | Zwingend Prosa |
|---|---|
| Zustaende + Uebergaenge + Terminalitaet | Architektur-Rationale |
| Commands / CLI-Wirkungen | Trade-offs |
| Events | UX-Entscheidungen |
| Invarianten (deterministisch pruefbar) | Organisatorische Ownership |
| Deklarierte Szenario-Traces | Qualitative Heuristiken |
| Entitaeten mit Identitaet/Lifecycle | Fachliche Motivation |
| | Nichtdeterministische Realwelt-Effekte |

Faustregel: Wenn die Aussage deterministisch pruefbar ist und
operatives Verhalten normiert -> Formal-Spec. Sonst Prosa.

## 11. Schichten-Kopplung (Drift-Schutz)

```text
Prosa (DK/FK)  ──formal_refs──►  Formal-Spec (formal.<ctx>.<artifact>)
     │                                    │
     │  <!-- PROSE-FORMAL: ... -->        │  prose_refs (reziprok)
     │  Body-Anker (strict policy)        │
     ▼                                    ▼
 Lint prueft Anker-Existenz       Compiler prueft Modell + Traces
     └─────────► Drift-Audit ◄───────────┘
```

Eine fachliche Aussage existiert genau **einmal kanonisch**: entweder
als ID-tragendes Formal-Objekt (diskrete Semantik) oder als Prosa
(Rationale). Parallel gepflegte Listen sind Compile-Fehler.

## 12. Anti-Patterns (Sofort-Stopp)

- Normative Liste (States, Events, Commands) als Prosa-Tabelle ohne Formal-Bezug.
- Verweis ueber Dateinamen, Headings oder Kapitelnummern statt ueber IDs.
- Zweite Spec-Zone in einer Datei, oder normative Semantik in Mermaid-Diagrammen / freier Tabelle ausserhalb der Zone.
- Cross-Cutting-Doc setzen, weil "passt nirgendwo richtig" — Foundation-Sinkhole-Antipattern. Stattdessen: Domaene zuordnen.
- Neue Querschnitts-Domaene anlegen statt Policy in `policy-registry.yaml` ergaenzen.
- Cross-Domain-Referenz auf ein `surface: internal`-Doc (verletzt L18).
- Glossarblock einer fremden Domaene editieren.
- Generiertes Artefakt (Overview, Reverse-Index, IR, Coverage-Report) als Quelle behandeln oder manuell anfassen.
- BC-Schnitt einfach umorganisieren — `bc-cut-decisions.md` braucht expliziten User-Trigger.
- Architektur-Pattern-Vokabular (Port/Adapter/Hexagonal/Onion/Clean) in Konzept- oder Code-Texten.

## 13. Operativer Default-Workflow

1. Frage formulieren: was suche ich, in welcher Schicht, in welchem BC?
2. MCP-Call mit Layer-/BC-Filter absetzen (`concept_search` /
   `concept_glossary_search`). grep/Read sind Fallback, nicht Default.
3. Treffer pruefen: ist es Contract-Doc (`surface: contract`) oder
   Innenleben? Cross-Domain-Refs nur auf Contract.
4. Bei normativer Aussage: existiert die als Formal-ID? Wenn ja,
   referenziere die ID, nicht die Prosa.
5. Bei Aenderung: pruefe Frontmatter-Konsistenz (Klassifikation,
   `authority_over`, `defers_to`, ggf. `formal_refs`-Reziprozitaet)
   und ob ein Lint-Lauf noetig wird.
6. Generierte Artefakte aktualisieren (Glossar-Overview, IR-Reports)
   nicht manuell — Tool-Lauf, niemals von Hand.

---

Wenn du nach dem Lesen unsicher bist, **wo** etwas hingehoert: erst
Domaene/BC bestimmen, dann Layer (Domain/Technical/Formal), dann
Datei. Nicht umgekehrt.
