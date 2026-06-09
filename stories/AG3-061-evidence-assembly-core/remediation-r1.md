# AG3-061 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` + `status.yaml` only. No production code,
tests, or concept files touched. Every code/concept anchor below was re-verified
against the real tree at remediation time and corrected to `file:line` /
`§section`. AG3-057 template structure preserved (title block → §1 Ist-Zustand
→ §2 Scope/Out-of-Scope → §3 ACs → §4 DoD → §5 Guardrails → §6 Sub-Agent-Hinweise).

## Must-Fix ERRORs

### MF1 — FK-28-Stufenmodell korrigieren, insbesondere Worker-Hints als Stufe 3 (review §1, §Must-Fix 1)
**Finding:** Story machte Stufe 3 zu „Aggregation + Manifest-Bau" und zog Handover
in Stufe 1. FK-28 §28.3.1 definiert die drei Stufen aber als: Stufe 1 deterministischer
Kern (Git-Diff/Nachbarn/normative Quellen), Stufe 2 Import-Extraktion (FK-46),
**Stufe 3 Worker-Hints aus `handover.json`/`worker-manifest.json`**; Dedup/Limit/Manifest
sind nachgelagerte Schritte, keine Stufe.
**Resolution:** In-Scope 1 `assembler.py` auf die exakte FK-28-§28.3.1-Reihenfolge
umgeschrieben (Stufe 1 deterministischer Kern → Stufe 2 erweiterbarer Import-Eingang →
Stufe 3 Worker-Hints → `_deduplicate` → `_enforce_size_limit` → `BundleManifest.from_entries`).
Stufe 3 inkl. der FK-28-§28.3.5-Worker-Hint-Regeln aufgenommen: **additiv** (kein
Entfernen/Herabstufen von Stufe-1/2), **keine Duplikate**, **Self-Reference-WARNING**.
Neues AC4 verprobt alle drei Regeln + den `WORKER_ASSERTION`-Marker; AC3 verprobt die
Stufen-Reihenfolge. (Resolved in-story.)

### MF2 — Diff-/Git-Owner und noetige Helper explizit in Scope/AC klaeren (review §1, §Must-Fix 2)
**Finding:** FK-28 §28.3.6 fordert einen `GitOperations.diff_name_only()` in
`agentkit/core/git.py`; die Story liess den Diff-Owner unklar und warnte zugleich gegen
einen zweiten git-diff-Reader. Realcode hat **kein** `GitOperations`/`core/git.py`
(Grep `class GitOperations|diff_name_only|def diff` → 0; Glob `src/agentkit/**/git*.py`
→ nur `utils/git.py` (Worktree-Helfer, keine Diff-API) + `installer/github_coordinates.py`).
**Resolution (FIX THE MODEL):** Der reale SYSTEM-`git diff --name-only`-Owner existiert
bereits: `ChangeEvidencePort`/`ChangeEvidence.changed_files`
(`verify_system/structural/system_evidence.py:43-118`, `:68-69`), produktiv verdrahtet
via `_SubprocessGitChangeEvidenceProvider` (`bootstrap/composition_root.py:662`, Klasse
`:779-835`, `git diff --name-only {base}..HEAD` `:830-835`). Neuer §1-Absatz „Diff-/Git-Owner"
belegt das; In-Scope 1 (`repo_context.py`/`assembler.py` Stufe 1) konsumiert **diesen** Port;
neues AC11 verlangt explizit „kein zweiter git-diff-Reader, kein `GitOperations`/`core/git.py`".
Der `GitOperations`/`core/git.py`-Aufbau ist als Out-of-Scope „NICHT in AK3 gebaut" deklariert;
die FK-28-§28.3.6-Prosa ist FK-vs-Code-Drift und als doc-only-Nachzug geroutet (s. u.).
(Resolved in-story; cross-story doc-only-Nachzug benannt.)

### MF3 — Manifest-Determinismus vs. `evidence_epoch` sauber spezifizieren (review §2, §Must-Fix 3)
**Finding:** „Gleicher Input → byte-identisches Manifest" kollidiert mit `evidence_epoch`
als Assembly-Zeitpunkt (FK-28 §28.5.3/§28.5.4: `datetime.now(...)`).
**Resolution:** In-Scope 3 trennt jetzt: der reproduzierbare Teil ist `manifest_hash`
(SHA-256 ueber nach `(repo_id, str(path))` sortierte `repo_id:path:size`-Eintraege,
stufenreihenfolge-unabhaengig) + sortierte Entries/`merge_paths`; `evidence_epoch` ist der
**injizierbare** Assembly-Zeitpunkt (optionaler Clock-/Epoch-Parameter, Default UTC-`now`).
Formel praezisiert: „gleicher Input + gleicher Epoch → byte-identisch". Neues AC6 verprobt
beide Faelle (zwei Epochs → gleicher Hash/merge_paths, unterschiedlicher Epoch; gleicher
Epoch → byte-identisch). (Resolved in-story.)

### MF4 — `BundleEntry.repo` zu `repo_id` korrigieren (review §2, §Must-Fix 4)
**Finding:** Multi-Repo-AC/Scope nannten `BundleEntry.repo`; FK-28 §28.5.2/§28.5.4 nennt
`repo_id` (auch im Manifest-Hash `f"{e.repo_id}:{e.path}:{e.size}"`).
**Resolution:** Alle Vorkommen auf `repo_id` normalisiert (In-Scope 1 `authority.py`-Feldliste,
AC2, AC8). (Resolved in-story.)

### MF5 — Template-Platzhalter `{{BUNDLE_MANIFEST_HEADER}}` scopen oder Folge-Owner benennen (review §1 WARNING, §Must-Fix 5)
**Finding:** Der Platzhalter wurde ohne konkreten Owner aus dem Scope geschoben, obwohl
FK-28 §28.8.3 ihn normativ auffuehrt.
**Resolution:** In-Scope 6 aufgenommen: der **Python-Producer** `render_prompt_header()` ist
hier voll in Scope (Owner des Header-Texts); das **Einfuegen** des Platzhalters in die fuenf
`prompts/sparring/`-Templates (`review-consolidated/-spec-compliance/-implementation/
-test-sparring/-synthesis.md`) wird hier als reine Resource-Edits mitgezogen. Die
**Turn-seitige Substitution/Hydration** des Platzhalters ist explizit **AG3-062** (Review-Turn,
FK-46/47) — als Out-of-Scope mit Owner benannt. Damit hat jeder Teil einen konkreten Owner.
(Resolved in-story, klare Owner-Aufteilung AG3-061/AG3-062.)

### MF6 — `status.yaml.unblocks` mit Story-Index synchronisieren (review §4, §Must-Fix 6)
**Finding:** `status.yaml` sagte `unblocks: []`, der `_STORY_INDEX.md` zeigt AG3-062/063/067
als von AG3-061 abhaengig.
**Resolution:** `unblocks: [AG3-062, AG3-063, AG3-067]` gesetzt. Belegt durch
`_STORY_INDEX.md:53` (AG3-062 `depends_on … AG3-061`), `:54` (AG3-063 `depends_on AG3-043, AG3-061`),
`:58` (AG3-067 `depends_on AG3-043, AG3-053, AG3-061`). (Resolved in-status.)

### MF7 — Falsche FK-Abschnittsanker und falsche Ist-Zustand-Claims bereinigen (review §3, §Must-Fix 7)
**Finding (Anker):** Authority/BundleEntry/Manifest liegen real in **§28.5**, CLI in **§28.7**,
Tests in **§28.9**, Assembler/3-Stufen/Multi-Repo/Limit in **§28.3**, Header-Platzhalter in
**§28.8.3**; die Story verwies mehrfach falsch auf §28.3/§28.4/§28.6/§28.9.
**Resolution:** Quell-Konzept-Block + alle Inline-Referenzen auf die realen Anker korrigiert:
EvidenceAssembler/3-Stufen/RepoContext/350-KB → §28.3 (mit Unterabschnitten §28.3.1/§28.3.2/
§28.3.5/§28.3.6); AuthorityClass/BundleEntry/BundleManifest/Evidence-Epoch → §28.5 (§28.5.1/
§28.5.2/§28.5.3/§28.5.4); CLI → §28.7 (§28.7.1); Header-Platzhalter → §28.8.3; Test-Strategie
→ §28.9. (`render_prompt_header`/Hash-Formel ist real §28.5.3/§28.5.4, nicht §28.7/§28.8.)
**Finding (Ist-Zustand-Claims):** §1 behauptete, `evidence_manifest` komme im Code vor; Grep
`evidence_manifest` ueber `src/agentkit` (ohne `.pyc`) → 0 Treffer. CLI-Ist-Zustand nannte
`run`/`control-plane`; real sind `run-story`/`doctor`/`serve-control-plane`.
**Resolution:** §1 praezisiert: `evidence_fingerprint` mit echten Ankern belegt
(`story_context_manager/models.py:144/185-187`, `implementation/phase.py:237/758`); der
nicht existierende `evidence_manifest`-Claim entfernt; zusaetzlich der **echte** Namens-Konflikt
`evidence_epoch` (existiert bereits als `datetime`-Cycle-Feld `implementation/phase.py:236/738/757`,
`design_review.py:365` — anderes Modell als FK-28-`BundleManifest.evidence_epoch`) belegt und
sauber abgegrenzt. CLI-Commandnamen exakt auf `install`/`uninstall`/`run-story`/`doctor`/
`serve-control-plane` (`cli/main.py:41/104/110/131/134`, Dispatch `:151-160`) korrigiert.
(Resolved in-story.)

## WARNINGs (review §1/§2/§3)

### W1 — ACs testen keine FK-28-Worker-Hint-Regeln (review §2)
Resolved via MF1: neues AC4 deckt `worker-manifest.json`/`handover.json`, additive Hints,
keine Duplikate/Herabstufung und das Self-Reference-WARNING ab.

### W2 — Template-Platzhalter ohne Owner (review §1)
Resolved via MF5 (Producer + Template-Edit in AG3-061, Turn-Substitution AG3-062).

### W3 — Systematisch falsche FK-Abschnittsreferenzen (review §3)
Resolved via MF7 (alle Anker auf §28.3/§28.5/§28.7/§28.8.3/§28.9 korrigiert).

## NITs (review §3)
- `evidence_manifest`-Claim entfernt; nur `evidence_fingerprint` (+ neuer `evidence_epoch`-Konflikt)
  mit echten Ankern belegt. (MF7)
- CLI-Ist-Zustand auf `run-story`/`doctor`/`serve-control-plane` korrigiert. (MF7)

## Bestaetigte/verifizierte Anker (review §4 „Kontext-Sinnhaftigkeit")
- Kein konkurrierender `EvidenceAssembler`; `verify_system/evidence/__init__.py:1` ist der
  Einzeilen-Leerstub; `verify_system/llm_evaluator/bundle.py:9-20` ist die andere Layer-2-
  Bundle-Maschinerie (`build_review_bundle` `:130-196`, Konstanten `:37/:39`) — beibehalten und
  als „nicht duplizieren" verankert.
- Neu/praeziser verankert: `system_evidence.py:43-118` (`ChangeEvidencePort`/`ChangeEvidence.changed_files`),
  `composition_root.py:662/779-835` (`_SubprocessGitChangeEvidenceProvider`),
  `cli/main.py:41/104/110/131/134/151-160`, `story_context_manager/models.py:144`,
  `implementation/phase.py:236/237/738/757/758`.

## status.yaml
`unblocks: [AG3-062, AG3-063, AG3-067]` gesetzt (MF6). Keine weiteren Felder geaendert
(`status: draft`, `phase: review_pending` bleiben korrekt fuer den laufenden Review-Zyklus;
`depends_on: [AG3-022, AG3-026, AG3-044]` deckt sich mit `_STORY_INDEX.md:52` und bleibt).

## Genuine cross-story Voraussetzungen / Folge-Einheiten
1. **AG3-062 (Welle 1) — Import-Resolver (Stufe-2-Befuellung) + Request-DSL + Preflight-Turn +
   Review-Turn-`{{BUNDLE_MANIFEST_HEADER}}`-Substitution + `review-preflight.md` + Sentinel.**
   AG3-061 liefert nur den erweiterbaren Stufe-2-Eingang, den Header-Producer und den
   Platzhalter. Autoritativ via `_STORY_INDEX.md:53` (AG3-062 `depends_on … AG3-061`).
2. **AG3-063 (Welle 1) — ConformanceService-Nutzung des Manifest-Indexers** (FK-32).
   `_STORY_INDEX.md:54` (AG3-063 `depends_on AG3-043, AG3-061`).
3. **AG3-067 (Welle 1) — ContextSufficiencyBuilder + Section-aware Packing + sechsfeldriges
   ContextBundle** (FK-37/38). `_STORY_INDEX.md:58` (AG3-067 `depends_on AG3-043, AG3-053, AG3-061`).
4. **doc-only Konzept-Nachzug — FK-28 §28.3.6 Diff-Owner-Drift.** FK-28 §28.3.6 nennt
   `GitOperations.diff_name_only()` in `agentkit/core/git.py` als noetige Erweiterung; im AK3-Cut
   ist der Diff-Owner aber `ChangeEvidencePort` (`system_evidence.py`/`composition_root`), und
   `core/git.py` existiert nicht (BC-Topologie haelt `verify_system` subprocess-frei). Das ist
   FK-Prosa-vs-Code-Drift (Code/BC-Cut ist autoritativ). Gehoert in den doc-only Konzept-Nachzug
   (`_STORY_INDEX.md` Welle 10, AG3-101..104-Muster) an die FK-28-zustaendige doc-only-Einheit —
   **nicht** in den AG3-061-Code-Cut. AG3-061 bindet korrekt an den vorhandenen Port und meldet
   den Drift, mehr nicht.

Hinweis zur Cut-Treue: Producer `render_prompt_header()` + Platzhalter-Einfuegen bleiben bewusst
**innerhalb** AG3-061 (FK-28 §28.8.3 nennt den Platzhalter normativ; ohne Producer waere der
Platzhalter leer). Die Turn-seitige Hydration ist Teil des Review-Turns (AG3-062) und korrekt
dorthin geroutet — kein Anspruch, dass AG3-062 den Producer liefert.
