# AG3-070 — Remediation r1 (Codex Review CHANGES-REQUESTED)

Scope of this remediation: `story.md` rewritten + `status.yaml` corrected (one field
genuinely wrong). No production code, tests, or `concept/` files touched. AG3-057 template
structure (sections 1–6, header fields) preserved unchanged.

All code anchors and FK references below were re-verified against the real tree; corrected
file:line references are reflected in the rewritten `story.md`.

---

## Konzept-Vollstaendigkeit

### ERROR — `sonarqube.accept_frequency_fc_threshold` owner-obligation fehlte
**Resolution: fixed in story (owner obligation now delivered).** Re-verified: FK-03 names the
field (`03_konfigurationsmodell_schemas_versionierung.md:184`, `:205` float `0..1` Default
`0.25`, `:458`), it sits UNDER the `sonarqube` stanza, and `_CROSS_STORY_PREREQS.md:6` (CP1)
assigns it to AG3-070 with AG3-078 as consumer. The field is now in scope (§2.1.4a), AC
(§3 AC4a: Default-test + `0..1` range negative test), negative-paths (§2.1.7), guardrails
(§5 FAIL-CLOSED), and sub-agent hints (§6). It explicitly **extends the existing
`SonarQubeConfig` owner**, not a parallel stanza (see Kontext-ERROR below). Quell-Konzepte
header updated with the FK anchor.

### PASS — VektorDB owner obligation
Confirmed already covered (§2.1.4 + AC4: `vectordb` stanza, `similarity_threshold=0.7`,
`max_llm_candidates=5`); matches `_STORY_INDEX.md:66` and the AG3-068 consumer. No change
needed beyond the consumer cross-link.

## AC-Schaerfe

### ERROR — Loader exception unscharf an der Code-Grenze
**Resolution: fixed in story.** Re-verified the real loader: `load_project_config` wraps
Pydantic validation in `ConfigError` (`config/loader.py:101-107`; `ConfigError` defined
`exceptions.py:26`), while the model validators raise `ValueError`. Scope §2.1.1 and AC1 now
split the contract cleanly: (a) the Pydantic validator throws `ValueError` (model negative
test); (b) `load_project_config` returns fail-closed `ConfigError` with the `ValueError` as
cause (loader negative test) — no bare `ValueError` escaping the loader, and no loader-API
change demanded. Guardrails §5 + hints §6 mirror this.

### WARNING — Schema-versioning AC zu breit ohne Inventarliste
**Resolution: fixed in story.** The blanket "jedes versionierte Artefakt-/Config-Modell" is
replaced by an explicit, **named + test-fixed owner inventory list** (FK-90 §90.1/§90.2 lists
concrete schema families). Scope §2.1.5 now enumerates `ProjectConfig` (`config_version`
field, `config/models.py:414`) plus the FK-90-named artefact/config Pydantic-owner families,
and AC5 requires a contract test that fixes the inventory list itself (a new versioned owner
without a list entry turns the test red) so family coverage cannot silently drift.

## Klarheit

### ERROR — Ist-Zustand-Claim `config_version` falsch
**Resolution: fixed in story.** Re-verified: `config_version` IS present as operative/
telemetric records (`closure/post_merge_finalization/records.py:30`, `:55-56`; installer
tracking), so the "only installer/registration.py" claim was false. §1 bullet rewritten to:
"no `config_version` in the config model/loader (`config/models.py:335-381`, `:414-443`;
`config/loader.py:52-107`); other operative/telemetric `config_version` records exist and are
NOT the `project.yaml` mandatory field (FK-03 §3.2.1)".

### WARNING — `llm_roles` grep-claim zu eng
**Resolution: fixed in story.** Re-verified: `llm_roles` appears as a closure-metrics record
(`closure/post_merge_finalization/records.py:31`, `:57-58`) beside the installer strings. §1
bullet narrowed to "no typed **config** field" and now names the real non-config occurrences.

## Kontext-Sinnhaftigkeit

### ERROR — Existierender partieller `SonarQubeConfig`-Owner ignoriert
**Resolution: fixed in story.** Re-verified: `class SonarQubeConfig` + `PipelineConfig.sonarqube`
exist (`config/models.py:122`, `:173-180`, `:380`) and are exported via
`config/__init__.py:22-25`, but lack `accept_frequency_fc_threshold`. New §1 bullet documents
this partial owner; §2.1.4a / AC4a / §6 mandate **extending** that owner (single truth), not a
second `sonarqube` stanza (FIX-THE-MODEL / SSOT).

### WARNING — `status.yaml.unblocks` leer vs. Index
**Resolution: fixed in `status.yaml`.** Verified against the authoritative dependent
`status.yaml` files (not only the index): AG3-068, AG3-069, AG3-088, AG3-089 and AG3-103 each
carry `depends_on: AG3-070`. `status.yaml.unblocks` changed from `[]` to
`[AG3-068, AG3-069, AG3-088, AG3-089, AG3-103]`. (The index also references these waves;
AG3-103 was additionally confirmed from its own `status.yaml`.)

---

## Must-Fix checklist (review §Must-Fix)
1. `sonarqube.accept_frequency_fc_threshold` in Scope/AC/Hinweise: Default `0.25`, `0..1`
   validation, tests — DONE (§2.1.4a, AC4a, §2.1.7, §5, §6).
2. Loader-exception expectation aligned to real `ConfigError` boundary, no API change — DONE
   (§2.1.1, AC1, §5, §6).
3. False Ist-Zustand grep claims for `config_version` and `llm_roles` corrected — DONE (§1).
4. Schema-versioning AC sharpened with named Pydantic-owner/family inventory list — DONE
   (§2.1.5, AC5).
5. `status.yaml.unblocks` reconciled against dependents — DONE.

## Corrected / verified code + concept anchors
- `SonarQubeConfig` partial owner: `config/models.py:122`, `:173-180`; in `PipelineConfig`:
  `:380`; exported `config/__init__.py:22-25`. Field absent — confirmed.
- Loader: `load_project_config` wraps validation in `ConfigError` `config/loader.py:101-107`;
  `ConfigError` `exceptions.py:26`; validators raise `ValueError`.
- `config_version`/`llm_roles` operative records: `closure/post_merge_finalization/records.py:30`,
  `:31`, `:55-56`, `:57-58`; installer strings `installer/registration.py`.
- No `config_version` in config model/loader: `config/models.py:335-381`, `:414-443`;
  `config/loader.py:52-107` — confirmed.
- FK-03 `accept_frequency_fc_threshold`: `03_konfigurationsmodell_schemas_versionierung.md:184`,
  `:205`, `:458` (stanza placement under `sonarqube`).
- Owner obligation: `_CROSS_STORY_PREREQS.md:6` (CP1).
- Dependents `depends_on: AG3-070`: AG3-068/069/088/089/103 status.yaml — confirmed.

## Genuine cross-story prerequisites (owner obligations, noted not silently absorbed)
- **CP1 (`_CROSS_STORY_PREREQS.md:6`):** `sonarqube.accept_frequency_fc_threshold` is an
  AG3-070 owner deliverable — now IN this story's scope/AC. The FK-03/FK-41 §41.10 PROSE
  alignment for this field stays **doc-only AG3-103** (not this story).
- **`vectordb` stanza** owner obligation (AG3-068 depends on it) — already in scope/AC; no
  carve-out needed.
- **FK-90 §90.1/§90.2 prose-to-Pydantic-reality rewrite** — explicitly out of scope with
  named owner **AG3-103** (doc-only); unchanged.
- Consumers (no logic here): `vectordb`→AG3-068; `telemetry.web_call_limit`→AG3-086;
  `governance.*`→AG3-085; `sonarqube.accept_frequency_fc_threshold`→AG3-078;
  migration→AG3-088/089.

## Files written (only AG3-070)
- `stories/AG3-070-config-model-schema-catalog/story.md` (rewritten)
- `stories/AG3-070-config-model-schema-catalog/status.yaml` (`unblocks` corrected)
- `stories/AG3-070-config-model-schema-catalog/remediation-r1.md` (this report)
