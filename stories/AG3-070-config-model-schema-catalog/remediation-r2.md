# AG3-070 — Remediation r2 (Codex Review CHANGES-REQUESTED, round 2)

Scope of this remediation: `story.md` rewritten in place + one `status.yaml` field
corrected. No production code, tests, or `concept/` files touched. AG3-057 template
structure (header fields + sections 1–6) preserved unchanged. All code/concept anchors
below re-verified against the real tree.

Round-2 review left exactly two Remaining Must-Fix ERRORs. Both are resolved.

---

## ERROR 1 — Schema-version inventory not genuinely explicit / non-existent `§3.6` / generic families

**Review finding (`review-r2.md:19`):** `story.md:39-42` claimed a "benannte Inventarliste"
but only named `ProjectConfig` and otherwise stayed generic ("FK-90 names + code Pydantic
owners"). `story.md:58` referenced a non-existent `§3.6`. Not deterministic/buildable for
contract-test scope. Fix demanded: list concrete Pydantic owner families/modules in AG3-070
OR narrow the scope explicitly.

**Root cause found (decisive):** FK-03 §3.3.4 defines **two independent** versioning areas:
(a) Pipeline-Config (`project.yaml` → `config_version`) and (b) QA-artefacts (JSON envelopes
→ `schema_version`). The artefact-`schema_version` area is **already owned and implemented in
code** — `ArtifactEnvelope.schema_version: Literal["3.0"]` (`artifacts/envelope.py:85`,
constant `ENVELOPE_SCHEMA_VERSION` `:44`) and `ChangeFrame.schema_version`
(`exploration/change_frame.py:318`, validated fail-closed). AG3-070 is the `project-config`
BC; it does **not** own those artefact families. The generic "FK-90 artefact families"
inventory claim was therefore both unbuildable in-cut and an SSOT overreach.

**Resolution: narrowed the scope explicitly to the in-cut Config owner; routed the artefact
area to its existing code owners; fixed the bad anchor.**
- §2.1.5 (Scope) and AC5/AC6 rewritten to a **concrete, complete, single-owner Config list**:
  the only `config_version` owner is `PipelineConfig` (`config/models.py:335`, FK-03 §3.2.1
  places `config_version` there), reached from the root `ProjectConfig`
  (`config/models.py:414`) via `ProjectConfig.pipeline` (`:439`), which carries **no** second
  version field. The contract test fixes exactly this list (a new Config-`config_version`
  owner OR a second config version owner turns it red).
- The artefact/envelope `schema_version` families are now **explicitly out of cut** with their
  real code owners named — new §1 Ist-Zustand bullet + new §2.2 Out-of-Scope bullet +
  §6 hint + Quell-Konzepte FK-03 §3.3.4 anchor.
- Non-existent `§3.6` reference removed (AC5 rewritten); correct anchor is FK-03 §3.3.4
  (two-versioning-areas table), verified at `03_konfigurationsmodell_schemas_versionierung.md`
  §3.3.4.
- §2.1.7 negative-path "unbekannte `schema_version` eines Artefakts" removed from AG3-070
  (it belongs to the artefact BC); the `config_version` negative path is kept and now names
  the `PipelineConfig` owner. AC1 owner anchor corrected to `PipelineConfig` (`:335`).

## ERROR 2 — `status.yaml.unblocks` incomplete (missing AG3-078)

**Review finding (`review-r2.md:21`):** `AG3-078/status.yaml:21` declares `depends_on: AG3-070`,
but `AG3-070/status.yaml` omitted `AG3-078` from `unblocks`.

**Resolution: fixed in `status.yaml`.** Re-verified the authoritative dependent
(`stories/AG3-078-failure-corpus-pattern-check-factory/status.yaml:20-21`: `depends_on`
includes `AG3-070`, with the CP1 `accept_frequency_fc_threshold` rationale inline).
`status.yaml.unblocks` changed from `[AG3-068, AG3-069, AG3-088, AG3-089, AG3-103]` to
`[AG3-068, AG3-069, AG3-078, AG3-088, AG3-089, AG3-103]`.

---

## Round-1 carry-overs (review-r2 marked resolved) — left unchanged
`sonarqube.accept_frequency_fc_threshold`, loader `ValueError`→`ConfigError` boundary,
`config_version` Ist-Zustand, existing `SonarQubeConfig` extension, FK-90→AG3-103 doc-only:
all verified still correct and untouched.

## Verified anchors (this round)
- Two versioning areas: FK-03 §3.3.4 (`config_version` vs artefact `schema_version`).
- Config owner: `PipelineConfig` `config/models.py:335`; `config_version` per FK-03 §3.2.1;
  root `ProjectConfig` `:414`; `ProjectConfig.pipeline` `:439`.
- Artefact owners (out of cut): `artifacts/envelope.py:85` (`:44`),
  `exploration/change_frame.py:318`.
- Dependent edge: `AG3-078/status.yaml:20-21` `depends_on: AG3-070`.

## Scope honesty (no false owner claims)
AG3-078 is NOT claimed to deliver anything beyond its scope; it is recorded only as a
downstream consumer of the `accept_frequency_fc_threshold` field AG3-070 owns (CP1), and as
an `unblocks` edge. The artefact `schema_version` area is attributed to its real existing
code owners, not silently absorbed into AG3-070.

## Files written (only AG3-070)
- `stories/AG3-070-config-model-schema-catalog/story.md` (rewritten sections)
- `stories/AG3-070-config-model-schema-catalog/status.yaml` (`unblocks` += AG3-078)
- `stories/AG3-070-config-model-schema-catalog/remediation-r2.md` (this report)
