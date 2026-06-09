OVERALL APPROVE

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: PASS
- AC-Schaerfe: PASS
- Klarheit/Eindeutigkeit: PASS
- Kontext-Sinnhaftigkeit: PASS

**R3 ERROR**
- RESOLVED: `story.md` now consistently separates `bundle_id` from `skill_name`.
- `bundle_id` is profile-suffixed and directory-authoritative (`*-core` / `*-are`), matching `bundle_store.py` and the current on-disk manifests.
- Catalog completeness is checked via manifest `skill_name`, with explicit CORE and ARE bundles for `create-userstory` / `execute-userstory`.
- `lookup-userstory-core` and `llm-discussion-core` remain real bundle IDs while their FK identities are suffix-free `skill_name`s.

**Remaining Must-Fix ERRORs**
- None.
