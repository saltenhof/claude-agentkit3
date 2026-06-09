# AG3-066 — Remediation Round 6 (stale-text cleanup)

Scope of this round: **only** the two stale-text ERRORs from `review-r6.md`. Code
and ACs are PASS and were not touched. Sole edited deliverable file:
`stories/AG3-066-review-divergence-quorum/story.md`. No `concept/`, `src/`, or
`tests/` change.

---

## ERROR 1 — story contradicts current AG3-103 scope for the §68.2.2 payload row

**Finding (review-r6):** AG3-103 now explicitly owns the FK-68 §68.2.2
`review_divergence` payload-field row (`AG3-103/story.md:13`, `:36`, `:52`, `:63`),
but AG3-066 still claimed AG3-103 covers "aktuell nur" the §68.2 glossar value-list
and "nicht" the §68.2.2 payload row (`story.md:14`, `:32`, `:65`), and `:65`
contradicted itself by later saying AG3-103 carries it "inzwischen".

**Resolution:** Replaced the stale "aktuell nur / noch nicht im Owner-Scope / muss
erweitern" wording at all three spots with the current fact: AG3-103 now owns the
FK-68 §68.2.2 payload-row doc-only correction and aligns it from `score`/`routing`
to the FK-34 §34.8.4 field set; AG3-066's routing therefore points at a real,
owner-carried scope and is valid.

- `story.md:14` — replaced "AG3-103 fuehrt aktuell nur … nicht die §68.2.2-Payload-Feldzeile;
  das Routing benennt diese Luecke als nachzutragende Owner-Pflicht" with
  "AG3-103 fuehrt die §68.2.2-Payload-Feldzeile inzwischen als Owner-Scope
  (`AG3-103/story.md:13`, `:36`, `:52`, `:63`); das Routing … ist gueltig".
- `story.md:32` — replaced the "Offene Owner-Scope-Luecke … muss seine §68.2-Hoheit …
  ergaenzen" paragraph with an "Owner-Scope getragen" statement (both dimensions —
  glossar value-list and payload field row — carried by AG3-103; routing valid).
- `story.md:65` — removed the self-contradiction: the "Konkreter Routing-Auftrag …
  noch nicht im Owner-Scope … AG3-103 muss seinen … Scope erweitern" text plus the
  trailing "AG3-103 fuehrt … inzwischen als Owner-Scope" are now one consistent
  "Routing gueltig (Owner-Scope getragen)" statement.
- `story.md:98` (Guardrail section) — tightened the historical `depends_on`-removal
  justification so it no longer asserts an un-carried obligation; added the `:63`
  reference and reaffirmed the routing is valid.

## ERROR 2 — residual stale authority/citation text

**Finding (review-r6):** AG3-066 cited `:572` for the "Kap. 68" reference and used the
ambiguous phrase "wobei FK-68 … als Kap. 68 adressiert ist (`:572`)". FK-34 §34.8.4
writes the `review_divergence` event and references "(Kap. 68)" at `:573` (not `:572`);
FK-68 §68.2.2 is the stale owner row.

**Resolution:**
- `story.md:14` — corrected `:572` → `:573` for the "Kap. 68" reference.
- `story.md:31` — replaced "wobei FK-68 fuer dieses Event explizit als „Kap. 68"
  adressiert ist (`:572`)" with the clean relation: "FK-34 §34.8.4 schreibt das Event
  und referenziert dabei „Kap. 68" (`:573`)", and labelled the FK-68 §68.2.2 payload
  table explicitly as "die stale Telemetrie-Owner-Zeile".

No other `:572` occurrence remains in the file.

---

## Verification

- `grep` over `story.md` for `:572`, `aktuell nur`, `noch nicht im Owner-Scope`,
  `erweitern`, `noch nicht getragene`, `nachzutragende` → **no matches**.
- ARCH-55: no German code identifiers/keys introduced; edits are concept-prose only
  (German prose is permitted).
- Files written: **only** AG3-066 files — `story.md` (edited) and this
  `remediation-r6.md`. No AG3-103, `concept/`, `src/`, or `tests/` change.
