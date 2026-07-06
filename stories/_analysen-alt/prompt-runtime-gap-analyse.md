# prompt-runtime — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `prompt-runtime` |
| Display-Name | `Prompt-Runtime` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-44, formal.prompt-runtime.entities, formal.prompt-runtime.state-machine, formal.prompt-runtime.commands, formal.prompt-runtime.events, formal.prompt-runtime.invariants, formal.prompt-runtime.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/prompt_composer/` (kein `src/agentkit/prompt_runtime/`) |

## 1. Executive Summary

Der BC `prompt-runtime` existiert noch nicht als eigenstaendiges Paket `src/agentkit/prompt_runtime/`. Die konzeptionell geforderten Subs `BundleStore`, `BundlePinning` und `Materialization` unter dem Modul-Prefix `agentkit.backend.prompt_runtime` sind nicht angelegt. Stattdessen deckt das Paket `src/agentkit/prompt_composer/` grosse Teile der Run-Pinning- und Materialisierungslogik ab, jedoch unter falschem Modul-Prefix, ohne die normierte Top-Surface `PromptRuntime` und ohne Anbindung an `artifacts.ArtifactManager`. Die formale State-Machine mit ihren Zustandsuebergaengen, das typisierte `PromptAuditHash`-Pydantic-Schema sowie die konzeptionelle `reject-stale-local-prompt-cache`-Kommandoebene fehlen vollstaendig.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 7 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **`src/agentkit/prompt_runtime/` als eigenstaendiges Python-Paket mit Top-Klasse `PromptRuntime`** — `bc-cut-decisions.md §BC 10`
- **Top-Surface `PromptRuntime.materialize_prompt(invocation) -> PromptInstance`** — `bc-cut-decisions.md §BC 10`, `FK-44 §44.4`
- **Top-Surface `PromptRuntime.create_run_pin(run_id) -> RunPromptPin`** — `bc-cut-decisions.md §BC 10`, `FK-44 §44.3`
- **Top-Surface `PromptRuntime.update_binding(bundle_id, version) -> None`** — `FK-44 §44.3`, `bc-cut-decisions.md §BC 10`
- **Top-Surface `PromptRuntime.compute_audit_hash(invocation_id, output_bytes) -> PromptAuditHash`** — `bc-cut-decisions.md §BC 10`, `FK-44 §44.6`
- **Sub `agentkit.backend.prompt_runtime.bundle_store`: `BundleStore`, `PromptBundle`, `PromptTemplate`, `BundleVersion`** — `bc-cut-decisions.md §BC 10`
- **Sub `agentkit.backend.prompt_runtime.bundle_pinning`: `BundlePinning`, `ProjectPromptPin`, `RunPromptPin`, `PinResolver`, `PinPersistence`** — `bc-cut-decisions.md §BC 10`, `FK-44 §44.3`, `FK-44 §44.5`
- **Sub `agentkit.backend.prompt_runtime.materialization`: `BundleMaterializer`, `StaticPromptMaterializer`, `DynamicPromptRenderer`, `RenderMode`, `PromptAuditHash`, `AuditRecord`** — `bc-cut-decisions.md §BC 10`, `FK-44 §44.4`, `FK-44 §44.6`
- **Run-scoped Prompt-Instanzpfad `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`** — `FK-44 §44.4.1`, `formal.prompt-runtime.commands §materialize-agent-prompt-instance`
- **Audit-Records via `artifacts.ArtifactManager` persistieren** — `FK-44 §44.6`, `bc-cut-decisions.md §BC 10`
- **State-Machine: Zustaende `binding_resolved`, `run_pinned`, `instance_materialized`, `rejected` mit definierten Uebergaengen** — `formal.prompt-runtime.state-machine`
- **Kommando `reject-stale-local-prompt-cache` mit Invariante `project_local_prompt_copy_is_never_authoritative`** — `formal.prompt-runtime.commands §reject-stale-local-prompt-cache`, `formal.prompt-runtime.invariants`
- **Event `prompt_used` (offen) — falls eingefuehrt, TelemetryContract-Registrierung vorher** — `FK-44 §44.6`, `bc-cut-decisions.md §BC 10 Punkt 6`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/prompt_composer/resources.py:PromptBundleBinding` — Dataclass fuer Bundle-Bindung; deckt `bundle_id`, `bundle_version`, `bundle_root`, `manifest_path`, `manifest_sha256` ab
- `src/agentkit/prompt_composer/resources.py:resolve_project_prompt_binding` — liest Lock-Datei `.agentkit/config/prompt-bundle.lock.json`, prueft Manifest-SHA256, liefert `PromptBundleBinding` aus installerverwalteten Bundle-Store
- `src/agentkit/prompt_composer/resources.py:resolve_bootstrap_prompt_binding` — Fallback auf interne Ressource fuer nicht-projektgebundene Kontexte
- `src/agentkit/prompt_composer/resources.py:prompt_template_sha256` — berechnet und verifiziert SHA256 gegen Manifest-Eintrag
- `src/agentkit/prompt_composer/pins.py:PromptRunPin` — frozen Dataclass mit `run_id`, `prompt_bundle_id`, `prompt_bundle_version`, `prompt_manifest_sha256`
- `src/agentkit/prompt_composer/pins.py:initialize_prompt_run_pin` — erzeugt Run-Pin per `resolve_project_prompt_binding`, persistiert JSON
- `src/agentkit/prompt_composer/pins.py:ensure_prompt_run_pin` — idempotentes Schreiben mit Mismatch-Pruefung
- `src/agentkit/prompt_composer/pins.py:resolve_run_prompt_binding` — laedt Pin, prueft gegen Lock, prueft gegen aktuelle Binding — schuetzt vor Mid-run-Drift
- `src/agentkit/prompt_composer/composer.py:ComposedPrompt` — frozen Dataclass mit allen Audit-Feldern (`template_sha256`, `render_input_digest`, `output_sha256`, `render_mode`, `logical_prompt_id`, `template_relpath`)
- `src/agentkit/prompt_composer/composer.py:compose_named_prompt` — rendert Template per `format_map`, berechnet Digests, liefert `ComposedPrompt`
- `src/agentkit/prompt_composer/composer.py:write_prompt_instance` — schreibt `prompt.md` und `manifest.json` unter `{project_root}/.agentkit/prompts/{run_id}/{invocation_id}/`
- `src/agentkit/prompt_composer/composer.py:write_rendered_prompt_artifact` — Pendant fuer Evaluator-Prompts (schreibt `rendered-manifest.json`)
- `src/agentkit/prompt_composer/selectors.py:select_template_name` — bildet `StoryType`/`StoryMode`/`spawn_reason` auf Template-Namen ab
- `tests/unit/prompting/` — Unit-Tests fuer Pins, Selectors, Sentinels, Composer, Resources, Worker-Context

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens
> eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den
> Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade
> kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Paket `src/agentkit/prompt_runtime/` fehlt vollstaendig | `bc-cut-decisions.md §BC 10` | Kein `__init__.py`, kein Top-Modul, keine Sub-Pakete unter `agentkit.backend.prompt_runtime.*`; AG3-015 plant Erstanlage |
| A2 | Top-Klasse `PromptRuntime` mit den vier normierten Top-Surface-Methoden fehlt | `bc-cut-decisions.md §BC 10`, `FK-44 §44.3–44.4` | `create_run_pin`, `materialize_prompt`, `update_binding`, `compute_audit_hash` sind nicht als Klassen-API vorhanden |
| A3 | Sub `agentkit.backend.prompt_runtime.bundle_store` fehlt | `bc-cut-decisions.md §BC 10` | `BundleStore`, `PromptBundle`, `PromptTemplate`, `BundleVersion`, `LogicalPromptId` nicht vorhanden |
| A4 | Typisiertes Pydantic-`PromptAuditHash`-Schema fehlt | `FK-44 §44.6`, `bc-cut-decisions.md §BC 10`, `formal.prompt-runtime.entities` | Audit-Hash-Felder existieren nur lose als Felder in `ComposedPrompt` (Dataclass), nicht als eigenes, versioniertes Pydantic-v2-Schema im Besitz von `Materialization`-Sub |
| A5 | `AuditRecord`-Persistenz via `artifacts.ArtifactManager` fehlt | `FK-44 §44.6`, `bc-cut-decisions.md §BC 10 Punkt 1` | Kein `ArtifactManager`-Aufruf im Codebase gefunden; AuditRecords werden derzeit als lose JSON-Dateien geschrieben — Invariante `prompt_usage_is_auditable_to_exact_template_and_output_digest` nicht vollstaendig erfuellt |
| A6 | Kommando `reject-stale-local-prompt-cache` nicht implementiert | `formal.prompt-runtime.commands §reject-stale-local-prompt-cache`, `formal.prompt-runtime.invariants §project_local_prompt_copy_is_never_authoritative` | Kein aktiver Pruefmechanismus, der mutable lokale Prompt-Kopien zurueckweist und Event `prompt.stale_cache_detected` emittiert |
| A7 | State-Machine-Zustaende und -Uebergaenge nicht formal implementiert | `formal.prompt-runtime.state-machine`, `formal.prompt-runtime.scenarios` | Kein Status-Enum (`binding_resolved`, `run_pinned`, `instance_materialized`, `rejected`), keine Transition-Guards; Laufzeitpfad ist imperativ ohne formale Zustandspruefung |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Run-Pinning / `BundlePinning`-Sub | `src/agentkit/prompt_composer/pins.py:PromptRunPin`, `initialize_prompt_run_pin`, `ensure_prompt_run_pin` | `bc-cut-decisions.md §BC 10`, `FK-44 §44.3`, `formal.prompt-runtime.invariants §active_run_uses_one_pinned_bundle` | Modul-Prefix falsch (`prompt_composer.pins` statt `prompt_runtime.bundle_pinning`); `ProjectPromptPin`-Klasse fehlt als eigenstaendige Klasse; `PinResolver`- und `PinPersistence`-Klassen fehlen; kein formales `pinned_at`-Timestamp-Feld |
| B2 | Bundle-Bindungsaufloesung / `BundleStore`-Verantwortung | `src/agentkit/prompt_composer/resources.py:resolve_project_prompt_binding`, `resolve_bootstrap_prompt_binding` | `bc-cut-decisions.md §BC 10`, `FK-44 §44.2`, `formal.prompt-runtime.invariants §project_prompt_binding_is_lock_authoritative` | Modul-Prefix falsch (`prompt_composer.resources` statt `prompt_runtime.bundle_store`); `BundleStore`-Klasse als typisierter Koordinator fehlt; `entity.prompt-bundle`-Attribute `immutable` wird nicht deklariert |
| B3 | Prompt-Materialisierung fuer Agent-Prompts | `src/agentkit/prompt_composer/composer.py:write_prompt_instance`, `MaterializedPromptInstance` | `FK-44 §44.4.1`, `formal.prompt-runtime.commands §materialize-agent-prompt-instance`, `formal.prompt-runtime.scenarios §static_prompt_is_materialized_from_pinned_bundle` | Modul-Prefix falsch; `StaticPromptMaterializer` (Hardlink/Symlink) fehlt — nur Datei-Kopie via `atomic_write_text`; `PromptAuditHash` nicht als Pydantic-Schema; kein Event `prompt.instance_materialized` emittiert |
| B4 | Prompt-Materialisierung fuer Evaluator-Prompts | `src/agentkit/prompt_composer/composer.py:write_rendered_prompt_artifact`, `RenderedPromptArtifact` | `FK-44 §44.4.2`, `formal.prompt-runtime.commands §render-evaluator-prompt` | Evaluator-Pfad vorhanden, aber `ArtifactManager`-Integration fehlt; kein Event `prompt.rendered` emittiert; kein formaler `render-mode: static`-Pfad implementiert (immer `rendered`) |
| B5 | Digest-Kette fuer Auditierbarkeit | `src/agentkit/prompt_composer/composer.py:ComposedPrompt` (Felder `template_sha256`, `render_input_digest`, `output_sha256`) | `FK-44 §44.6`, `formal.prompt-runtime.invariants §prompt_usage_is_auditable_to_exact_template_and_output_digest`, `formal.prompt-runtime.entities §prompt-instance` | Digest-Berechnung korrekt implementiert; `render_input_digest` und `output_sha256` vorhanden; aber `AuditRecord`-Persistenz via `ArtifactManager` fehlt; `prompt_bundle_manifest_digest` nur im Pin, nicht explizit im Manifest-JSON der Instanz als `resolved_prompt_bundle_manifest_digest` |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im
> Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug,
> Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Modul-Prefix-Verletzung: Gesamtes BC unter `prompt_composer` statt `prompt_runtime` | `src/agentkit/prompt_composer/` (alle Module) | `bc-cut-decisions.md §BC 10`, `formal.prompt-runtime.*` | Die BC-Cut-Entscheidung weist `agentkit.backend.prompt_runtime.*` als Modul-Prefix aus. Der aktuelle Code liegt unter `agentkit.prompt_composer.*`. Andere BCs (FK-44 §44.4.2, bc-cut-decisions) referenzieren `PromptRuntime.materialize_prompt` — diese Schnittstelle existiert unter dem falschen Prefix. Verletzt SINGLE SOURCE OF TRUTH fuer Modul-Lokation. |
| C2 | `resolve_run_prompt_binding` verletzt Invariante `binding_changes_affect_only_future_runs` | `src/agentkit/prompt_composer/pins.py:resolve_run_prompt_binding` (Z. 155–175) | `formal.prompt-runtime.invariants §binding_changes_affect_only_future_runs`, `FK-44 §44.3` | Die Funktion vergleicht den persistierten Run-Pin gegen die *aktuelle* Projektbindung (`resolve_project_prompt_binding`) und wirft einen Fehler, wenn Bindung und Pin voneinander abweichen. Das ist korrekt fuer Mismatch-Erkennung, aber nach einem legitimen `update_binding`-Aufruf durch den Installer wuerden neue Rebinds — sofern der Run-Pin noch von der alten Version abgeleitet wurde — faelschlicherweise als Fehler behandelt, anstatt stabil den gepinnten Bundle weiterzuverwenden. Die Invariante erfordert, dass der Run-Pin immun gegen spaetere Projektbindungsaenderungen bleibt; stattdessen wirft der Code `PROMPT_RUN_PIN_MISMATCH`, wenn Lock und Pin auseinanderdriften. |
| C3 | `PromptRunPin`-Dataclass statt Pydantic-v2-Modell | `src/agentkit/prompt_composer/pins.py:PromptRunPin` | `bc-cut-decisions.md §BC 10`, Coding-Regeln in `CLAUDE.md §Pydantic v2 fuer Konfigurationen und Artefaktmodelle` | `PromptRunPin` ist als `@dataclass(frozen=True)` implementiert. Das CLAUDE.md schreibt Pydantic v2 fuer Artefaktmodelle vor. Andere Artefakt-Owner-Klassen im Projekt nutzen Pydantic. Fehlende Pydantic-Validation bedeutet kein automatisches Schema-Contract-Testing. |

## 5. Ableitungen / Empfehlungen

1. **Paket `src/agentkit/prompt_runtime/` anlegen und Modul-Prefix migrieren (hoechste Prioritaet):** Solange der Code unter `prompt_composer` liegt, ist jede BC-uebergreifende Referenz auf `PromptRuntime.materialize_prompt` (von `verify-system`, `implementation-phase`, `installation-and-bootstrap`) ungueltig. Dies ist ein Blocker fuer alle abhaengigen BCs.

2. **Top-Klasse `PromptRuntime` mit normierten vier Top-Surface-Methoden implementieren:** Ohne diese Klasse kann kein anderer BC die Schnittstelle korrekt aufrufen. Besonders `update_binding` (Aufruf durch `installation-and-bootstrap`) und `materialize_prompt` (Aufruf durch `verify-system`) sind fuer die Pipeline-Integritaet kritisch.

3. **`PromptAuditHash` als Pydantic-v2-Schema in `agentkit.backend.prompt_runtime.materialization` definieren und `AuditRecord`-Persistenz via `artifacts.ArtifactManager` herstellen:** Ohne typisiertes Schema ist Audit-Contract-Testing nicht moeglich; ohne `ArtifactManager`-Anbindung verletzt jede Prompt-Nutzung die Invariante `prompt_usage_is_auditable_to_exact_template_and_output_digest`.

4. **`resolve_run_prompt_binding` semantisch korrigieren (C2):** Der Run-Pin muss immun gegen spaetere Lock-Aktualisierungen sein. Nach einem `update_binding` durch den Installer soll ein bereits gepinnter Run stabil auf seinem alten Bundle bleiben — kein Fehler, keine stille Mutation. Der Vergleich zwischen Lock und Pin muss umgebaut werden: Run-Pin hat Vorrang, Abweichung ist kein Fehler, solange der Pin valide und konsistent ist.

5. **`PromptRunPin` nach Pydantic-v2 migrieren:** Sichert Schema-Contract-Tests und ist Pflicht gemaess CLAUDE.md-Coding-Rules.

6. **Kommando `reject-stale-local-prompt-cache` mit Invarianten-Pruefung implementieren:** Verhindert, dass mutable projektlokale Prompt-Kopien als Quelle genutzt werden; Szenario `stale_project_prompt_cache_is_rejected` aus `formal.prompt-runtime.scenarios` ist derzeit nicht verprobt.

7. **`StaticPromptMaterializer` via Hardlink/Symlink implementieren:** Aktuell werden auch statische Prompts per Datei-Kopie geschrieben; das ist funktional, aber es fehlt der konzeptionelle Schnitt zwischen `static` und `rendered` als separate Materializer-Klassen.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/technical-design/44_prompt_bundles_materialization_audit.md`
  - `concept/formal-spec/prompt-runtime/README.md`
  - `concept/formal-spec/prompt-runtime/entities.md`
  - `concept/formal-spec/prompt-runtime/state-machine.md`
  - `concept/formal-spec/prompt-runtime/commands.md`
  - `concept/formal-spec/prompt-runtime/events.md`
  - `concept/formal-spec/prompt-runtime/invariants.md`
  - `concept/formal-spec/prompt-runtime/scenarios.md`
  - `src/agentkit/prompt_composer/__init__.py`
  - `src/agentkit/prompt_composer/pins.py`
  - `src/agentkit/prompt_composer/composer.py`
  - `src/agentkit/prompt_composer/resources.py`
  - `src/agentkit/prompt_composer/selectors.py`
- **Punktuell via Grep/Read:**
  - `concept/_meta/bc-cut-decisions.md §BC 10` — Modul-Prefix, Top-Surface, Sub-Komponenten, Klassen-Skizze, Beziehungen
  - `concept/technical-design/_meta/domain-registry.yaml` — BC-ID `prompt-runtime`, Display-Name, contract_docs
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/prompt_runtime/**`: kein Ergebnis — Paket existiert nicht
  - Glob `src/agentkit/prompt_composer/**`: alle Module gefunden
  - Glob `src/agentkit/prompting/**`: nur `__pycache__`-Dateien, kein Python-Quellcode
  - Grep `materialize_prompt|PromptBundle|update_binding|PromptRuntime|bundle_pinning|PromptAuditHash|ArtifactManager` in `src/`: bestaetigt Fehlen von `ArtifactManager`, `PromptRuntime`, `PromptAuditHash`
  - Glob `tests/**/*prompt*`: Unit-Tests unter `tests/unit/prompting/` und `tests/unit/prompt_composer/`; Integration-Tests `tests/integration/prompts_and_skills/` nur mit leerem `__init__.py`
