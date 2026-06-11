# Analysis — Skill-Bundle Placeholder-Token-Vokabular vs. Konzept/Code

**Typ:** Read-only Konzept-Investigation (Finding-Dokument, KEINE Story, KEINE Code-Änderung)
**Datum:** 2026-06-11
**Autor:** Sub-Agent (Konzept-Investigation)
**Status:** Befund vorgelegt — Entscheidungen offen für Konzept-/Human-Owner

---

## TL;DR (wichtigster Befund zuerst)

Die ausgelieferten Skill-Bundles (`src/agentkit/resources/skill_bundles/*/*/SKILL.md`)
verwenden **~50 distinkte `{{UPPERCASE_TOKEN}}`-Platzhalter**. Das Konzept-Korpus
(`concept/`) definiert **genau VIER** Platzhalter — und zwar **lowercase**:
`{{gh_owner}}`, `{{gh_repo}}`, `{{project_key}}`, `{{project_prefix}}` (FK-43 §43.2.3
und §43.4.2). **Alle übrigen ~46 Tokens — inkl. der kompletten UPPERCASE-Schreibweise,
inkl. `{{GH_CONFIG_EXPORT}}`, `{{PROJECT_CODEBASE_ROOT}}`, `{{CONCEPTS_DIR}}`,
sämtlicher `{{GH_FIELD_*}}`/`{{GH_*_OPTION}}`, `{{DOD_*}}`, `{{USERSTORY_BUNDLE_PATH}}`,
`{{AGENT_SPAWN_SKILL_PROOF}}` (nur im Code, nicht im Konzept) — sind im
Konzept-Korpus NICHT definiert.** Es existiert keine Namenskonvention, keine
Token→Source-Tabelle, keine Resolution-/Timing-Spezifikation für diese Tokens.

**Das ist primär eine Konzept-Authoring-Lücke, nicht nur eine Implementierungslücke.**
Solange das Vokabular nicht im Konzept definiert ist, gibt es kein autoritatives
Zielbild, gegen das eine Implementierung (Substitutor, Registry, Config-Sources)
geschnitten werden könnte. Konzept-Authoring (FK-03 und/oder FK-43, ggf. FK-12)
muss der Implementierung **vorausgehen**.

**Sekundärbefund (Code):** Der heutige `PlaceholderSubstitutor`
(`src/agentkit/skills/placeholder.py`) kennt 5 Tokens (4 FK-03 + `AGENT_SPAWN_SKILL_PROOF`)
und ist **fail-closed-raise** auf jedes unbekannte Token. Der AG3-111-Materialisierungs-Pfad
(`src/agentkit/skills/materialize.py`) ruft `substitute_spawn_header` über JEDE `.md`
des Bundles auf — d.h. **die ausgelieferten Bundles können heute nicht gebunden werden:
`_materialize_variant_tree` würde an der ersten `.md` mit einem unbekannten Token
mit `UnknownPlaceholderError` abbrechen** (Install-Abbruch, fail-closed).

---

## 1. Vollständiges Token-Inventar

Quelle: alle 8 ausgelieferten `SKILL.md` (kein anderer Bundle-Dateityp enthält Tokens —
die `manifest.json` der Bundles sind tokenfrei, verifiziert per Grep).
Zählung = Gesamtvorkommen über alle Bundles.

### Gruppe A — Projekt-Identität
| Token | Count | Bundle(s) | FK-03-Mapping |
|---|---|---|---|
| `{{PROJECT_PREFIX}}` | 31 | create-userstory-core, execute-userstory-core, lookup-userstory-core | UPPERCASE-Variante von FK-43 `{{project_prefix}}` (`config.project_prefix`) |
| `{{PROJECT_NAME}}` | 2 | create-userstory-core, lookup-userstory-core | **kein** FK-03-Feld (`project_key`? Display-Name? undefiniert) |

> Hinweis: `{{project_key}}` / `{{gh_repo}}` (die zwei restlichen FK-03-Tokens) kommen
> in den Bundles in lowercase **gar nicht** vor; das Bundle nutzt stattdessen
> `{{GH_REPO_PRIMARY}}` (Gruppe C) und keinen `project_key`-Token.

### Gruppe B — Repo-Layout / Verzeichnisse
| Token | Count | Bundle(s) | Quelle (vermutet) |
|---|---|---|---|
| `{{PROJECT_CODEBASE_ROOT}}` | 41 | create-userstory-core, execute-userstory-core (indirekt via spawn-Template) | Projekt-Root-Pfad — **kein FK-03-Feld** |
| `{{CONCEPTS_DIR}}` | 15 | create-userstory-core | Konzept-Verzeichnis — **kein FK-03-Feld** (FK-03 kennt nur `wiki_stories_dir`, `guardrails_dir`) |
| `{{WIKI_STORIES_DIR}}` | 5 | create-userstory-core, lookup-userstory-core | entspricht FK-03 `wiki_stories_dir` — aber NICHT als Platzhalter in FK-43 gemappt |
| `{{WIKI_STORIES_INDEX}}` | 1 | lookup-userstory-core | abgeleiteter Pfad — **kein FK-03-Feld** |
| `{{GH_REPO_LOCAL_PATH}}` | 2 | lookup-userstory-core | lokaler Repo-Pfad (FK-03 `repositories[].path`?) — nicht gemappt |
| `{{REPO_LAYOUT_TABLE}}` | 1 | lookup-userstory-core | generierte Tabelle aus `repositories` — **kein FK-03-Feld** |
| `{{STORY_SPEC_PATH}}` | 1 | create-userstory-core | Pfad zur Story-Spec — **kein FK-03-Feld** |
| `{{USERSTORY_BUNDLE_PATH}}` | 14 | create-userstory-core, execute-userstory-core | Pfad zum gebundenen Skill-Bundle (Self-Reference) — **kein FK-03-Feld** |
| `{{MODULES_EXAMPLE}}` | 3 | create-userstory-core | Beispieltext für Module — **kein FK-03-Feld** |

### Gruppe C — GitHub Config / Project-Identifikatoren
| Token | Count | Bundle(s) | Quelle (vermutet) |
|---|---|---|---|
| `{{GH_OWNER}}` | 13 | create-userstory-core, lookup-userstory-core | UPPERCASE-Variante von FK-43 `{{gh_owner}}` (`config.github_owner`) |
| `{{GH_REPO_PRIMARY}}` | 8 | create-userstory-core | sinngemäß FK-43 `{{gh_repo}}` (`config.repositories[0].name`) — anderer Name |
| `{{GH_CONFIG_EXPORT}}` | 12 | create-userstory-core, lookup-userstory-core | **Shell-Export-Block** (z.B. `export GH_TOKEN=…`) — **kein FK-03-Feld, kein Konzept** |
| `{{GH_PROJECT_ID}}` | 13 | create-userstory-core | GitHub Project (V2) Node-ID — **kein FK-03-Feld** |
| `{{GH_PROJECT_NUMBER}}` | 4 | create-userstory-core, lookup-userstory-core | GitHub Project Number — **kein FK-03-Feld** |

### Gruppe D — GitHub Field-IDs (Project-V2 Custom-Field-Node-IDs)
Alle Count 1, alle nur in **create-userstory-core**. Keiner im Konzept definiert.
`{{GH_FIELD_STORY_TYPE_ID}}`, `{{GH_FIELD_STORY_ID_ID}}`, `{{GH_FIELD_STATUS_ID}}`,
`{{GH_FIELD_SIZE_ID}}`, `{{GH_FIELD_PRIMARY_REPO_ID}}`,
`{{GH_FIELD_PARTICIPATING_REPOS_ID}}`, `{{GH_FIELD_NEW_STRUCTURES_ID}}`,
`{{GH_FIELD_MODULE_ID}}`, `{{GH_FIELD_EPIC_ID}}`, `{{GH_FIELD_CREATED_AT_ID}}`,
`{{GH_FIELD_CONCEPT_QUALITY_ID}}`, `{{GH_FIELD_CHANGE_IMPACT_ID}}`,
plus die Render-Hilfe `{{GH_PROJECT_FIELDS_TABLE}}`.

> Diese korrespondieren fachlich mit den Story-Attributen aus **FK-03 Ebene 3**
> (`Status`, `Story Type`, `Size`, `Change Impact`, `New Structures`,
> `Concept Quality`, `Module` …) — aber FK-03 modelliert diese als
> **Story-Backend-Attribute**, NICHT als GitHub-Project-Field-Node-IDs und
> ausdrücklich NICHT als Skill-Platzhalter.

### Gruppe E — GitHub Option-IDs (Single-Select-Option-Node-IDs)
Alle Count 1, alle nur in **create-userstory-core**. Keiner im Konzept definiert.
Story-Type: `{{GH_STORY_TYPE_RESEARCH_OPTION}}`, `…_IMPLEMENTATION_OPTION}}`,
`…_CONCEPT_OPTION}}`, `…_BUGFIX_OPTION}}`.
Status: `{{GH_STATUS_BACKLOG_OPTION}}`, `{{GH_STATUS_APPROVED_OPTION}}`.
New-Structures: `{{GH_NEW_STRUCTURES_TRUE_OPTION}}`, `…_FALSE_OPTION}}`.
Concept-Quality: `{{GH_CONCEPT_QUALITY_HIGH_OPTION}}`, `…_MEDIUM_OPTION}}`, `…_LOW_OPTION}}`.
Change-Impact: `{{GH_CHANGE_IMPACT_LOCAL_OPTION}}`, `…_COMPONENT_OPTION}}`,
`…_CROSS_COMPONENT_OPTION}}`, `…_ARCHITECTURE_IMPACT_OPTION}}`.

### Gruppe F — Definition of Done (Template-Blöcke)
Alle Count 1, nur **create-userstory-core**: `{{DOD_FEATURE}}`, `{{DOD_BUGFIX}}`,
`{{DOD_CONCEPT}}`, `{{DOD_RESEARCH}}`. (Keine Pipe-Syntax wie `{{DOD_X|Y}}` im Bundle —
es sind vier separate Tokens.) Keiner im Konzept definiert.

### Gruppe G — Guardrails
| Token | Count | Bundle(s) | Quelle (vermutet) |
|---|---|---|---|
| `{{GUARDRAIL_REFS}}` | 4 | create-userstory-core | gerenderte Guardrail-Referenzliste aus FK-03 `guardrails_dir`/`guardrails_pattern` — **kein FK-03-Platzhalter** |

### Gruppe H — Spawn-Proof (manifest-fed)
| Token | Count | Bundle(s) | Quelle |
|---|---|---|---|
| `{{AGENT_SPAWN_SKILL_PROOF}}` | 5 | execute-userstory-core | **Installed-Manifest** (`.installed-manifest.json` → `agent_spawn_skill_proof`), AG3-110/FK-31 §31.7.4. **Im Code definiert, im Konzept-Korpus als Platzhalter NICHT in FK-43 §43.2.3/§43.4.2 gelistet** (FK-43 nennt nur die 4 FK-03-Tokens). |

**Summe:** 50 distinkte Tokens. Vier Bundles tragen Tokens
(create-userstory-core: 46 distinkt; execute-userstory-core: 3;
lookup-userstory-core: 9; Überschneidungen z.B. `PROJECT_PREFIX`).
Die `-are`-Varianten, `llm-discussion-core`, `manage-requirements-core`,
`semantic-review-core` SKILL.md sind **tokenfrei**.

---

## 2. Per-Token intendierte Quelle (laut Konzept)

### Was das Konzept tatsächlich definiert (FK-43 §43.2.3, verbatim)

> „Skills können Platzhalter enthalten, die beim Binden eines Projekts aus der
> Projektkonfiguration substituiert oder zur Laufzeit aufgelöst werden (Kap. 50):
>
> | `{{gh_owner}}` | GitHub-Owner aus Config (Code-Backend) |
> | `{{gh_repo}}` | GitHub-Repo aus Config … |
> | `{{project_key}}` | AK3-Project-Schluessel aus `project.yaml` … |
> | `{{project_prefix}}` | Story-ID-Prefix aus `project.yaml` |"

FK-43 §43.4.2 (verbatim) bestätigt dieselben 4 und bindet sie an FK-03:

> „`PlaceholderSubstitutor` substituiert Werte aus `PipelineConfig` (BC foundation,
> FK-03). … Die substituierten Felder stammen ausschliesslich aus FK-03:
> `{{gh_owner}}`→`config.github_owner`, `{{gh_repo}}`→`config.repositories[0].name`,
> `{{project_prefix}}`→`config.project_prefix`, `{{project_key}}`→`config.project_key`.“

Der mitgelieferte Code-Block in FK-43 §43.4.2 zeigt exakt diese vier Replacements
und nichts weiter.

### Mapping der Bundle-Tokens auf autoritative Quellen

| Token-Gruppe | Autoritative Quelle laut Konzept | Install-time vs. Runtime | Befund |
|---|---|---|---|
| A `{{PROJECT_PREFIX}}` | FK-03 `config.project_prefix` (als `{{project_prefix}}`) | **Install-time** (FK-03 Ebene 2, bei Bind bekannt) | Nur Case/Name weicht ab |
| A `{{PROJECT_NAME}}` | **undefiniert** (kein FK-03-Feld) | unklar | Konzept-Lücke |
| B `{{WIKI_STORIES_DIR}}` | FK-03 `wiki_stories_dir` (existiert in YAML, §3.1) | Install-time möglich | **nicht** als Platzhalter in FK-43 gemappt |
| B übrige (`PROJECT_CODEBASE_ROOT`, `CONCEPTS_DIR`, `USERSTORY_BUNDLE_PATH`, `STORY_SPEC_PATH`, `REPO_LAYOUT_TABLE`, `MODULES_EXAMPLE`, `WIKI_STORIES_INDEX`, `GH_REPO_LOCAL_PATH`) | **undefiniert** | teils install-time ableitbar (Pfade), teils generiert | Konzept-Lücke |
| C `{{GH_OWNER}}`, `{{GH_REPO_PRIMARY}}` | FK-03 `github_owner` / `repositories[0].name` (als `{{gh_owner}}`/`{{gh_repo}}`) | **Install-time** | Nur Case/Name weicht ab |
| C `{{GH_CONFIG_EXPORT}}`, `{{GH_PROJECT_ID}}`, `{{GH_PROJECT_NUMBER}}` | **undefiniert** — kein FK-03-Feld, kein FK-12-Platzhalter | GH_PROJECT_* evtl. install-time via GitHub-API; GH_CONFIG_EXPORT = Secret-Handling | Konzept-Lücke; **Secret-Hygiene-Risiko** (vgl. FK-03 „Kein Inline-Token“) |
| D `{{GH_FIELD_*_ID}}` | **undefiniert** — GitHub Project-V2-Node-IDs | install-time (einmalig via GitHub-API ermittelbar) ODER setup-time | Konzept-Lücke; fachlich an FK-03 Ebene-3-Attribute angelehnt, aber nicht modelliert |
| E `{{GH_*_OPTION}}` | **undefiniert** — Single-Select-Option-Node-IDs | install-time/setup-time | Konzept-Lücke |
| F `{{DOD_*}}` | **undefiniert** — DoD-Template-Blöcke | install-time (statischer Content) ODER Bundle-intern | Konzept-Lücke |
| G `{{GUARDRAIL_REFS}}` | abgeleitet aus FK-03 `guardrails_dir`/`guardrails_pattern` | install-time generierbar | nicht als Platzhalter modelliert |
| H `{{AGENT_SPAWN_SKILL_PROOF}}` | Installed-Manifest (AG3-110/FK-31 §31.7.4) — im Code, nicht in FK-43-Platzhaltertabelle | **Install/Read-time aus Manifest** | im Code modelliert; FK-43-Tabelle nicht nachgezogen |

**Kernpunkt zu „install-time vs. runtime“:** Das Konzept (FK-43 §43.2.3) lässt
ausdrücklich BEIDE Timing-Modi zu („beim Binden … substituiert **oder** zur Laufzeit
aufgelöst“). Es legt aber **pro Token kein Timing fest** — nur die 4 FK-03-Tokens sind
überhaupt benannt, und für die ist die Quelle install-time-bekannt
(`project.yaml`/`PipelineConfig`). Für die ~46 Bundle-Tokens gibt es **keine
konzeptionelle Timing-Zuordnung**, weil sie konzeptionell nicht existieren.

---

## 3. Case- und Naming-Mismatch — Konzept-Authoring-Lücke

**Es gibt im Konzept-Korpus KEINE dokumentierte Namenskonvention für diese Tokens.**

- FK-43 §43.2.3 und §43.4.2 verwenden durchgängig **lowercase**:
  `{{gh_owner}}`, `{{gh_repo}}`, `{{project_key}}`, `{{project_prefix}}`.
- Die Bundles verwenden durchgängig **UPPERCASE** und führen ~46 zusätzliche Tokens.
- Verifiziert per präzisem Grep über `concept/`: die exakten Strings
  `PROJECT_CODEBASE_ROOT`, `GH_CONFIG_EXPORT`, `CONCEPTS_DIR`, `GH_PROJECT_ID`,
  `GH_FIELD_STORY_TYPE`, `PROJECT_PREFIX`, `GH_OWNER`, `USERSTORY_BUNDLE_PATH`,
  `WIKI_STORIES_DIR` liefern **null Treffer** im Konzept-Korpus.
- FK-12 (GitHub-Integration) definiert **kein** Platzhalter-/Config-Export-Vokabular;
  es deferiert GitHub-Config explizit an FK-03 (`defers_to: FK-03|configuration`).
  FK-03 modelliert nur YAML-Felder und Story-Attribute — keine Skill-Platzhalter,
  keine GitHub-Project-Field/Option-Node-IDs, keinen `GH_CONFIG_EXPORT`-Shell-Block.

**Schlussfolgerung:** Das Token-Vokabular der Bundles ist **ausschließlich in den
Bundle-Dateien vorhanden** und im Konzept-Korpus **undokumentiert**. Das ist eine
**Konzept-Authoring-Lücke** (kein Owner für Vokabular, Naming, Quellen, Timing) —
nicht bloß ein nachzuziehender Implementierungsdetail. Es verstößt zudem gegen die
CLAUDE.md-Guardrails „kein operatives Vokabular ohne Owner“ und „typisierte Artefakte/
Quellen statt loser String-Konventionen“.

---

## 4. Resolution-Mechanismus — Intent vs. Code-Realität

### Was das Konzept zum Mechanismus sagt
- **Zwei Bind-Modi (FK-43 §43.4.1 / §43.4.1.1):** Standard = reiner Link auf das
  zentrale Bundle (keine Substitution; `project_binding_is_link_only`). Materialisierte
  Variante = der Installer erzeugt eine **substituierte Kopie** im AK3-Install-Bereich
  und linkt den Harness-Bindungspunkt auf diese Variante. FK-43 §43.4.1.1 verbatim:
  „erzeugt der Installer **substituierte Varianten** im AK3-Installationsverzeichnis
  und linkt diese in den jeweiligen Harness-Skill-Pfad. Substitution arbeitet auf einer
  **neutralen Skill-Repräsentation** im Bundle …“
- **Substitution = simples String-Replace, keine Template-Engine** (FK-43 §43.4.2:
  „Einfaches String-Replace, keine Template-Engine.“).
- **Runtime-Auflösung** ist konzeptionell zugelassen (FK-43 §43.2.3 „oder zur Laufzeit
  aufgelöst“) und würde über FK-44 (`PromptRuntime.materialize_prompt`) bzw. den Harness
  laufen — aber FK-43 spezifiziert **nicht**, welche Tokens runtime-aufgelöst werden.

### Was „fail-closed-on-unknown“ konzeptionell impliziert
Die Konzept-Quelle FK-43 §43.4.2 listet abschließend genau 4 Tokens; der Code hat
daraus eine **fail-closed-raise**-Semantik gemacht (jedes nicht-gelistete Token →
`UnknownPlaceholderError`). Das ist korrekt FÜR die 4 Konzept-Tokens, **kollidiert aber
mit dem realen Bundle-Vokabular**:

- Wenn der Substitutor ALLE Tokens kennen muss (heutige Semantik), dann müssen alle
  ~50 Tokens eine autoritative install-time-Quelle haben — das setzt voraus, dass
  KEINER der Tokens runtime-only ist.
- Wenn dagegen ein Teil der Tokens **runtime/per-story** ist (z.B. `{ISSUE_NUMBER}`-artige
  Werte — die im Bundle als `{…}` einfach-geschweift, NICHT `{{…}}` doppelt stehen, also
  bewusst NICHT als AK3-Platzhalter gemeint sind), dann müsste der Install-Substitutor
  **known-subset-substitution** machen (bekannte Tokens ersetzen, unbekannte intakt
  lassen) — das **widerspricht** der heutigen fail-closed-raise-Implementierung.

**Beobachtung zum `{{…}}`-vs-`{…}`-Schnitt:** Die Bundles nutzen `{{DOUBLE}}` für
AK3-Substitution und `{SINGLE}` (z.B. `{ISSUE_NUMBER}`, `{STORY_ID}`, `{path}`) für
runtime/agent-lokale Werte. Das ist ein impliziter, **nirgends im Konzept dokumentierter**
Schnitt: `{{…}}` = AK3-aufzulösen, `{…}` = Agent/Runtime. Diese Konvention müsste das
Konzept explizit machen.

### Code-Realität (Sekundärbefund, belegt)
- `src/agentkit/skills/placeholder.py:38-49` — `_MANDATORY_PLACEHOLDERS` = exakt die 4
  FK-03-Tokens; `SPAWN_SKILL_PROOF_PLACEHOLDER` als 5. (manifest-fed).
- `placeholder.py:187-202` (`_apply`) — jedes nicht-gemappte `{{\w+}}` → `raise
  UnknownPlaceholderError` (**fail-closed-raise**, kein known-subset-pass-through).
- `src/agentkit/skills/materialize.py:112-141` (`_materialize_variant_tree`) — ruft für
  JEDE `.md` `substitutor.substitute_spawn_header(...)` auf. Bei den ausgelieferten
  Bundles (z.B. `create-userstory-core` mit `{{PROJECT_CODEBASE_ROOT}}` u.v.m.) bricht
  das beim ersten unbekannten Token ab. `materialize.py:248-251` + `288-318` →
  Install-Abbruch + Rollback der Variante.
- **Effekt:** Der dokumentierte „materialisierte Bind-Modus“ ist mit dem realen
  Bundle-Inhalt **strukturell inkompatibel**. Ein End-to-End-Bind der mitgelieferten
  Pflicht-Skills (`create-userstory-core`, `execute-userstory-core`,
  `lookup-userstory-core`) ist heute nicht möglich.

---

## 5. Scope-Form für die zukünftige Story (Empfehlung, KEINE Story)

Eine konzepttreue Lösung braucht — in dieser Reihenfolge — folgende Bausteine.
**Konzept-Authoring zuerst**, sonst gibt es kein autoritatives Zielbild
(CLAUDE.md: „Feasibility zuerst / Konzepttreue ist Pflicht / Fehlende Infos → stoppen“).

### 5.1 Konzept-Authoring (MUSS vorausgehen)
1. **Token-Vokabular normieren** (FK-43 §43.2.3/§43.4.2 erweitern, ggf. FK-03 für
   neue Config-Quellen): vollständige Token→Source-Tabelle für ALLE ~50 Tokens;
   verbindliche Namenskonvention (Case-Frage UPPERCASE vs. lowercase entscheiden und
   Bundles ODER Konzept angleichen — **eine** Schreibweise).
2. **Timing pro Token festlegen:** install-time (aus `project.yaml`/`PipelineConfig`)
   vs. install-time-aus-GitHub-API (Field/Option-Node-IDs, Project-IDs) vs.
   runtime/per-story (falls überhaupt vorhanden) vs. statischer Bundle-Content (DoD).
3. **`{{…}}`-vs-`{…}`-Konvention** explizit dokumentieren.
4. **GitHub-Field/Option-Node-IDs** als eigenen Quell-Owner modellieren: woher kommen
   sie (GitHub-Project-V2-API-Abfrage zur Install-/Setup-Zeit?), wo werden sie
   persistiert (Installed-Manifest? eigene Config-Sektion?). Aktuell gibt es dafür
   keinen Owner — das ist genau das v2-Antipattern, das CLAUDE.md verbietet.
5. **`{{GH_CONFIG_EXPORT}}` / Secret-Hygiene** klären: FK-03 verbietet Inline-Tokens
   ausdrücklich. Ein Shell-`export`-Block in Skills darf keine Secrets materialisieren.

### 5.2 Implementierung (NACH Konzept)
6. **Token→Source-Registry** (typisiert, Pydantic, ein Owner) statt String-Kaskade.
7. **Substitutor-Semantik entscheiden:** entweder (a) ALLE Tokens install-time-resolvbar
   → Registry liefert für jeden Wert eine Quelle, fail-closed bleibt korrekt; oder
   (b) gemischtes Timing → Substitutor von **fail-closed-raise** auf
   **known-subset-substitution** umstellen (install-bekannte ersetzen, runtime-Tokens
   intakt lassen), mit fail-closed **nur** für deklariert-install-time-Tokens, die
   nicht auflösbar sind. Diese Änderung berührt `placeholder.py` UND `materialize.py`
   und braucht Negativpfad-Tests an der Bind-Grenze (testing-guardrails).
8. **Config-Sources verdrahten:** `PipelineConfig`/`ProjectConfig` (vorhanden),
   abgeleitete Pfade (`PROJECT_CODEBASE_ROOT`, `CONCEPTS_DIR`, `USERSTORY_BUNDLE_PATH`),
   GitHub-API-Projektion (Field/Option-IDs, Project-IDs), Installed-Manifest
   (`AGENT_SPAWN_SKILL_PROOF`, evtl. GitHub-IDs).
9. **Render-Tokens** (`GH_PROJECT_FIELDS_TABLE`, `REPO_LAYOUT_TABLE`, `GUARDRAIL_REFS`,
   `DOD_*`, `MODULES_EXAMPLE`) als generierte Blöcke definieren — Producer + Owner klären.

### 5.3 Offene Entscheidungen für Human/Konzept-Owner
- **D1 — Schreibweise:** UPPERCASE (Bundles anpassen oder Konzept) vs. lowercase
  (Bundles auf FK-43 angleichen)? Eine Wahrheit.
- **D2 — Quelle der GitHub-Field/Option-Node-IDs:** Install-time GitHub-API-Abfrage?
  Setup-time? Manuelle Config? Wer ownt die Persistenz?
- **D3 — Substitutor-Timing-Modell:** „alles install-time, fail-closed bleibt“ vs.
  „known-subset, runtime-Tokens pass-through“. Entscheidet, ob `placeholder.py`/
  `materialize.py` geändert werden müssen.
- **D4 — `GH_CONFIG_EXPORT`-Inhalt & Secret-Hygiene:** Was genau exportiert dieser
  Block, und wie ohne Inline-Secret (FK-03-Konflikt)?
- **D5 — Bundle-Korrektheit:** Sind die ~46 Tokens überhaupt das gewollte Zielbild,
  oder sind die Bundles aus v2/extern übernommen und müssen fachlich neu geschnitten
  werden? (Wenn übernommen → Bundles sind die zu korrigierende Seite, nicht das Konzept.)
- **D6 — `{{…}}`-vs-`{…}`-Schnitt:** verbindlich machen oder anders lösen.

---

## Belegliste (Datei:Zeile / Konzept-ID §)

- **Token-Inventar:** alle `src/agentkit/resources/skill_bundles/*/4.0.0/SKILL.md`
  (Grep über `\{\{[A-Za-z0-9_|]+\}\}`); Manifeste tokenfrei.
- **Beispiel-Verwendung:** `…/create-userstory-core/4.0.0/SKILL.md:19, 58, 179, 209,
  583-585, 633-636, 1006-1009`; `…/lookup-userstory-core/4.0.0/SKILL.md:67-68, 92-93`.
- **4-Token-Konzept:** FK-43 §43.2.3 (`technical-design/43_…md`, Anchor
  `vorgehen-004`) und §43.4.2 (Anchor `43-4-…-006`).
- **FK-03-Config-Felder:** FK-03 §3.1 (`project.yaml`-YAML inkl. `project_key`,
  `project_prefix`, `github_owner`, `repositories`, `wiki_stories_dir`,
  `guardrails_dir`); §3.1 Ebene 3 (Story-Attribute Status/Story Type/Size/…);
  „Kein Inline-Token“ in der SonarQube-Stanza (Secret-Hygiene-Präzedenz).
- **FK-12 deferiert GitHub-Config an FK-03** (`defers_to_edges: FK-03|configuration`),
  definiert KEIN Platzhalter-Vokabular.
- **Substitutor (Code):** `src/agentkit/skills/placeholder.py:35-49, 79-100, 144-161,
  187-202` (fail-closed-raise, 4+1 Tokens).
- **Materialisierung (Code, AG3-111):** `src/agentkit/skills/materialize.py:80-96,
  112-141, 193-318` (ruft `substitute_spawn_header` über alle `.md`; bricht bei
  unbekanntem Token ab + rollt zurück).
- **Konzept-Korpus enthält die UPPERCASE-Tokens NICHT:** präziser Grep über `concept/`
  → null Treffer für `PROJECT_CODEBASE_ROOT|GH_CONFIG_EXPORT|CONCEPTS_DIR|GH_PROJECT_ID|
  GH_FIELD_STORY_TYPE|PROJECT_PREFIX|GH_OWNER|USERSTORY_BUNDLE_PATH|WIKI_STORIES_DIR`.
