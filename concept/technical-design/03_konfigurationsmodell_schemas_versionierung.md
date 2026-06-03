---
concept_id: FK-03
title: Konfigurationsmodell, Schemas und Versionierung
module: configuration
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: configuration
  - scope: config-schema-validation
  - scope: config-versioning
defers_to:
  - target: FK-02
    scope: stage-registry
    reason: Stage-Registry ist im Domänenmodell definiert
supersedes: []
superseded_by:
tags: [konfiguration, schema, versionierung, yaml, pydantic]
formal_scope: prose-only
---

# 03 — Konfigurationsmodell, Schemas und Versionierung

**Vollständigkeitsanspruch:** Dieses Kapitel definiert die vollständige
Konfigurationsstruktur von AgentKit. Jeder konfigurierbare Parameter
muss hier dokumentiert sein. Wenn eine Komponente in einem anderen
Kapitel technisch beschrieben wird, muss ihr konfigurierbarer Anteil
hier referenziert werden. Neue Konfigurationsparameter, die in
späteren Kapiteln entstehen, werden hier nachgetragen.

## 3.1 Konfigurationshierarchie

AgentKit verwendet vier Konfigurationsebenen. Höhere Ebenen
überschreiben niedrigere. **Wichtig:** Ebene 3 (Story-Attribute aus dem
AK3-Story-Backend) wird ausschließlich einmalig während der Setup-Phase
gelesen und als `StoryContext` im State-Backend persistiert. Ein
`context.json` ist nur ein materialisierter Export dieses Snapshots. Ab
da liest die Pipeline nur noch den Snapshot, nie mehr das Story-Backend.
Die Hierarchie beschreibt die **Startup-Auflösung**, nicht ein
Laufzeit-Merge.

```
Ebene 4: CLI-Argumente            (höchste Priorität, Startup)
    ▼
Ebene 3: Story-Attribute          (AK3-Story-Backend, nur bei Setup einmalig gelesen)
    ▼
Ebene 2: Projektkonfiguration     (.agentkit/config/project.yaml, bei Start geladen)
    ▼
Ebene 1: AgentKit-Defaults        (im Python-Code, Pydantic-Defaults)
    ▼
Ergebnis: StoryContext (autoritiver Snapshot, optional als `context.json` exportiert)
```

### Ebene 1: AgentKit-Defaults (im Code)

Definiert in `agentkit/core/config.py` als Pydantic-Defaults.
Beispiele:

```python
class FeaturesConfig(BaseModel, frozen=True):
    multi_repo: bool = False
    vectordb: bool = False
    multi_llm: bool = True       # FK-Pflicht
    telemetry: bool = True
    db: bool = False
    e2e_assertions: bool = False

class PolicyConfig(BaseModel, frozen=True):
    major_threshold: int = 3
    required_stages: list[StageConfig] = [
        StageConfig(id="structural", blocking=True),
        StageConfig(id="llm_review", blocking=True),
        StageConfig(id="adversarial", blocking=False),
        StageConfig(id="e2e_verify", blocking=True),
    ]
```

### Ebene 2: Projektkonfiguration (`project.yaml`)

Zentrale Konfigurationsdatei unter `.agentkit/config/project.yaml`.
Wird vom Installer erzeugt (Checkpoint 5) und vom Nutzer angepasst.

```yaml
config_version: "3.0"

project_key: "acme-trading"
project_prefix: "ACME"

github_owner: "acme-corp"   # GitHub-Owner als Code-Backend (Repos, Branches, PRs)

repositories:
  - name: backend
    path: "."
    language: python
    test_command: "pytest"
    build_command: "ruff check"

wiki_stories_dir: stories
guardrails_dir: _guardrails
guardrails_pattern: "*.md"

features:
  multi_repo: false
  vectordb: true
  multi_llm: true
  telemetry: true
  db: true
  e2e_assertions: true
  are: false                  # Agent Requirements Engine (optional)

llm_roles:
  worker: claude
  qa_review: chatgpt
  semantic_review: gemini
  adversarial_sparring: grok
  doc_fidelity: gemini
  governance_adjudication: gemini
  story_creation_review: chatgpt

orchestrator_guard:
  blocked_paths:
    - "/src/"
    - "/lib/"
    - "/app/"
  blocked_extensions:
    - ".java"
    - ".py"
    - ".ts"
    - ".go"
    - ".rs"
    - ".kt"
  blocked_files:
    - "pom.xml"
    - "build.gradle"
    - "package.json"
    - "Cargo.toml"
    - "pyproject.toml"
    - "Dockerfile"
    - "docker-compose.yml"

policy:
  major_threshold: 3
  max_feedback_rounds: 3
  # Stages sind in der typisierten Stage-Registry definiert (Kap. 02.9).
  # Hier können Overrides pro Projekt gesetzt werden:
  stage_overrides:
    adversarial:
      blocking: false           # Default true, hier auf non-blocking herabgestuft (z.B. Pilotphase)

vectordb:
  similarity_threshold: 0.7
  max_llm_candidates: 5

telemetry:
  web_call_limit: 200        # Hard-Limit, nur für Research-Stories
  web_call_warning: 180      # Warnschwelle, nur für Research-Stories

assertion_governance:
  system_assertions: true     # Allgemeine System-Assertions (Health, Smoketest)
  require_assertion_review: false

are:
  enabled: false              # ARE ist optional
  mcp_server: "are-server"    # MCP-Server-Name (registriert in .mcp.json)

governance:
  risk_threshold: 30          # Risikoscore-Schwelle für Incident-Kandidat
  window_size: 50             # Rolling-Window-Breite in Events
  cooldown_s: 300             # Cooldown zwischen LLM-Adjudications gleichen Typs

sonarqube:
  available: true             # Projekt/Host deklariert ein Sonar überhaupt (Capability-Schalter). false = kein Sonar
  enabled: true               # Pflicht (hart) für codeproduzierende Projekte (impl/bugfix-Stories) MIT available:true
  base_url: "http://localhost:9901"   # SonarQube-Server (FK-10 §10.7.2)
  min_version: "26.4"         # SonarQube Community Build Mindestversion
  token_env: "SONARQUBE_TOKEN" # Verweis auf ENV/Secret-Store — NIE inline-Token
  plugins:
    community_branch:
      min_version: "1.23.0"   # Community Branch Plugin (harte Abhängigkeit, FK-33 §33.6.3)
  quality_gate:
    default_profile: "resources/target_project/sonar/ak3-default-gate.json"  # ausgeliefertes Default-Profil (SSOT)
    overrides_allowed: true   # Projektverantwortlicher darf eigenes Regelwerk setzen
```

#### SonarQube-Stanza (`sonarqube`) — Felder und Validierung

Die `sonarqube`-Stanza deklariert die Umgebungs- und Profil-Anforderung
des SonarQube-Green-Gates (Gate-Semantik in FK-33 §33.6.3, Capability
`sonarqube_gate`). Sie ist der Config-Owner-Anteil dieser Anforderung;
geprueft wird sie als Installer-Vorbedingung (FK-50) und gefuehrt als
Pflicht-Laufzeitabhaengigkeit (FK-10 §10.2.2).

| Feld | Typ | Bedeutung |
|------|-----|-----------|
| `available` | bool | **Capability-Schalter (Default `true` fuer codeproduzierende Projekte): Deklariert, ob das Projekt/der Host *ueberhaupt* ein Sonar besitzt.** `false` erklaert „kein Sonar" — das `sonarqube_gate` ist dann an allen drei Lifecycle-Gate-Punkten **NOT_APPLICABLE** (kein fail-closed; FK-33 §33.6.5). Das ist **auch fuer codeproduzierende Projekte ausdruecklich zulaessig** — Konsequenz: keine Sonar-Qualitaetsdurchsetzung, der Betreiber akzeptiert das bewusst. Klar abzugrenzen von `enabled`: `available` sagt „gibt es ein Sonar?", `enabled` sagt „ist die Gate-Maschinerie scharf geschaltet?". |
| `enabled` | bool | **Hart Pflicht (`true`) fuer codeproduzierende Projekte mit `available: true`** (Projekte mit impl/bugfix-Stories, die ein Sonar besitzen). Reine Concept-/Research-Projekte **oder** Projekte mit `available: false` duerfen `false` setzen. Bei `available: false` ist `enabled` bedeutungslos (das Gate ist NOT_APPLICABLE). |
| `base_url` | str (URL) | SonarQube-Server-Endpunkt (Default-Port 9901, FK-10 §10.7.2). |
| `min_version` | str (SemVer) | Mindestversion SonarQube Community Build. Niedrigere Server-Version → Installer-FAIL (FK-50). |
| `token_env` | str | Name der ENV-Variable bzw. des Secret-Store-Schluessels mit dem Sonar-Token. **Kein Inline-Token** (Secret-Hygiene, FK-33 §33.3.2 `security.secrets`). |
| `plugins.community_branch.min_version` | str (SemVer) | Mindestversion des **Community Branch Plugin** (harte Abhaengigkeit, da Community Edition keine native Branch-Analyse hat; FK-33 §33.6.3). |
| `quality_gate.default_profile` | str (Pfad) | Verweis auf das ausgelieferte Default-Quality-Gate-Profil unter `resources/target_project/` (SSOT). Traegt BEIDE Conditions: New-Code UND Overall-Code (FK-33 §33.6.3 Overall-Code-Invariante). |
| `quality_gate.overrides_allowed` | bool | Ob der Projektverantwortliche das Default-Profil durch ein eigenes Regelwerk ersetzen darf (Default `true`). |

**Pydantic v2-Validierung** (`SonarQubeConfig` als frozen-Modell,
`extra="forbid"`, eingebunden in `PipelineConfig`):

- `available == true` UND `enabled == true` UND fehlende
  `base_url`/`token_env` → `ValueError` (fail-closed, kein stiller Default
  auf Localhost ohne Auth). Bei `available == false` entfaellt diese
  Pflicht — die Umgebungsfelder duerfen leer bleiben (es gibt kein Sonar).
- `min_version` / `plugins.community_branch.min_version` muessen
  parsebare SemVer-Strings sein.
- `quality_gate.default_profile` muss auf eine existierende Profil-Datei
  unter `resources/target_project/` zeigen (Pfad-Existenz im
  Installer-Verify, FK-50 CP 12).
- **Cross-Field-Regel (auf `available` umgestellt):** Ein Projekt mit
  codeproduzierenden Stories (impl/bugfix im Story-Backend) und
  `sonarqube.available: true`, aber `sonarqube.enabled: false`, ist
  unzulaessig — der Setup-Preflight (FK-22 §22.4c) und das Closure-Gate
  (FK-29 §29.1a / FK-35 §35.2.4a) koennen dann ihre APPLICABLE-Vorbedingung
  nicht erfuellen (Sonar deklariert vorhanden, Gate aber nicht scharf).
  Diese Regel wird beim Config-Laden als `ValueError` durchgesetzt (analog
  `e2e_assertions requires db`, §3.2.1). **`sonarqube.available: false` ist
  hingegen auch fuer codeproduzierende Projekte ausdruecklich zulaessig**
  (kein `ValueError`): Das `sonarqube_gate` ist dann an allen drei
  Lifecycle-Gate-Punkten NOT_APPLICABLE und wird uebersprungen (FK-33
  §33.6.5) — der Betreiber akzeptiert bewusst, dass es keine
  Sonar-Qualitaetsdurchsetzung gibt. Abzugrenzen vom *konfiguriert-aber-
  unerreichbaren* Sonar (`available: true`, Server nicht erreichbar), das
  weiterhin fail-closed blockt (FK-33 §33.6.5, „abwesend ≠ kaputt").

#### Config-Hash (Drift-Erkennung der Gate-Konfiguration)

Damit eine manuelle Aenderung am SonarQube-Regelwerk nicht unbemerkt die
Gate-Bedeutung verschiebt, werden die folgenden Bestandteile zu einem
**Config-Hash** verdichtet und in die commit-gebundene Attestation
gepinnt (FK-33 §33.6.3):

- **Quality-Gate-Hash** (die aktiven Gate-Conditions),
- **Quality-Profile-Hash** (das aktive Regelprofil),
- **Analysis-Scope-Hash** (`sonar.sources`/`sonar.inclusions`/
  `sonar.exclusions`),
- **New-Code-Definition** (Referenz-Branch / Datum / Tage),
- **Plugin-Version** des Community Branch Plugin.

Stimmt der Config-Hash der Attestation nicht mit dem erwarteten Wert des
Projekts ueberein, wurde gegen ein anderes Regelwerk vermessen — das
Integrity-Gate Dimension 9 (`SONAR_NOT_GREEN`, FK-35 §35.2.4a) schlaegt
dann fehl, und eine manuelle Admin-Aenderung an Gate/Profil/Scope/
New-Code-Definition gilt als „Policy-Change, der einen vollstaendigen
main-Rescan erfordert" (FK-50 Config-Drift-Behandlung). So bleibt Config
ein erkennbarer Teil der Wahrheit und kann nicht still neben dem
Gate-Ergebnis driften (FIX THE MODEL).

### Ebene 3: Story-spezifische Felder (Story-Attribute im AK3-Story-Backend)

Diese Story-Attribute werden pro Story im AK3-Story-Backend gepflegt und
beeinflussen Pipeline-Verhalten für genau diese Story:

| Story-Attribut | Typ | Werte | Verwendung |
|-------------|-----|-------|-----------|
| `Status` | Single Select | Backlog, Approved, In Progress, Done | Pipeline-Steuerung |
| `Story ID` | Text | z.B. `ODIN-042` | Korrelation |
| `Story Type` | Single Select | implementation, bugfix, concept, research | Pipeline-Pfad, Modus-Ermittlung |
| `Size` | Single Select | XS, S, M, L, XL, XXL | Review-Häufigkeit |
| `Change Impact` | Single Select | Local, Component, Cross-Component, Architecture Impact | Modus-Ermittlung (Trigger 2), Impact-Violation-Check |
| `New Structures` | Single Select | true, false | Modus-Ermittlung (Trigger 3) |
| `Concept Quality` | Single Select | High, Medium, Low | Modus-Ermittlung (Trigger 4) — Pflichtfeld, Default: High |
| `Module` | Text | Modulname | Kontext-Selektion |

`QA Rounds` und `Completed At` sind keine Story-Attribute, sondern
Telemetrie-Werte; sie werden nicht hier gepflegt, sondern in der
Telemetrie-DB ausgewertet (FK-68).

**Modus-Ermittlung** (REF-032 + Remediation: 4-Trigger-Modell) liest die Felder
`Story Type`, `Change Impact`, `New Structures` und `Concept Quality` sowie
Konzeptpfade (`concept_paths` als Story-Attribut aus dem AK3-Story-Backend) über `StoryContext`
bzw. dessen `context.json`-Export.
`Maturity`, `External Integrations` und `Requires Exploration` wurden entfernt.

### Ebene 4: Aufruf-Parameter

Überschreiben alle anderen Ebenen für einen einzelnen Aufruf.
Normative Aufruf-Parameter sind in FK-91 §91.1a (Service-API) bzw.
§91.1 (Operator-Recovery-CLI) definiert.

```bash
# Operator-Recovery-CLI (Spezialfall; Standardweg ist POST /phases/{phase}/start):
agentkit run-phase implementation --story ODIN-042 --config .agentkit/config/project.yaml
agentkit structural --story ODIN-042 --repo-id backend --base-ref main
agentkit install --gh-owner acme-corp --gh-repo trading-platform --dry-run
```

## 3.2 Konfigurationsvalidierung

### 3.2.1 Validierung beim Laden

`agentkit/core/config.py` lädt die YAML-Datei und validiert über
Pydantic:

```python
class PipelineConfig(BaseModel, frozen=True):
    config_version: str
    github: GitHubConfig
    repos: list[RepoConfig]
    # ... weitere Felder

    @model_validator(mode="after")
    def validate_config(self) -> "PipelineConfig":
        if self.config_version != "3.0":
            raise ValueError(f"Unsupported config version: {self.config_version}")
        if self.features.e2e_assertions and not self.features.db:
            raise ValueError("e2e_assertions requires db feature")
        if self.features.multi_llm and not self.llm_roles:
            raise ValueError("multi_llm requires llm_roles configuration")
        if self.features.multi_llm and self.llm_roles:
            required = {"qa_review", "semantic_review", "adversarial_sparring",
                        "doc_fidelity", "governance_adjudication"}
            missing = required - set(vars(self.llm_roles).keys())
            if missing:
                raise ValueError(f"llm_roles missing required roles: {missing}")
        if self.features.are and not self.are:
            raise ValueError("are feature requires are configuration section")
        if self.features.are and self.are and not self.are.mcp_server:
            raise ValueError("are.mcp_server must be set")
        return self
```

**Fail-closed:** Unbekannte Felder werden nicht stillschweigend ignoriert,
sondern erzeugen einen Fehler (`model_config = ConfigDict(extra="forbid")`).

### 3.2.2 Validierung bei Installation

Der Installer (Checkpoint 13: Verify) prüft die erzeugte Konfiguration:
- Alle referenzierten Story-Attribute sind im AK3-Story-Backend definiert
- Alle Enum-Story-Attribute haben die erwarteten Wertebereiche
- Alle referenzierten Repos existieren lokal

## 3.3 Schema-Katalog

### 3.3.1 JSON Schemas (Artefakte)

Alle QA-Artefakte werden gegen JSON Schemas validiert. Die Schemas
liegen im Zielprojekt unter `tools/qa/schemas/` (deployt vom Installer).

| Schema-Datei | Artefakt | Owning Chapter |
|-------------|----------|---------------|
| `envelope.schema.json` | Gemeinsame Envelope-Felder | 02 |
| `context.schema.json` | Story-Context | 22 |
| `structural.schema.json` | Structural-Check-Ergebnisse | 33 |
| `llm-review.schema.json` | LLM-Bewertung (12 Checks) | 34 |
| `semantic-review.schema.json` | Semantic Review | 34 |
| `adversarial.schema.json` | Adversarial-Testing-Ergebnisse | 34 |
| `decision.schema.json` | Policy-Entscheidung | 33 |
| `closure.schema.json` | Closure-Ergebnis | 25 |
| `worker-manifest.schema.json` | Worker-Deklaration | 24 |
| `handover.schema.json` | Handover-Paket | 24 |
| `entwurfsartefakt.schema.json` | Change-Frame (Exploration) | 23 |
| `bugfix-reproducer.schema.json` | Bugfix-Reproducer | 24 |
| `guardrail.schema.json` | Guardrail-Prüfung | 33 |
| `phase-state.schema.json` | Pipeline-Zustand | 20 |
| `story-search-result.schema.json` | VektorDB-Suchergebnisse | 13 |
| `incident.schema.json` | Failure-Corpus-Incident | 41 |
| `pattern.schema.json` | Failure-Corpus-Pattern | 41 |
| `check-proposal.schema.json` | Failure-Corpus-Check-Proposal | 41 |
| `are-evidence.schema.json` | ARE-Evidence-Einreichung | 40 |
| `are-gate-result.schema.json` | ARE-Gate-Prüfergebnis | 40 |
| `concept-feedback.schema.json` | Konzept-Feedback-Loop-Ergebnis | 24 |

### 3.3.2 YAML Schemas (Konfiguration)

| Schema | Datei | Owning Chapter |
|--------|-------|---------------|
| Pipeline-Config | `project.yaml` → `PipelineConfig` (Pydantic) | 03 |
| CCAG-Regeln | `.agentkit/ccag/rules/*.yaml` (kanonisch; harness-spezifische Symlinks via Adapter — z. B. `.claude/ccag/rules/` fuer Claude Code; FK-76) → eigenes Schema | 42 |
| Installer-Manifest | `.installed-manifest.json` → eigenes Schema | 50 |

### 3.3.3 Schema-Versionierung

Alle Schemas tragen ein `schema_version`-Feld. Aktuell: `"3.0"`.

**Kompatibilitätsregel:** Schema-Änderungen, die bestehende Felder
entfernen oder umbenennen, erfordern einen Versionssprung (3.0 → 4.0).
Additive Änderungen (neue optionale Felder) sind innerhalb einer
Version erlaubt.

**Validierung:** `agentkit` prüft `schema_version` beim Laden jedes
Artefakts. Unbekannte Versionen → Fehler (fail-closed).

### 3.3.4 Zwei Versionierungsbereiche

Es gibt zwei unabhängige Versionierungsbereiche mit jeweils eigener
Strategie:

| Bereich | Feld | Aktuell | Migrationsstrategie |
|---------|------|---------|-------------------|
| **Pipeline-Config** (`project.yaml`) | `config_version` | `"3.0"` | SemVer (Major/Minor), automatische Migration durch Installer (siehe 3.5) |
| **QA-Artefakte** (alle JSON-Envelopes) | `schema_version` | `"3.0"` | Nur Major-Sprünge. Alte Artefakte werden nicht migriert — sie gehören zu abgeschlossenen Stories und bleiben unverändert. Neue Stories erzeugen Artefakte mit der aktuellen Version. |

Config-Version und Schema-Version können unterschiedliche Werte haben
(z.B. Config 4.0, Artefakte noch 3.0). Die Artefakt-Version ändert
sich nur, wenn sich die Envelope-Struktur oder ein Stage-spezifisches
Schema strukturell ändert.

## 3.4 Defaulting-Strategie

### 3.4.1 Allgemeine Regel

Fehlende Konfigurationsfelder werden fail-closed behandelt:

| Kontext | Fehlend → Default |
|---------|------------------|
| Feature-Flags | `false` (Feature deaktiviert) |
| Multi-LLM | `true` (Pflicht) |
| Modus-Ermittlung Story-Attribute | Exploration Mode (restriktiver Pfad) |
| Schwellenwerte | Pydantic-Default (dokumentiert) |
| required_stages | Mindestens `structural` (blocking) |
| llm_roles | Fehler bei `multi_llm: true` — kein Default für Rollenzuordnung |
| orchestrator_guard Pfade | Leere Liste → Guard ist effektiv deaktiviert → Warnung |
| ARE-Konfiguration | `are.enabled: false` — ARE entfällt komplett, kein Fehler |
| ARE MCP-Server | Fehler wenn `are.enabled: true` aber kein `mcp_server` konfiguriert |

### 3.4.2 Schwellenwerte mit Defaults

| Parameter | Default | Config-Pfad | FK-Referenz |
|-----------|---------|-------------|-------------|
| Similarity-Schwellenwert VektorDB | 0.7 | `vectordb.similarity_threshold` | FK-05-018 |
| Max LLM-Kandidaten VektorDB | 5 | `vectordb.max_llm_candidates` | FK-05-020 |
| Web-Call-Limit (nur Research) | 200 | `telemetry.web_call_limit` | FK-08-019 |
| Web-Call-Warnung | 180 | `telemetry.web_call_warning` | FK-08-019 |
| Policy Major-Threshold | 3 | `policy.major_threshold` | FK-05-209 |
| Max Feedback-Runden | 3 | `policy.max_feedback_rounds` | — |
| LLM-Retry pro Check | 1 | fest im Code | FK-05-163 |
| Max LLM-Aufrufe pro Check | 2 | fest im Code (1 Versuch + 1 Retry) | FK-05-163 |
| Structural Check: Min Protocol-Größe | 50 Bytes | fest im Code | — |
| Structural Check: Min Structural-Größe | 500 Bytes | fest im Code | FK-06-077 |
| Structural Check: Min Check-Anzahl | 5 | fest im Code | FK-06-077 |
| Integrity Gate: Min Decision-Größe | 200 Bytes | fest im Code | FK-06-078 |
| Governance-Beobachtung: Risikoscore-Schwelle | 30 | `governance.risk_threshold` | — |
| Governance-Beobachtung: Window-Breite | 50 Events | `governance.window_size` | — |
| Governance-Beobachtung: Cooldown | 300 Sekunden | `governance.cooldown_s` | FK-06-128 |
| Incident-Aufnahmeschwelle: Rework-Zeit | 30 Minuten | fest im Code | FK-10-016 |
| Pattern-Promotion: Wiederholung | 3 Incidents / 30 Tage | fest im Code | FK-10-032 |
| Check-Deaktivierung: Zeitraum | 90 Tage | fest im Code | FK-10-080 |
| Check-Deaktivierung: Min False Positives | 3 | fest im Code | FK-10-080 |
| Review-Häufigkeit XS/S | 1 Review | im Worker-Prompt | FK-05-119 |
| Review-Häufigkeit M | 2 Reviews | im Worker-Prompt | FK-05-120 |
| Review-Häufigkeit L/XL | 3+ Reviews | im Worker-Prompt | FK-05-121 |
| LLM-Bewertung: Max Description-Länge | 300 Zeichen | im LLM-Prompt + Validierung | FK-05-158 |

## 3.5 Konfigurationsänderungen und Migration

### 3.5.1 Versionierungsstrategie

`config_version` in `project.yaml` folgt Semantic Versioning
auf Major.Minor-Ebene:

| Änderung | Versionssprung | Migrationsbedarf |
|----------|---------------|-----------------|
| Neues optionales Feld mit Default | Minor (3.0 → 3.1) | Nein |
| Neues Pflichtfeld | Major (3.0 → 4.0) | Ja |
| Feld umbenannt/entfernt | Major (3.0 → 4.0) | Ja |
| Feld-Typ geändert | Major (3.0 → 4.0) | Ja |

### 3.5.2 Migration bei Upgrade

Der Installer (Kapitel 50/51) erkennt die bestehende `config_version`
und führt bei Major-Sprüngen eine automatische Migration durch:

1. Bestehende `project.yaml` lesen
2. Felder gemäß Migrationstabelle umbenennen/konvertieren
3. Neue Pflichtfelder mit dokumentierten Defaults befüllen
4. `project.yaml.bak` als Backup schreiben
5. Neue Version schreiben

Nutzerseitige Anpassungen (Werte, die vom Default abweichen) werden
erkannt und erhalten. Nur strukturelle Änderungen werden migriert.

---

*FK-Referenzen: FK-04-018/020 (Multi-LLM Pflicht + Konfiguration),
FK-05-018/020 (VektorDB-Schwellenwerte), FK-06-044/045 (Modus-Felder,
fail-closed), FK-08-019/025 (Web-Call-Budget), FK-11-006/008
(Idempotenz, Anpassungsschutz)*
