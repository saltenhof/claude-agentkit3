OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: **FAIL**. FK-34 no-majority/passthrough prose routing to AG3-103 is removed and code-AC-covered. FK-68 §68.2.2 routing to AG3-103 is valid now, but AG3-066 still contains stale text saying AG3-103 does **not** yet cover that payload row.
- AC-Schaerfe: **PASS**. AC1-9 remain concrete, buildable, and test-oriented.
- Klarheit/Eindeutigkeit: **FAIL**. The old “FK-68 verweist selbst” claim is gone, but two authority/citation spots still use stale `:572` / ambiguous FK-68-addressing wording.
- Kontext-Sinnhaftigkeit: **PASS**. Real code matches the described delta: old LOW/HIGH hook, no `telemetry/divergence.py`, no mandatory payload pin, and `risk_window` still preserves `score`.

**Remaining Must-Fix ERRORs**

ERROR 1: AG3-066 contradicts current AG3-103 scope for the §68.2.2 payload row.

Evidence: AG3-103 now explicitly covers FK-68 §68.2.2 `review_divergence` at `AG3-103/story.md:13`, `:36`, `:52`, `:63`. AG3-066 still says AG3-103 “aktuell nur” covers the §68.2 glossary and “nicht” the §68.2.2 payload row at `story.md:14`, `:32`, `:65`; `story.md:65` even contradicts itself by later saying AG3-103 covers it inzwischen.

Fix: Replace the stale “aktuell nur / noch nicht im Owner-Scope / muss erweitern” wording with the current fact: AG3-103 now owns the FK-68 §68.2.2 payload-row doc-only correction; AG3-066’s routing is therefore valid.

ERROR 2: Residual stale authority/citation text.

Evidence: FK-34 line 572 starts the event sentence; line 573 contains “(Kap. 68)”. AG3-066 still cites `:572` for the Kap.-68 reference at `story.md:14` and uses the ambiguous phrase “wobei FK-68 … als Kap. 68 adressiert ist (`:572`)" at `story.md:31`, before correcting it later in the same sentence.

Fix: Make both spots match the clean relation: FK-34 §34.8.4 writes the `review_divergence` event and references Kap. 68 at `:573`; FK-68 §68.2.2 is the stale owner row.
