# agent-skills — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `agent-skills` |
| Display-Name | `Agent-Skills` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-01`, `DK-12`, `FK-43`, `formal.skills-and-bundles.entities`, `formal.skills-and-bundles.state-machine`, `formal.skills-and-bundles.commands`, `formal.skills-and-bundles.events`, `formal.skills-and-bundles.invariants`, `formal.skills-and-bundles.scenarios` |
| Codebase-Hauptpfade | kein `src/agentkit/skills/` vorhanden; einzig relevante Beruehrung: `src/agentkit/installer/runner.py` |

## 1. Executive Summary

Der BC `agent-skills` ist in der Codebase nahezu vollstaendig absent. Es existiert weder das vorgeschriebene Modul `src/agentkit/skills/` noch eine der ~20 Klassen (`Skills`, `SkillManager`, `SkillBundleStore`, `SkillBinding`, `SkillQualityMetric`, `PlaceholderSubstitutor` usw.), die das Konzept fordert. Der Installer legt das Verzeichnis `.claude/skills/` als leeren Platzhalter an und entfernt es beim Deinstallieren — jedoch ohne jede Symlink-Bindungslogik. Alle formalen Entitaeten, State-Machine-Zustaende, Commands, Events und Invarianten aus `formal.skills-and-bundles.*` sind unimplementiert. Der BC ist der einzige der 16 geschnittenen BCs ohne eigenes Produktionsmodul.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 10 |
| B — Teilweise umgesetzt | 1 |
| C — Drift / Fehler | 2 |

## 2. Konzept-Soll (Kurzfassung)

- **Top-Komponente `Skills` mit vier oeffentlichen Methoden** (`bind_skill`, `resolve_binding`, `list_bound_skills`, `collect_quality_metrics`) als kanonische Schnittstelle — `bc-cut-decisions.md §BC 11`
- **Pflicht-Skills als SKILL.md-Verzeichnisse** (create-userstory-core/are, execute-userstory-core/are, lookup-userstory, llm-discussion) — `FK-43 §43.3.1`
- **Optionale Skills** (manage-requirements, semantic-review) — `FK-43 §43.3.2`
- **Systemweite Bundle-Installation mit Symlink-Bindung** (kein inhaltliches Kopieren ins Projekt) pro Harness (Claude Code `.claude/skills/`, Codex harness-eigenes Aequivalent) — `FK-43 §43.4.1`, `formal.skills-and-bundles.invariants §project_binding_is_symlink_only`
- **Skill-Lifecycle State-Machine** (Requested -> ProfileResolved -> BundleSelected -> Bound -> Verified/Rejected) — `formal.skills-and-bundles.state-machine`
- **PlaceholderSubstitutor** zur Bind-Zeit-Substitution von `{{gh_owner}}`, `{{gh_repo}}`, `{{project_prefix}}`, `{{project_key}}` aus PipelineConfig (read-only) — `FK-43 §43.4.2`
- **SkillBundleStore** als kanonischer systemweiter Store mit Versionierung, Manifest-Digest und Bundle-Pfad-Resolver — `bc-cut-decisions.md §BC 11`
- **Eigenstaendiger Skill-Version-Pin** (unabhaengig von `prompt-runtime.BundlePinning`) mit `SkillBundleStore` als Halter des Records — `FK-43 §43.5.2`
- **SkillQualityMetric** mit Aggregation aus Telemetrie-Projektionen (`Telemetry.ProjectionAccessor`) und Failure-Corpus-Befunden via Experiment-Tags — `FK-43 §43.6.2`
- **F-43-030 Normative Skill-Nutzung**: Agents muessen Pflicht-Skills verwenden; Enforcement-Owner ist `governance.guard_system` Hook `skill_usage_check` — `FK-43 §43.6`, `bc-cut-decisions.md §Skill-Usage-Enforcement`
- **Vollstaendige formale Szenarien** (core-profile-binds-core-variant, are-profile-binds-are-variant, rebind, latest-binding-rejected, copying-canonical-source-rejected) — `formal.skills-and-bundles.scenarios`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/installer/runner.py` — erstellt `.claude/skills/`-Verzeichnis als leere Struktur; entfernt es beim Deinstallieren; keine Symlink-Logik, kein `Skills.bind_skill`-Aufruf
- `src/agentkit/installer/paths.py` — definiert `CLAUDE_DIR` und implizit `.claude/skills/` als Pfadkonstante; kein Skill-spezifischer Pfad-Helper
- `src/agentkit/resources/target_project/.claude/skills/` — leeres Verzeichnis (Platzhalter), keine Symlinks, kein Inhalt
- `tests/contract/scaffold_snapshots/test_install_scaffold.py` — prueft, dass `.claude/skills/` als Verzeichnis existiert; prueft keine Skill-Bindungen oder Symlinks

Kein Modul `src/agentkit/skills/` vorhanden. Keine Klassen `Skills`, `SkillManager`, `SkillBundleStore`, `SkillBinding`, `PlaceholderSubstitutor`, `SkillQualityMetric` implementiert. `src/agentkit/project_ops/install/` enthaelt nur `__pycache__`-Artefakte von Python 3.14 (vermutlich Relikte einer aelteren Entwicklungsphase); keine Quell-.py-Dateien vorhanden.

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Modul `src/agentkit/skills/` mit Top-Komponente `Skills` und oeffentlichen Methoden (`bind_skill`, `resolve_binding`, `list_bound_skills`, `collect_quality_metrics`) | `bc-cut-decisions.md §BC 11` | Kein Produktionsmodul vorhanden; das ist der vollstaendige BC-Kern |
| A2 | `SkillBundleStore` (Sub-1): systemweiter kanonischer Bundle-Store mit Versionierung, Manifest-Digest, Bundle-Pfad-Resolver | `bc-cut-decisions.md §BC 11`, `formal.skills-and-bundles.entities §bundle` | Keine Implementierung; kein analoges Modul zu `prompt-runtime.BundleStore` |
| A3 | `SkillBinding` (Sub-1): Symlink-basierte Projekt-Bindung inkl. Skill-Lifecycle State-Machine (Requested -> ProfileResolved -> BundleSelected -> Bound -> Verified/Rejected) und PlaceholderSubstitutor | `FK-43 §43.4.1`, `formal.skills-and-bundles.state-machine`, `formal.skills-and-bundles.invariants §project_binding_is_symlink_only` | Kein Python-Code; Invariante "nur Symlinks, keine Kopien" existiert formal, wird aber nicht erzwungen |
| A4 | `SkillQualityMetric` (Sub-1): Aggregation aus `Telemetry.ProjectionAccessor` (WorkflowMetric-Daten) und Failure-Corpus-Befunden via Skill-Experiment-Tags | `FK-43 §43.6.2`, `bc-cut-decisions.md §BC 11` | Kein Code; Lese-Schnittstellen zu Telemetrie- und Failure-Corpus-BCs unimplementiert |
| A5 | Pflicht-Skills als SKILL.md-Verzeichnisse (create-userstory-core, create-userstory-are, execute-userstory-core, execute-userstory-are, lookup-userstory, llm-discussion) | `FK-43 §43.3.1` | Keine SKILL.md-Dateien im Repo; `.claude/skills/` ist leer |
| A6 | Optionale Skills als SKILL.md-Verzeichnisse (manage-requirements, semantic-review) | `FK-43 §43.3.2`, `FK-43 §43.3.2 F-43-029` | Fehlend; Semantic-Review-Skill (F-43-029) mit 12 Pruefdimensionen nicht realisiert |
| A7 | Eigenstaendiger Skill-Version-Pin (`SkillBundleStore` als Record-Halter), unabhaengig von `prompt-runtime.BundlePinning` | `FK-43 §43.5.2` | Keine Implementierung; Abgrenzung zu Prompt-Bundle-Pin nicht codiert |
| A8 | Formale Invarianten-Durchsetzung: `profile_selects_one_variant_before_binding`, `bundle_binding_points_to_concrete_version`, `project_local_repo_never_contains_canonical_skill_source`, `live-source-checkout-is-never-a-production-bundle` | `formal.skills-and-bundles.invariants` | Alle sieben formalen Invarianten unimplementiert |
| A9 | Hook `skill_usage_check` in `governance.guard_system` als Enforcement fuer F-43-030 (Normative Skill-Nutzung) | `FK-43 §43.6`, `bc-cut-decisions.md §Skill-Usage-Enforcement` | Kein Hook registriert; `src/agentkit/governance/guard_system/` enthaelt keinen Skill-Bezug |
| A10 | Formale Event-Emittierung (profile.resolved, bundle.selected, binding.applied, binding.verified, binding.rebound, binding.rejected) fuer Auditierbarkeit | `formal.skills-and-bundles.events` | Keine Events implementiert; kein Telemetrie-Aufruf fuer Skill-Lifecycle-Ereignisse |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | `.claude/skills/`-Verzeichnis anlegen und entfernen | `src/agentkit/installer/runner.py:uninstall_agentkit` (Zeile 477), `src/agentkit/resources/target_project/.claude/skills/` | `FK-43 §43.4.1`, `formal.skills-and-bundles.commands §bind-project-skills` | Verzeichnis wird als leerer Platzhalter angelegt; keine Symlink-Erzeugung, kein `Skills.bind_skill`-Aufruf vom Installer, kein Profil-Resolving, keine Bundle-Auswahl; das Verzeichnis existiert strukturell, aber der gesamte Bindungsprozess fehlt |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Installer erstellt `.claude/skills/` direkt, ohne `Skills.bind_skill` aufzurufen | `src/agentkit/installer/runner.py:install_agentkit` | `FK-43 §43.4.1`, `bc-cut-decisions.md §BC 11` ("Top-Surface `Skills.bind_skill` ist die kanonische Schnittstelle der Komponente `Skills`") | Der Installer soll die Top-Surface `Skills.bind_skill` aufrufen — analoges Muster zu `PromptRuntime.update_binding`. Direktes Anlegen des Verzeichnisses durch den Installer ist Architektur-Drift: es umgeht den BC und seine Invarianten |
| C2 | `__pycache__`-Artefakte (`skills.cpython-314.pyc`, `skill_variant.cpython-314.pyc`) in `src/agentkit/project_ops/install/` ohne zugehoerige Quell-py-Dateien | `src/agentkit/project_ops/install/__pycache__/` | `CLAUDE.md §SINGLE SOURCE OF TRUTH IST PFLICHT` | Kompilierte Artefakte ohne Quelle sind ein inkonsistenter Repo-Zustand; deuten auf geloeschten oder nie committeten Quellcode hin. Das ist keine operative Wahrheit und verletzte den Grundsatz "keine losen Artefakte im Repo" |

## 5. Ableitungen / Empfehlungen

1. **`src/agentkit/skills/` Modul anlegen (hoechste Prioritaet):** Der BC hat kein Produktionsmodul. Das ist der vollstaendige fehlende BC-Kern. Ohne dieses Modul koennen weder Installer noch Governance korrekt arbeiten. Startpunkt: Top-Komponente `Skills` mit den vier Top-Surface-Methoden und den drei Sub-1-Komponenten gemaess `bc-cut-decisions.md §BC 11`.
2. **`__pycache__`-Relikte aus `src/agentkit/project_ops/install/` entfernen:** Die `.pyc`-Dateien fuer `skills.py` und `skill_variant.py` ohne Quellcode sind ein Repository-Hygieneproblem und koennen Verwirrung ueber den Implementierungsstand erzeugen. Sie sind kein valider Ersatz fuer Quellcode.
3. **Installer-Architektur korrigieren (Drift C1):** `install_agentkit()` muss `Skills.bind_skill()` aufrufen statt das `.claude/skills/`-Verzeichnis direkt anzulegen. Erst wenn das `skills/`-Modul (Punkt 1) existiert, kann dieser Drift bereinigt werden.
4. **Pflicht-SKILL.md-Dateien erstellen:** `execute-userstory-core`, `create-userstory-core` und `lookup-userstory` sind Pflicht-Skills (FK-43 §43.3.1) und blockieren den End-to-End-Betrieb von Story-Workflows.
5. **Formale Invarianten codieren:** Die sieben Invarianten aus `formal.skills-and-bundles.invariants` (insbesondere `project_binding_is_symlink_only` und `bundle_binding_points_to_concrete_version`) sind die Stabilitaetsgarantien des BC. Sie muessen als Laufzeitpruefungen in `SkillBinding` und `SkillBundleStore` landen.
6. **Governance-Hook `skill_usage_check` implementieren:** F-43-030 ist normativ (Agents *muessen* Skills nutzen), aber nicht durchgesetzt. Ohne den Hook in `governance.guard_system` ist die Norm toter Text.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/01-rollen-und-llm-einsatz.md` (DK-01)
  - `concept/domain-design/12-skills-und-skill-system.md` (DK-12)
  - `concept/technical-design/43_skills_system_task_automation.md` (FK-43)
  - `concept/formal-spec/skills-and-bundles/entities.md`
  - `concept/formal-spec/skills-and-bundles/state-machine.md`
  - `concept/formal-spec/skills-and-bundles/invariants.md`
  - `concept/formal-spec/skills-and-bundles/commands.md`
  - `concept/formal-spec/skills-and-bundles/events.md`
  - `concept/formal-spec/skills-and-bundles/scenarios.md`
  - `concept/technical-design/_meta/domain-registry.yaml` (Eintrag agent-skills)
  - `src/agentkit/installer/runner.py`
  - `src/agentkit/installer/paths.py`
  - `tests/contract/scaffold_snapshots/test_install_scaffold.py`
- **Punktuell via Direktlesen:**
  - `concept/_meta/bc-cut-decisions.md §BC 11` (Offset 998–1077), §Uebergreifende Entscheidungen, §Skill-Bundle-vs-Prompt-Bundle, §Konzept-Refactor-Liste Eintraege 40–45
- **Code-Scan (Glob/Grep):**
  - Pattern `skill|Skill|agent_skills` auf `src/agentkit/**/*.py`: um alle relevanten Python-Dateien zu identifizieren; ergab nur einen Treffer (`installer/runner.py`)
  - Glob `**/skills*` auf `src/agentkit/`: um ein dediziertes Skills-Modul zu finden; nur `__pycache__`-Artefakte ohne Quellcode gefunden
  - Glob `**/*.py` auf `src/agentkit/project_ops/`: ergab keine Quell-py-Dateien in `install/`; bestaetigt fehlenden Quellcode
  - Glob `**/resources/target_project/**` auf `src/agentkit/`: um die deployte Projektstruktur zu inspizieren; `.claude/skills/` als leeres Verzeichnis bestaetigt
  - Pattern `agent-skills|agent_skills` auf `concept/_meta/bc-cut-decisions.md`: um BC-11-Abschnitt und Querbezuege zu lokalisieren
