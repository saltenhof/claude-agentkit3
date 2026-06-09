OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

ERROR: Die 3-Stufen-Assembly ist falsch geschnitten. Story macht Stufe 3 zu “Aggregation + Manifest-Bau” und zieht Handover in Stufe 1; FK-28 definiert Stufe 3 aber als Worker-Hints aus `handover.json`/`worker-manifest.json`, danach erst Dedup/Limit/Manifest. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:33`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:153`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:173`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:352`. Fix: Stufen exakt auf FK-28 ausrichten und Worker-Hint-Regeln inkl. additiv/nicht-herabstufen/Self-Reference-Warning aufnehmen.

ERROR: FK-28 fordert Git-Diff-Helfer als benötigte Erweiterung, die Story lässt den Diff-Owner unklar und warnt zugleich gegen einen zweiten Git-Diff-Reader. Realcode hat keinen `GitOperations`/`diff_name_only`; nur `src/agentkit/utils/git.py` ohne Diff-API. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:33`, `stories/AG3-061-evidence-assembly-core/story.md:62`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:560`, `src/agentkit/utils/git.py:58`. Fix: Diff-Provider/Modulpfad explizit entscheiden und als Scope+AC aufnehmen.

WARNING: Template-Platzhalter `{{BUNDLE_MANIFEST_HEADER}}` wird ohne konkreten Owner aus Scope geschoben, obwohl FK-28 ihn normativ aufführt. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:43`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:936`. Fix: Entweder in AG3-061 aufnehmen oder konkrete Folge-Story/Owner im Status/Index benennen.

**2) AC-Schaerfe: FAIL**

ERROR: “Gleicher Input -> byte-identisches Manifest” kollidiert mit `evidence_epoch` als Assembly-Zeitpunkt. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:35`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:725`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:781`. Fix: Determinismus auf `manifest_hash`/sortierte Entries begrenzen oder Clock/`evidence_epoch` explizit injizierbar machen: gleicher Input + gleicher Epoch -> byte-identisch.

ERROR: Multi-Repo-AC nennt `BundleEntry.repo`; FK-28 nennt `repo_id`. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:30`, `stories/AG3-061-evidence-assembly-core/story.md:52`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:646`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:657`. Fix: Feldname auf `repo_id` normalisieren.

WARNING: ACs testen keine FK-28-Worker-Hint-Regeln. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:47`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:373`. Fix: AC/Test fuer `worker-manifest.json`, additive Hints, keine Duplikate/Herabstufung, Self-Reference-Warning ergänzen.

**3) Klarheit: WEAK**

WARNING: FK-28-Abschnittsreferenzen sind systematisch falsch. Authority/BundleEntry/Manifest liegen real in §28.5, CLI in §28.7, Tests in §28.9; Story verweist mehrfach auf §28.3/§28.4/§28.6/§28.9. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:7`, `stories/AG3-061-evidence-assembly-core/story.md:30`, `stories/AG3-061-evidence-assembly-core/story.md:36`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:600`, `concept/technical-design/28_evidence_assembly_review_vorbereitung.md:817`. Fix: Abschnittsanker korrigieren.

NIT: Ist-Zustand behauptet `evidence_manifest` komme im Code vor; Suche in `src/agentkit` ohne `.pyc` hat 0 Treffer. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:21`. Fix: Satz auf `evidence_fingerprint` beschränken oder echten Anchor liefern.

NIT: CLI-Ist-Zustand nennt `run`/`control-plane`; real sind `run-story`, `doctor`, `serve-control-plane`. Evidence: `stories/AG3-061-evidence-assembly-core/story.md:22`, `src/agentkit/cli/main.py:110`, `src/agentkit/cli/main.py:131`, `src/agentkit/cli/main.py:134`. Fix: Commandnamen exakt nennen.

**4) Kontext-Sinnhaftigkeit: FAIL**

ERROR: `status.yaml` widerspricht dem Story-Index: Index zeigt AG3-062, AG3-063 und AG3-067 als von AG3-061 abhängig, Status sagt `unblocks: []`. Evidence: `stories/AG3-061-evidence-assembly-core/status.yaml:12`, `var/concept-gap-analysis/_STORY_INDEX.md:53`, `var/concept-gap-analysis/_STORY_INDEX.md:54`, `var/concept-gap-analysis/_STORY_INDEX.md:58`. Fix: `unblocks` auf die abhängigen Stories setzen.

PASS mit Einschränkung: Kein konkurrierender `EvidenceAssembler` existiert; `verify_system/evidence/__init__.py` ist wirklich ein Einzeilen-Leerstub, und `build_review_bundle` ist eine andere Layer-2-Bundle-Maschinerie. Evidence: `src/agentkit/verify_system/evidence/__init__.py:1`, `src/agentkit/verify_system/llm_evaluator/bundle.py:9`.

**Must-Fix**

1. FK-28-Stufenmodell korrigieren, insbesondere Worker-Hints als Stufe 3.
2. Diff-/Git-Owner und nötige Helper explizit in Scope/AC klären.
3. Manifest-Determinismus vs. `evidence_epoch` sauber spezifizieren.
4. `BundleEntry.repo` zu `repo_id` korrigieren.
5. Template-Platzhalter entweder scopen oder mit konkretem Folge-Owner versehen.
6. `status.yaml.unblocks` mit Story-Index synchronisieren.
7. Falsche FK-Abschnittsanker und falsche Ist-Zustand-Claims bereinigen.
