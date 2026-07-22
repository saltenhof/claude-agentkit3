# Review 1 (Codex) — AG3-176 VektorDB-Installer-Integration

## Gesamturteil

**NICHT ABNAHMEFAEHIG.** Die gemeldeten fokussierten Gruenlaeufe sind kein
Korrektheitsnachweis. Es gibt drei voneinander unabhaengige BLOCKER und mehrere
MAJOR-Befunde an produktiven Grenzen. Die MAJOR+-Befunde sind echte
Funktions-/Vertragsverletzungen, nicht Orchestrator-Feinschliff:

1. Der echte Installer validiert eine bestehende Projektkonfiguration nicht vor
   seinen ersten Wirkungen, sondern erzeugt und ueberschreibt sie lenient.
2. Das neue Skill-Bundle 5.0.0 ist wegen falschem Manifest-Digest nicht bindbar.
3. Selbst nach Korrektur des Digests scheitert seine Materialisierung am nicht
   unterstuetzten Platzhalter `{{concepts_dir}}`.
4. Erstindex, Hooks, Closure-Sync, VERIFY und Uninstall verletzen weitere
   ausdrueckliche Story-/Konzeptvertraege.

Die Review-Reproduktion blieb bewusst harmlos: statisches Code-Lesen, eine
Digest-Berechnung ueber ausgelieferte Dateien und ein fokussierter pytest-Lauf.
Es wurden keine echten Secrets und keine missbraeuchlichen Payloads verwendet.

## Findings

### AG3-176-R1 — BLOCKER — Strikte Config-Grenze liegt nicht vor den Installer-Wirkungen

**Ort:**

- `src/agentkit/backend/installer/checkpoint_engine/flow.py:82-99`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp01_to_06.py:201-247`
- `src/agentkit/backend/installer/runner.py:348-399`
- `src/agentkit/backend/installer/runner.py:725-731`
- `src/agentkit/backend/installer/runner.py:1000-1027`
- `tests/unit/config/test_strict_config_boundary.py:102-108`

**Fakten-Beleg:** Der reale Spine laeuft ueber CP1 bis CP5 und erst spaeter ueber
CP7/CP8/CP9/CP10. CP5 baut aus `InstallConfig` eine neue Mapping-Struktur,
erzwingt darin `features.vectordb: true`, materialisiert zuerst die
Verzeichnisstruktur und schreibt danach `project.yaml`. Bei einer bestehenden
Datei wird ausschliesslich `yaml.safe_load()` verwendet und anschliessend die
neue Struktur geschrieben. Damit gelten Last-wins-Semantik und
Pydantic-freie Nachsicht genau an der produktiven Grenze. Ein vorhandenes
`features.vectordb: false`, doppelte `features`-/`vectordb`-/Endpoint-Keys oder
anderweitig ungueltige, aber von `safe_load` akzeptierte Werte werden nicht vor
der ersten Wirkung als `configuration_invalid` abgewiesen; sie werden
ueberschrieben. `scaffold_project_structure()` laeuft sogar vor diesem
lenienten Read. Der volle `load_project_config()` ist nur spaeter und bedingt im
Skill-Binding-Pfad sichtbar. Der angebliche Reihenfolgetest ruft lediglich
`load_project_config()` direkt auf und kommentiert, dass *jeder Consumer, der
ihn benutzt*, sicher sei; er ruft den Installer nicht auf und beobachtet keine
Wirkungs-Seam.

**Normverletzung:** AG3-176 AC1/AC2; Decision Record Rand 1; FK-13
§13.1/§13.8; FK-03 §3.1; ZERO-DEBT/FAIL-CLOSED. Die vollstaendige strikte
Projektkonfiguration muss vor Aktivierung, Registrierung, Preflight und jeder
anderen Projektmutation validiert sein.

**Fix:** Am Installer-Eingang eine einzige strikte Read-/Validate-Phase mit
`load_project_config()` beziehungsweise einem gleich strikten
Create-vs.-Existing-Vertrag einfuehren. Bei bestehender Datei niemals ueber
`yaml.safe_load()` migrieren/ueberschreiben. Erst nach erfolgreicher
Vollvalidierung einen unveraenderlichen `ProjectConfig` in den Checkpoint-Kontext
geben und daraus CP5, Endpoint, Registrierung und Skills speisen. Ein
End-to-End-Negativmatrix-Test muss den echten `run_checkpoint_install`-Pfad mit
beobachteten Filesystem-, Preflight-, Registration- und Hook-Seams ausfuehren
und vor dem ersten Effekt abbrechen.

### AG3-176-R2 — BLOCKER — Bundle 5.0.0 hat den falschen Manifest-Digest und ist nicht bindbar

**Ort:**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/manifest.json:4`
- `src/agentkit/backend/skills/top.py:75-105`
- `tests/contract/skill_bundles/test_create_userstory_core_v5.py:20-26`
- `tests/contract/skills/test_skill_catalog_bundles.py:15-16,33-45`

**Fakten-Beleg:** Der Runtime-Owner berechnet SHA-256 ueber die kanonische
Manifest-JSON ohne `manifest_digest`. Fuer 5.0.0 ist deklariert:
`e52a57bc181714b2ea04566d029ba775dbe7afdb1791b2f22a9cc257a716a727`,
der Runtime-Algorithmus ergibt aber
`d7f33274c41468febe6efa643bd70418fb8b4091e36cef40ffae3767980b0ca6`.
Der deklarierte Wert ist stattdessen exakt der SHA-256 von `SKILL.md`. Der neue
v5-Test kodiert diesen falschen Vertrag explizit. Der allgemeine Bundle-Vertrag
globbt nur `*/4.0.0/manifest.json` und prueft v5 daher nicht. Der Store waehlt
gleichzeitig die hoechste SemVer, also v5; produktives Binding endet damit in
`SkillBundleDigestMismatchError`.

Harmlose Reproduktion:

```text
declared = e52a57bc181714b2ea04566d029ba775dbe7afdb1791b2f22a9cc257a716a727
runtime  = d7f33274c41468febe6efa643bd70418fb8b4091e36cef40ffae3767980b0ca6
SKILL.md = e52a57bc181714b2ea04566d029ba775dbe7afdb1791b2f22a9cc257a716a727
```

**Normverletzung:** AG3-176 AC7; FK-43 §43.5.2/§43.8; Story-DoD. Das
immutable Bundle muss vor Verlinkung digest-verifiziert materialisierbar sein.

**Fix:** Manifest-Digest mit exakt dem Runtime-Algorithmus neu erzeugen. Den
Katalogvertrag versionsunabhaengig ueber **alle** ausgelieferten Manifeste laufen
lassen und denselben kanonischen Helper im Produkt und Test verwenden. Einen
produktiven Bind-Test fuer 5.0.0 ergaenzen.

### AG3-176-R3 — BLOCKER — Bundle 5.0.0 verwendet einen unbekannten Platzhalter

**Ort:**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/SKILL.md:340-396`
- `src/agentkit/backend/skills/placeholder.py:152-169`
- `src/agentkit/backend/skills/placeholder.py:195-207`
- `src/agentkit/backend/skills/materialize.py:245-255`

**Fakten-Beleg:** `SKILL.md` verwendet mehrfach den skalaren Token
`{{concepts_dir}}`. Der FK-43-Substitutor kennt aus der Projektkonfiguration nur
`gh_owner`, `gh_repo`, `project_prefix`, `project_key` und `wiki_stories_dir`
sowie separat den Manifest-Proof. `_apply()` wirft fuer jeden anderen skalaren
Token fail-closed `UnknownPlaceholderError`. Der Materializer substituiert alle
`.md`-Dateien, also erreicht dieser Fehler den echten Installationspfad. Dieser
Befund ist vom falschen Digest unabhaengig: Nach dessen Fix scheitert das Bundle
an der naechsten Grenze.

**Normverletzung:** AG3-176 AC7; FK-43 §43.4.2 (geschlossene
Placeholder-Menge). `concepts_dir` soll zur Laufzeit aus der streng geladenen
Projektkonfiguration gelesen werden, nicht durch einen unangekuendigten neuen
Materialisierungsvertrag entstehen.

**Fix:** Den unbekannten Token entfernen und im Skill den produktiven,
fail-closed Config-/Binding-Zugriff beschreiben. Keine neue Placeholder-Semantik
ohne dazugehoerige normative Konzeptentscheidung und durchgaengige
Implementierung einfuehren. Danach beide Harness-Links ueber den echten
Materializer testen.

### AG3-176-R4 — MAJOR — CP10a kann bei Gesamtfehler bereits Freshness und einen Teil-Receipt publiziert haben

**Ort:**

- `src/agentkit/backend/vectordb/first_index.py:121-172`
- `src/agentkit/backend/vectordb/ingest/engine.py:145-160`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:852-870`
- `tests/unit/vectordb/test_first_index_receipts.py:106-168`

**Fakten-Beleg:** `run_first_index()` fuehrt `story_sync` zuerst aus. Der
AG3-174-Engine-Owner publiziert dabei den Story-Completion-Stand sofort. Erst
danach laufen Concept-Validation und `concept_sync`. Scheitert dieser zweite
Producer, meldet CP10a zwar FAILED, die Story-Freshness ist aber bereits
fortgeschrieben. Nach beiden Syncs werden die zwei Receipts ausserdem
sequenziell geschrieben; scheitert der zweite Write, bleibt ein neuer
Story-Success-Receipt bei einem insgesamt fehlgeschlagenen Checkpoint zurueck.
Die Tests decken das nicht: Der angebliche Empty-Corpus-Erfolg akzeptiert mehrere
`FirstIndexError`-Gruende und kehrt dann erfolgreich zurueck; der
Corpus-/Receipt-Test tut dasselbe. Damit koennen beide Kernnachweise ohne ein
Resultat bestehen.

**Normverletzung:** AG3-176 AC3; FK-50 CP10a; FK-13 §13.7/§13.8.
Transport-/Parse-/Partialfehler duerfen fuer den Erstindex weder Success noch
Freshness publizieren; Empty Corpus muss ein echter Erfolg mit Nullmengen sein.

**Fix:** Completion-/Receipt-Publikation fuer den CP10a-Gesamtvorgang stagen und
erst nach Erfolg beider Producer atomar beziehungsweise rollback-faehig
freigeben. Alternativ braucht die AG3-174-Engine einen expliziten
`publish_completion=False`-/prepare-commit-Port, ohne Sync/Ingest zu duplizieren.
Fehlerinjektion nach Story-Sync, im Concept-Sync und zwischen beiden
Receipt-Writes testen; in allen Faellen muessen vorherige Completion-Staende und
Receipts byte-/wertegleich bleiben. Empty Corpus muss ohne `except` erfolgreich
zwei Nullmengen-Receipts liefern.

### AG3-176-R5 — MAJOR — CP10/CP10b erben Config-Nachsicht und stille Default-Verzeichnisse

**Ort:**

- `src/agentkit/backend/installer/mcp_registration/dual_write.py:116-160`
- `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:946-959`

**Fakten-Beleg:** `build_story_kb_spec()` faengt Binding-/Runtime-Fehler ab und
erfindet fuer die Registrierung `root/concepts` und `root/stories`. CP10b faengt
durch `except (ProjectBindingError, Exception)` effektiv jede Exception ab und
nimmt `run_state.project_yaml` beziehungsweise den stillen Default
`"concepts"`; danach materialisiert es Hooks. Ein kaputtes Binding, ein
Config-Parserfehler oder ein abweichendes konfiguriertes `concepts_dir` wird
damit in eine produktive Registrierung/Hook-Wirkung umgedeutet.

**Normverletzung:** AG3-176 AC1/AC2/AC4/AC7; FK-50 CP10/CP10b; FK-03
§3.1; Decision Record Rand 1. Im projektgebundenen Pfad sind Defaults nach
Config-/Binding-Fehler ausdruecklich verboten.

**Fix:** Beide Fallbacks entfernen. Ausschliesslich den am Installer-Eingang
streng validierten `ProjectConfig`/`ProjectBinding` verwenden; jeder Load- oder
Binding-Fehler muss vor Mutation als `configuration_invalid` beziehungsweise
der typisierte Binding-Fehler enden. Dry-Run-Fixtures muessen echte gueltige
Projektkonfigurationen bereitstellen, nicht Produktionsnachsicht erzwingen.

### AG3-176-R6 — MAJOR — CP10b erhaelt bestehende Secret-Detection nicht und VERIFY prueft nur Textfragmente

**Ort:**

- `src/agentkit/backend/vectordb/git_hooks.py:150-166`
- `src/agentkit/backend/vectordb/git_hooks.py:181-235`
- `src/agentkit/backend/installer/upgrade/hook_migration.py:214-275`
- `concept/technical-design/51_upgrade_migration_customization_preservation.md:200-213`

**Fakten-Beleg:** Ist ein bestehender Pre-Commit nicht als "current" erkannt,
wird er hoechstens als `.bak` kopiert und der aktive Hook danach vollstaendig
durch `desired_pre` ersetzt. Das widerspricht sogar dem bereits vorhandenen
Upgrade-Owner, der bei erkannter Secret-Detection den Dispatch anhaengt und den
bestehenden Scan unveraendert laesst. Eine Sicherung ist kein Erhalt der aktiven
Detection. Zusaetzlich gelten Hooks als aktuell, wenn Marker, `concepts_dir` und
einige Woerter vorkommen. `pre_commit_is_current()` prueft den eigentlichen
Secret-Scan- und `validate --staged`-Aufruf nicht;
`post_commit_is_current()` prueft weder ausfuehrbare Aufrufe noch deren Reihenfolge.
Ein harmloser manueller Edit, der Marker/Kommentare stehen laesst, kann die
Kommandos entfernen und VERIFY liefert trotzdem PASS. Ferner wird ein valides
`concepts_dir` mit Leerzeichen ungequotet in Shell-`case`-Patterns eingesetzt
(`git_hooks.py:64-69,91-92,123-124`) und erzeugt einen syntaktisch/semantisch
falschen Dispatch.

**Normverletzung:** AG3-176 AC4; FK-50 CP10b; FK-51 §51.6.1; FK-30
§30.5.3/§30.5.4a. Bestehende Secret-Detection muss unveraendert aktiv bleiben;
REGISTER/DRY_RUN/VERIFY muessen die tatsaechlich feuernde Semantik belegen.

**Fix:** Den bestehenden `hook_migration`-/Hook-Owner wiederverwenden statt
einen zweiten Rewriter einzufuehren. AgentKit-Dispatch in einen klar markierten
Block chirurgisch einfuegen/aktualisieren, vorhandene Secret-Detection
unveraendert lassen und unbekannte Customizations fail-closed zur manuellen
Aufloesung melden. VERIFY muss den kanonischen Block beziehungsweise einen
typisierten Dispatcher pruefen, inklusive Befehlen, `--staged`, Build-vor-Sync
und konfiguriertem Pfad. Pfade nicht als unquoted Shell-Code interpolieren;
bevorzugt einen Python-Dispatcher mit argv-sicherer Uebergabe verwenden.

### AG3-176-R7 — MAJOR — Closure-Sync ist verlorenes daemonisiertes Fire-and-Forget

**Ort:**

- `src/agentkit/backend/closure/runtime_ports.py:220-308`
- `src/agentkit/backend/closure/post_merge_finalization/finalization.py:162-165`
- `tests/unit/closure/test_runtime_ports.py:257-276`

**Fakten-Beleg:** `ProductiveVectorDbSyncPort` startet einen
`threading.Thread(..., daemon=True)`, gibt sofort `(True, None)` zurueck und
bewahrt weder Handle noch Future noch einen dauerhaften Status. Der lokale
`error_box` wird vom Worker beschrieben, aber nie gelesen. Ein Prozessende kann
den Task abbrechen; ein Fehler nach `Thread.start()` kann den Closure-Aufrufer
nicht mehr erreichen und wird nur geloggt. Der Test wartet weder auf den Worker
noch weist er Sync-Aufruf oder Fehlerbeobachtbarkeit nach; bei `triggered=True`
hat er faktisch keine substanzielle Assertion.

**Normverletzung:** AG3-176 AC5; FK-13 §13.7; FK-21 §21.11.4. Closure darf
nicht blockieren, muss den Task aber verlaesslich starten und Fehler beobachtbar
machen; verlorenes Fire-and-Forget ist ausdruecklich ausgeschlossen.

**Fix:** Einen lifecycle-owned Executor/Task-Registry-Port mit Task-ID,
Completion-/Error-Status und definiertem Drain/Shutdown verwenden. Der Closure-
Aufruf darf nach erfolgreicher Queue-/Executor-Uebergabe zurueckkehren, nicht
nach untrackbarem Thread-Start. Tests muessen erfolgreichen Engine-Aufruf,
Post-Start-Fehler, Prozess-/Executor-Shutdown und observierbaren Status
deterministisch nachweisen.

### AG3-176-R8 — MAJOR — CP8 VERIFY prueft keinen der beiden Harness-Links

**Ort:**

- `src/agentkit/backend/installer/bootstrap_checkpoints/cp07_to_09.py:123-189`
- `src/agentkit/backend/skills/top.py:210-223`

**Fakten-Beleg:** In jedem nicht mutierenden Modus werden nur Bundles und das
Prompt-Manifest aufgeloest. DRY_RUN plant; VERIFY liefert danach bedingungslos
PASS mit `reason="binding_current"`. Weder `.claude/skills/...` noch
`.codex/skills/...` wird gelesen. Die interne `_verify_harness_links()`-Pruefung
laeuft nur waehrend des mutierenden Bindings und prueft zudem nur Existenz/Typ,
nicht dass beide Links auf genau dieselbe immutable Version zeigen. VERIFY kann
somit mit fehlendem Codex-Link oder auseinanderlaufenden 4.0.0-/5.0.0-Zielen
gruen sein.

**Normverletzung:** AG3-176 AC7; FK-43 §43.4/§43.5/§43.8. Beide
Harness-Links muessen auf dieselbe digest-verifizierte immutable Version zeigen;
Altprojekte bleiben bis explizitem Upgrade gepinnt.

**Fix:** Im VERIFY-Modus beide Linkziele read-only kanonisch aufloesen und gegen
denselben erwarteten Bundle-ID/Version/Digest-Pin pruefen. Fehlender Link,
abweichendes Ziel, mutable/materialisiertes Ziel ohne passenden Digest oder
Versionsdivergenz muessen FAILED sein. Fresh-Install, Reinstall, gepinntes
Altprojekt und einseitigen/tampered Link am echten CP8-Pfad testen.

### AG3-176-R9 — MAJOR — Skill 5.0.0 ist nicht fallbackfrei

**Ort:**

- `src/agentkit/bundles/skill_bundles/create-userstory-core/5.0.0/SKILL.md:206-250`
- `tests/contract/skill_bundles/test_create_userstory_core_v5.py:29-37`

**Fakten-Beleg:** Das angeblich obligatorische v5-Bundle enthaelt weiterhin den
negativen Template-Ast `{{^IF_STORY_VECTORDB}}`, die Ueberschrift
`Structural Search (Fallback — no VectorDB)` und konkrete `grep`-Kommandos. Das
ist exakt der zu entfernende optionale/Grep-Fallback, nur wenige Abschnitte vor
der Behauptung "Kein Grep-/Dateiscan-Fallback". Der Test sucht nur nach dieser
positiven Behauptung und zwei zufaellig nicht vorhandenen Formulierungen; er
weist weder die Abwesenheit des negativen Asts noch der ausgefuehrten
Grep-Kommandos nach.

**Normverletzung:** AG3-176 AC6/AC7; Decision Record Rand 1; FK-43. VektorDB
ist fuer unterstuetzte Zielprojekte obligatorisch; der optionale Ast und der
Grep-Ersatzpfad sind zu entfernen.

**Fix:** Den kompletten `IF_STORY_VECTORDB`-/Negativ-Ast aus v5 entfernen und
den einzigen produktiven Pfad mit den geforderten Hard Stops formulieren. Den
Test semantisch negativ machen: keine Conditional-Tokens, keine Fallback-
Ueberschrift und keine lokalen `grep`/`rg`-Suchkommandos fuer die betroffenen
Discovery-Pfade; anschliessend das materialisierte Bundle testen.

### AG3-176-R10 — MAJOR — Uninstall laesst beide CP10-MCP-Registrierungen zurueck

**Ort:**

- `src/agentkit/backend/installer/mcp_registration/dual_write.py:194-244`
- `src/agentkit/backend/installer/lifecycle/detach.py:315-362`

**Fakten-Beleg:** CP10 schreibt `story-knowledge-base` sowohl nach
`.mcp.json` als auch nach `.codex/config.toml`. Detach entfernt die Codex-Datei
nur, wenn sie bytegenau dem alten Basisinhalt von
`build_codex_config_toml()` entspricht. Nach dem Dual-Write ist sie per
Definition erweitert und wird deshalb als "foreign/modified" vollstaendig
erhalten; der AgentKit-MCP-Eintrag bleibt aktiv. Fuer `.mcp.json` existiert im
Detach-Pfad ueberhaupt kein symmetrischer, chirurgischer Remove. Der vom
Umsetzer genannte offene Punkt ist daher ein echtes Leck und betrifft beide
Harness-Konfigurationen.

**Normverletzung:** AG3-176 AC4/AC7 und Installer-Lifecycle-/Idempotenzvertrag;
FK-43 Lifecycle-Prinzip. Uninstall darf fremde Eintraege bewahren, muss aber die
eigenen Bindings vollstaendig entfernen.

**Fix:** In beiden Dateien nur die AgentKit-owned
`story-knowledge-base`-Tabellen/Objekte chirurgisch entfernen, fremde Server und
sonstige Codex-Konfiguration wertegleich erhalten und eine Datei nur loeschen,
wenn danach kein fremder Inhalt verbleibt. Contract-Test: vorhandene fremde
Eintraege + CP10 REGISTER + detach + Assert auf entfernte AK3-Eintraege und
unveraenderte Fremdeintraege in beiden Dateien.

### AG3-176-R11 — MAJOR — FK-50 widerspricht der eigenen neuen Pflichtaktivierung

**Ort:**

- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:476-483`
- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:506`
- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:554-559`
- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:861`

**Fakten-Beleg:** Die neue normative Passage sagt korrekt, dass
`features.vectordb: false` ein harter Config-Fehler ist und der
`SKIPPED/vectordb_disabled`-Ast entfernt wurde. Wenige Zeilen spaeter steht
weiterhin, Story-Knowledge-Base werde "nur bei features.vectordb: true"
registriert. Die CP10-Tabelle normiert fuer `features.vectordb: false` weiterhin
`SKIPPED / vectordb_disabled`; auch die allgemeine Statusbeschreibung fuehrt
denselben Fall weiter. Damit hat FK-50 fuer denselben Scope zwei gegensaetzliche
normative Antworten.

**Normverletzung:** AG3-176 AC6; Decision Record Rand 1; ZERO DEBT;
Konzepttreue/W3-Scope-Konsistenz. Ein verpflichtender Aktivierungsschnitt darf
keinen alten optionalen Normpfad behalten.

**Fix:** Alle stale optionalen CP10-/Statuspassagen im selben normativen Diff
entfernen oder eindeutig als historische, nicht normative Semantik markieren.
W2/W3 auf den betroffenen `authority_over`-Scopes erneut laufen lassen und den
Decision-Record-/Impact-Sweep aktualisieren, falls der Diff das erfordert.

### AG3-176-R12 — MAJOR — Die Testevidenz haengt nicht an den behaupteten produktiven Grenzen

**Ort:**

- `tests/unit/config/test_strict_config_boundary.py:102-108`
- `tests/unit/vectordb/test_first_index_receipts.py:106-168`
- `tests/unit/closure/test_runtime_ports.py:257-276`
- `tests/contract/skill_bundles/test_create_userstory_core_v5.py:20-37`
- `tests/contract/skills/test_skill_catalog_bundles.py:15-45`

**Fakten-Beleg:** Die zentralen Tests pruefen innere Helfer oder erlauben
Vakuumerfolg:

- Config: direkter Loader-Aufruf statt echter Installer und keine
  Side-Effect-Assertions.
- CP10a: erwarteter Erfolg darf ueber mehrere Fehlergruende frueh `return`en.
- Closure: bei gestartetem Thread wird weder Ausfuehrung noch Fehler beobachtet.
- Bundle: Test prueft den falschen SKILL.md-Digest und positive Prosa statt
  Fallback-Abwesenheit.
- Katalog: globbt nur 4.0.0, waehrend der Store hoechste SemVer aufloest.

Der fokussierte Lauf

```text
.venv\Scripts\python.exe -m pytest \
  tests/contract/skills/test_skill_catalog_bundles.py::test_shipped_bundle_manifest_digest_and_directory_consistency \
  tests/contract/skill_bundles/test_create_userstory_core_v5.py \
  tests/unit/config/test_strict_config_boundary.py \
  tests/unit/installer/checkpoint_engine/test_ag3_176_flow_and_hooks.py \
  tests/unit/vectordb/test_first_index_receipts.py \
  tests/unit/closure/test_runtime_ports.py -q
```

ergab **1 failed, 31 passed**. Der bestehende Katalogvertrag ist rot, weil er
4.0.0 erwartet, waehrend der Store korrekt 5.0.0 als hoechste SemVer liefert.
Gleichzeitig laufen die oben beschriebenen schwachen v5-/Config-/CP10a-/Closure-
Tests gruen. Die Behauptung lokal gruener relevanter Gates ist damit fuer den
vorliegenden Worktree nicht reproduzierbar.

**Normverletzung:** AG3-176 AC1-AC7 und DoD; ausdruecklicher Schwerpunkt
"Test-Substanz"; CLAUDE.md "Kein done ohne Beleg".

**Fix:** Tests an `run_checkpoint_install`/Checkpoint-Engine, echtem CP10a-Port,
tatsaechlich materialisierten/ausgefuehrten Hooks, echtem Bundle-Materializer
und lifecycle-owned Closure-Task anbinden. Fehler nicht als akzeptierten
Testausgang behandeln. Negativmatrizen muessen jeweils Wirkungslosigkeit,
unveraenderte Freshness/Receipts und typisierte Fehler am aeusseren Vertrag
beweisen. Den Katalogvertrag ueber alle SemVer-Verzeichnisse parametrisieren.

### AG3-176-R13 — MINOR — Nicht jedes Config-Lesefehlerbild wird als `configuration_invalid` normalisiert

**Ort:**

- `src/agentkit/backend/config/loader.py:77-87`
- `src/agentkit/backend/config/strict_yaml.py:114-143`

**Fakten-Beleg:** `Path.read_text(encoding="utf-8")` wird nur unter
`except OSError` gekapselt; `UnicodeDecodeError` ist kein `OSError` und verlaesst
den Loader daher als roher Python-Fehler statt als `ConfigError` mit
`error_code=configuration_invalid`. Der Strict-YAML-Wrapper normalisiert
`yaml.YAMLError`, aber nicht andere parsernahe Grenzfehler wie einen vor der
iterativen Depth-Pruefung auftretenden `RecursionError`.

**Normverletzung:** AG3-176 AC2; FK-03 §3.1; ARCH-55-artiger stabiler
Fehlervertrag. Das Verhalten bleibt zwar fail-closed, ist aber nicht
schnittkonsistent typisiert.

**Fix:** UTF-8-Decodierfehler und begrenzt die bekannten Parser-/Depth-
Grenzfehler in `ConfigError(configuration_invalid)` uebersetzen, ohne pauschal
Programmierfehler zu verschlucken. Tests am Datei-Loader, nicht nur am
String-Helper, ergaenzen.

### AG3-176-R14 — MINOR — `cp10.py` ist zum Checkpoint-Monolithen angewachsen

**Ort:** `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:1-1379`

**Fakten-Beleg:** Die Datei hat 1.379 Zeilen und der aktuelle Diff fuegt netto
mehr als 570 Zeilen hinzu. Sie besitzt inzwischen Dual-Harness-Registrierung,
MCP-Conformance, Endpoint-Preflight, CP10a-Indexierung, CP10b-Hooks, CP10c ARE,
CP10d Sonar und gemeinsame Ergebnislogik. Das sind mehrere unabhaengige
fachliche Owners/Fehlervertraege in einer Datei; die Story-DoD nennt
ausdruecklich "Kein God-File".

**Normverletzung:** Story-DoD; CLAUDE.md Strukturprinzip "klare fachliche
Schnitte statt God-Files"; PROJECT_STRUCTURE Checkpoint-Schnitt.

**Fix:** CP10-Orchestrierung duenn halten und CP10a/b/c/d in eigene
Checkpoint-Module mit gemeinsamem kleinem Result-/Mode-Helper zerlegen. Die
bereits vorhandenen fachlichen Owners (`mcp_registration`, `vectordb`,
`hook_migration`, Sonar) nur ueber Ports aufrufen, nicht erneut implementieren.

## MUSS-fixen vor Abnahme

**BLOCKER:**

- AG3-176-R1 — strikte Config-Grenze vor allen Wirkungen herstellen.
- AG3-176-R2 — v5-Manifest-Digest korrigieren und produktiv pruefen.
- AG3-176-R3 — unbekannten `{{concepts_dir}}`-Token entfernen beziehungsweise
  ohne unerlaubte Konzeptausweitung korrekt anbinden.

**MAJOR:**

- AG3-176-R4 — CP10a ohne Teil-Freshness/Teil-Receipt bei Gesamtfehler.
- AG3-176-R5 — projektgebundene Config-/Verzeichnis-Fallbacks entfernen.
- AG3-176-R6 — Secret-Detection wirklich erhalten und Hook-VERIFY substanziell machen.
- AG3-176-R7 — Closure-Sync lifecycle-owned und beobachtbar ausfuehren.
- AG3-176-R8 — beide Harness-Links im VERIFY gegen dieselbe immutable Version pruefen.
- AG3-176-R9 — v5 optionalen/Grep-Fallback vollstaendig entfernen.
- AG3-176-R10 — Dual-Write beim Uninstall chirurgisch zurueckbauen.
- AG3-176-R11 — widerspruechliche FK-50-Normpassagen bereinigen.
- AG3-176-R12 — echte Grenztests ohne Vakuumerfolg herstellen; relevante Suite gruen.

## Orchestrator-Feinschliff (aufschiebbar, aber nicht ignorierbar)

- AG3-176-R13 — Config-Lesefehler einheitlich typisieren.
- AG3-176-R14 — CP10 entlang der fachlichen Checkpoints aufteilen.

Diese beiden MINORs sind nach der lokalen Severity-Semantik Handlungsauftraege
mit aufschiebender Wirkung. **Wie wollen wir hier vorgehen**: im AG3-176-Fix
mitziehen oder als konkret terminierte Folgestory erfassen? Stilles Liegenlassen
waere mit ZERO DEBT nicht vereinbar.

## Ehrliche Substanzbewertung

Die BLOCKER/MAJOR-Liste ist nicht durch Stilpraeferenzen aufgeblasen. R1-R3
verhindern beziehungsweise entwerten den realen Installationspfad unmittelbar.
R4-R10 betreffen Datenwahrheit, aktive Sicherheits-/Hook-Semantik,
Beobachtbarkeit und Lifecycle-Cleanup. R11 zeigt eine echte normative
Selbstkontradiktion; R12 erklaert konkret, warum die hohe Testanzahl diese Fehler
nicht entdeckt. Nur R13/R14 sind Feinschliff im Sinne der verlangten Trennung.

## Gate-Status zum Review-Zeitpunkt

- **Sonar:** `OK`; `violations=0`, `critical_violations=0`,
  `security_hotspots=0` gegen `http://localhost:9901`.
- **Jenkins:** nicht gruen. Der letzte abgeschlossene Build 1184 steht auf
  `FAILURE`; laut Build-Log war `seu-ci-postgres` im Docker-Netz nicht
  aufloesbar, nachfolgende Stages wurden uebersprungen. Das ist ein
  Infrastrukturfehler und kein Gegenbeweis zu den Code-Findings, er verhindert
  aber die vorgeschriebene Gruen-Bestaetigung.
- **Gate-Helper-Drift:** `scripts/ci/check_remote_gates.ps1` konnte Jenkins
  nicht regulaer lesen (HTTP 401). Der laufende Container hat entgegen der
  AGENTS.md-Annahme `useSecurity=true`,
  `HudsonPrivateSecurityRealm` und
  `FullControlOnceLoggedInAuthorizationStrategy`; die hinterlegten
  Placeholder-Credentials passen daher nicht. Die Sonar-Abfrage wurde mit
  demselben projektierten Metric-Vertrag separat read-only ausgefuehrt.
- **Review-Artefakt:** `git diff --check` ist sauber. Es wurde ausschliesslich
  diese Review-Datei angelegt; der fremde Implementierungsstand blieb
  unangetastet.
