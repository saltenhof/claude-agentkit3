# AG3-089 — Remediation r1 (response to review-r1)

Scope of this remediation: `story.md` only (status.yaml verified correct, not touched).
No production code, tests, concept files, or other stories' files were modified.

## Must-Fix ERRORs

### MF1 / Finding 1a (ERROR) — §51.3 falsch umgeschnitten
**Finding:** Story machte aus FK-51 §51.3 „Erst-Upgrade / Re-Upgrade / Cross-Major"; FK-51 §51.3 definiert (1) Config+Bindung unveraendert, (2) Config vom Nutzer angepasst, (3) neue Skill-/Prompt-Variante.
**Resolution:** Scope §2.1.2 und neues AC3 (3a/3b/3c) auf die echten drei FK-Szenarien mit Digest-/Bundle-/Binding-Entscheidungskriterien umgestellt. Header „Quell-Konzepte" listet die drei Szenarien jetzt korrekt. Der erfundene „Erst-/Re-/Cross-Major"-Pfad ist entfernt.

### MF2 / Finding 1b (ERROR) — Widerspruch „keine Mutation" vs. §51.3.2 Backup+Write
**Finding:** Story verlangte bei jeder erkannten Anpassung „blockiert/meldet … statt zu ueberschreiben"/„mutiert nicht"; §51.3.2 schreibt fuer angepasste Config aber `.bak` + neue Version vor.
**Resolution:** Schreibverhalten pro Quelle differenziert. Config-Migration (§51.3.2) = `.bak`+Write (AC3b), explizit von F-51-023 ausgenommen. F-51-023 (Block/Meldung, keine Mutation) gilt jetzt ausdruecklich nur fuer Cleanup-/Binding-/Git-Hook-Schreibpfade (Scope §2.1.4/§2.1.5, AC8, Guardrails §5). Widerspruch aufgeloest ohne Abweichung vom FK.

### MF3 / Finding 3b (ERROR) — `ProjectPromptPin` existiert nicht
**Finding:** `ProjectPromptPin` als realer Anker genannt; `pins.py` hat `PromptRunPin`, Projektbinding liegt in `resources.py`.
**Resolution:** Auf reale Symbole umgeankert: `resolve_project_prompt_binding` (`src/agentkit/prompt_runtime/resources.py:105`), `PromptBundleBinding` (`resources.py:37`), Rebinding `PromptRuntime.update_binding` (`src/agentkit/prompt_runtime/runtime.py:206`). Erwaehnung von `pins.py`/`prompt-bundle.lock.json` als Footprint-Quelle entfernt.

### MF4 / Finding 3a (ERROR) — „nur eine Lesequelle existiert" falsch
**Finding:** Behauptung „Nur eine der vier Lesequellen existiert als Top-Surface" ist falsch; mehrere Owner-Lesesurfaces existieren bereits.
**Resolution:** Ist-Zustand §1 berichtigt: das *Aggregat* (`CustomizationFootprint`) und die *Invariante* (F-51-023) fehlen, die vier Owner-Lesesurfaces existieren bereits und sind jeweils mit realem `file:line` belegt (`PipelineConfig` models.py:335 / loader.py:52; `load_rules` rules.py:345; `resolve_project_prompt_binding` resources.py:105; `Skills.resolve_binding` top.py:625).

### MF5 / Finding 2a (ERROR) — AC fuer Git-Hook `.bak` bei unerkannter Anpassung fehlt
**Finding:** AC3 (alt) testete Hook-Migration/Dispatching, aber nicht den §51.6.1-Schutzfall `.bak` fuer unerkannte Anpassungen.
**Resolution:** Neues AC5 ergaenzt (unerkannter Pre-Commit -> `.bak` vor Write, keine stille Zerstoerung). Scope §2.1.3 entsprechend erweitert.

### Finding 2b (ERROR) — kein AC beweist die drei §51.3-Szenarien
**Resolution:** Abgedeckt durch neues AC3 (3a unchanged skip, 3b config digest mismatch, 3c explicit new bundle/profile binding). Identisch zu MF1-Resolution auf AC-Ebene.

### Finding 3a-bis (ERROR, Klarheit) — Top-Surface-Anker unsauber
**Resolution:** Alle vier Quellen mit korrektem Owner-BC und realer Lesesurface + `file:line` in §1 und Scope §2.1.5 verankert. CCAG-Runtime-Surface jetzt `load_rules` (rules.py:345) statt unspezifisch.

## WARNINGs

### W1 / Finding 1c — Git-Hook unerkannte Anpassung -> `.bak`
**Resolution:** In Scope §2.1.3 und AC5 explizit aufgenommen (deckt sich mit MF5). FK-51 §51.6.1 Schritt 4 zitiert.

### W2 / Finding 4 — `register_hooks`-Anker falsch
**Finding:** `Governance.register_hooks` war mit `governance/hook_registration.py` verankert; die Methode sitzt in `governance/runner.py:193`, `hook_registration.py` liefert nur Typen.
**Resolution:** Callable-Anker auf `src/agentkit/governance/runner.py:193`; Typ-Anker (`HookDefinition`/`RegistrationResult`) auf `src/agentkit/governance/hook_registration.py` (HookDefinition ab Z. 70). Beide in §1 getrennt benannt.

## PASS-Befunde (unveraendert)
- Index-Row `_STORY_INDEX.md:105` und `status.yaml` (`depends_on: AG3-070, AG3-088`) stimmen — `status.yaml` nicht angefasst.
- Reale Fehlstandsanker (`PROJECT_CONFIG_VERSION = "1"` runner.py:75; `update_upgraded` runner.py:1343; `installer/upgrade/` fehlt; `Skills.resolve_binding` top.py:625) im korrigierten §1 beibehalten.

## Template / Konventionen
- AG3-057-Templatestruktur (Abschnitte 1–6) erhalten; AC-Liste auf 9 Punkte erweitert (Renummerierung inkl. Pflichtbefehle = AC9).
- ARCH-55: alle eingefuehrten Symbol-/Modus-/Konventionsnamen englisch (`migrate_config`, `CustomizationFootprint`, `.bak`, `cleanup`).

## Cross-Story-Voraussetzungen (Bestand, keine neuen)
- **AG3-088** — Checkpoint-Engine + Execution-Modi; Upgrade ist ein Flow/Modus dieser Engine. (depends_on, bereits gesetzt.)
- **AG3-070** — `config_version`-Pflichtfeld + fail-closed Config-Loader als Versionsquelle der Migration. (depends_on, bereits gesetzt.)

Keine neue Cross-Story-Voraussetzung erforderlich: alle vier Footprint-Lesesurfaces existieren bereits in ihren Owner-BCs (FK-43/FK-44/FK-03/FK-30-Linien). AG3-089 konsumiert sie nur lesend und baut Aggregat + Invariante darauf.

## Hinweis zu einer FK-internen Diskrepanz (nicht in AG3-089 aufzuloesen)
FK-51 §51.8 Prosa sagt „drei Quellen", die zugehoerige Tabelle listet **vier** Zeilen (Pipeline-Config, CCAG, Prompt-Binding, Skill-Binding). `_STORY_INDEX.md:105` und der Review gehen von vier Quellen aus; die Story folgt der Tabelle/dem Index (vier). Die Prosa/Tabelle-Inkonsistenz ist ein Konzept-Defekt im Owner-Dokument FK-51 und liegt ausserhalb des AG3-089-Schnitts — hier nur gespiegelt, nicht im Konzept geaendert (Konzeptdateien duerfen nicht angefasst werden).
