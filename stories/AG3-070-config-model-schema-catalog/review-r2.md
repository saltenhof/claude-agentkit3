OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: **FAIL**
- AC-Schaerfe: **FAIL**
- Klarheit: **PASS**
- Kontext-Sinnhaftigkeit: **FAIL**

**Round-1 Verification**
- `sonarqube.accept_frequency_fc_threshold`: **resolved**. Scope/AC require extending existing `SonarQubeConfig`, default `0.25`, `0..1` validation.
- Loader `ValueError` vs `ConfigError`: **resolved**. Story now splits model validator `ValueError` from loader `ConfigError`.
- `config_version` Ist-Zustand: **resolved**. Story correctly distinguishes missing config-field from existing telemetry/operative records.
- Existing `SonarQubeConfig`: **resolved**. Story explicitly extends current owner, no parallel stanza.
- FK-90 prose → AG3-103: **acceptable**.
- Schema-version inventory: **not resolved**.
- `unblocks`: **not resolved**.

**Remaining Must-Fix ERRORs**
1. **ERROR:** Schema-version inventory is still not genuinely explicit. `story.md:39-42` claims a “benannte Inventarliste”, but only names `ProjectConfig`; the artifact-owner families remain generic (“FK-90 names + code Pydantic owners”). `story.md:58` also references non-existent `§3.6`. This is not deterministic/buildable for contract-test scope. Fix: list the concrete Pydantic owner families/modules in AG3-070 or narrow the scope explicitly.

2. **ERROR:** `status.yaml.unblocks` is still incomplete. `stories/AG3-078.../status.yaml:21` has `depends_on: AG3-070`, but `AG3-070/status.yaml:10-15` omits `AG3-078`. Fix: add `AG3-078` to `unblocks` or document why inverse dependency metadata is intentionally not maintained.
