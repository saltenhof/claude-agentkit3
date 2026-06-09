# AG3-066 — Remediation r5 (Antwort auf review-r5.md)

**Datum:** 2026-06-08
**Scope der Remediation:** ausschliesslich `story.md`. Kein Produktionscode, keine Tests, **keine** `concept/`-Datei, **keine** fremde Story-Datei (AG3-103) angefasst. `status.yaml` **nicht** geaendert (kein Feld war falsch; `depends_on: AG3-037, AG3-043` bleibt der Index-Cut, `_STORY_INDEX.md:57`).
**Autoritative Quellen (re-read und verifiziert in diesem Lauf):**
- `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` §34.8.4: Sektion+Intro `:570-574`, „Kap. 68"-Verweis `:573` (Event schreibt **FK-34** und verweist auf Kap. 68), Feldtabelle `:575-582`, Mermaid Nicht-Divergenz `:589`. §34.8.2 Passthrough `get(raw, raw)` `:512-514`.
- `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` §68.2.2 Event-Katalog: Zeile `#### Review-Divergenz` mit stale `score (LOW/MEDIUM/HIGH)`/`routing` (`:358-362`). **Verifiziert: FK-68 §68.2.2 verweist NICHT auf „Kap. 68" und deferiert NICHT zurueck auf FK-34** — es ist eine reine (stale) Owner-Zeile.
- `stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md`: fuehrt FK-68 §68.2.2 Payload-Field-Row `review_divergence` inzwischen explizit als Owner-Scope (`:13`, `:36`, §2.1.4 letzter Bullet `:52`) und nennt FK-34 §34.8.4 nur als **autoritative Angleichungs-Quelle** (`:14`), **nicht** als zu aendernde FK-34-§34.8-Prosa. AG3-103 owned FK-68/Schema-Katalog-Scope, **nicht** FK-34-§34.8-Prosa.

---

## Round-5 Befunde: die zwei verbleibenden must-fix ERRORs

### ERROR 1 — Falsche Autoritaets-Zitierung „FK-68 verweist selbst (auf Kap. 68)"

**Finding (Reviewer, verifiziert):** FK-34 `:570-573` definiert den `review_divergence`-Telemetrie-Block und sagt, das Event liegt „Kap. 68". FK-68 `:287-362` enthaelt die stale Event-Katalog-Zeile; sie deferiert **nicht** zurueck auf FK-34 und referenziert auch nicht selbst „Kap. 68". AG3-066 behauptete dennoch „FK-68 verweist selbst" an `story.md:31`, `:65`, `:98`, `:105`.

**Resolution:** Alle vier Vorkommen ersetzt durch die korrekte Basis: **FK-34 §34.8.4 referenziert „Kap. 68" (`:573`) und definiert den neuen Feldsatz (`:575-582`); FK-68 §68.2.2 ist die stale Telemetrie-Owner-Zeile (`:358-362`), die per Owner-Scope-Erweiterung (AG3-103) anzugleichen ist.**
- `story.md:31` (§1 Konfliktcheck-Absatz): „FK-34 ist autoritativ und FK-68 verweist selbst dorthin" → „FK-34 §34.8.4 verweist auf ‚Kap. 68' (`:573`) und definiert den Feldsatz (`:575-582`); die FK-68-§68.2.2-Payload-Zeile ist die stale Telemetrie-Owner-Zeile (`:358-362`), per Owner-Scope-Erweiterung (AG3-103) anzugleichen".
- `story.md:65` (§2.2 FK-68-Prosa-Bullet, Schluss): „FK-68 verweist selbst auf ‚Kap. 68'" → „FK-34 §34.8.4 verweist auf ‚Kap. 68' (`:573`) und definiert den Feldsatz (`:575-582`)"; ergaenzt um den Beleg, dass AG3-103 die §68.2.2-Zeile inzwischen als Owner-Scope fuehrt (`AG3-103/story.md:13`, `:36`, `:52`).
- `story.md:98` (§5 KONZEPTTREUE-Bullet): „FK-68 verweist selbst auf ‚Kap. 68' (`:572`)" → „FK-34 §34.8.4 referenziert ‚Kap. 68' (`:573`) und definiert den neuen Feldsatz (`:575-582`); die FK-68-§68.2.2-Zeile ist die stale Telemetrie-Owner-Zeile (`:358-362`)".
- `story.md:105` (§6 Hinweise-Bullet): „FK-68 verweist auf ‚Kap. 68'" → „FK-34 §34.8.4 referenziert ‚Kap. 68' (`:573`) und definiert den Feldsatz", plus Verweis auf die stale FK-68-§68.2.2-Owner-Zeile (`:358-362`).

**Anker-Korrektur:** Der falsch zitierte „Kap. 68"-Verweis lag bei `:573` (nicht `:572`); in den korrigierten Stellen ist jetzt durchgaengig `:573` zitiert (verifiziert gegen FK-34).

### ERROR 2 — Falsches AG3-103-Routing fuer FK-34-No-majority/Passthrough-PROSE

**Finding (Reviewer, verifiziert):** AG3-066 routete „No-majority-Regel & Passthrough-Haerte" als **FK-34-§34.8-Prosa**-Ergaenzung an AG3-103 (`story.md:66`, `:93`, `:98`, `:108`). AG3-103 owned aber FK-68/Schema-Katalog-Scope, **nicht** FK-34-§34.8-Prosa (`AG3-103/story.md:12-14`, `:52`). Damit zeigte das Routing auf einen falschen Owner.

**Resolution:** Die Behauptung, AG3-103 sei der zustaendige Owner fuer die FK-34-No-majority/Passthrough-Prosa, **entfernt**. Kein neuer falscher Owner erfunden. Begruendung im Story-Text:
- **Passthrough:** FK-34 §34.8.2 gibt den `get(raw, raw)`-Passthrough fuer unbekannte Rohverdikte **explizit** vor (`:512-514`) — FK-34 §34.8.4/§34.8.2 ist bereits die autoritative Quelle, eine FK-Prosa-Aenderung ist **nicht** erforderlich.
- **No-majority:** ist eine bewusste, in der Story dokumentierte **Code-Entscheidung** (fail-closed strengstes Verdikt nach `PASS < CONCERN < FAIL`), abgedeckt und getestet durch die Code-AC **AC4** — keine FK-Prosa-Aenderung noetig.
- `story.md:66` (§2.2-Bullet): vom „FK-Praezisierungs-Routing … an AG3-103" auf „kein FK-Prosa-Routing noetig; AC4 deckt das No-majority-Verhalten ab; FK-34 §34.8.2/§34.8.4 sind bereits autoritativ" umgestellt; explizit vermerkt, dass AG3-103 FK-68/Schema-Katalog-Scope owned, nicht FK-34-§34.8-Prosa.
- `story.md:93` (§5 FAIL CLOSED): „Haertungsfrage an AG3-103 geroutet" → „abgedeckt durch Code-AC AC4; Passthrough folgt FK-34 §34.8.2 (`:512-514`); kein FK-Prosa-/Owner-Routing noetig".
- `story.md:98` (§5 KONZEPTTREUE): „FK-Luecken (No-majority, Passthrough-Haerte) ebenfalls an AG3-103 geroutet" entfernt; ersetzt durch „No-majority und Passthrough sind keine FK-34-§34.8-Prosa-Luecken — FK-34 §34.8.2 gibt Passthrough vor, No-majority ist Code-Entscheidung per AC4".
- `story.md:108` (§6 Hinweise): „FK-Prosa-Ergaenzung an AG3-103 geroutet" → „abgedeckt durch AC4; Passthrough folgt FK-34 §34.8.2; kein Routing an AG3-103 noetig".

**Beibehalten (valide, NICHT angefasst):** Das **FK-68-§68.2.2-Payload-Zeilen-Routing** an AG3-103 (`story.md:32`, `:62`, `:65`) bleibt — AG3-103 fuehrt die §68.2.2-Payload-Field-Row `review_divergence` inzwischen als Owner-Scope (`AG3-103/story.md:13`, `:36`, `:52`). Dieses Routing ist korrekt verortet und bleibt.

---

## Per-Dimension-Verdikte aus review-r5 — Abdeckung

- **Konzept-Vollstaendigkeit (FAIL: weiteres falsches FK-34-Prosa-Routing an AG3-103):** adressiert — das FK-34-No-majority/Passthrough-Routing ist entfernt; der korrekte (FK-68-§68.2.2) Owner-Scope-Routing-Pfad bleibt erhalten.
- **AC-Schaerfe (PASS):** unveraendert; AC1-9 bleiben konkret und buildbar (No-majority bleibt durch AC4 abgedeckt).
- **Klarheit/Eindeutigkeit (FAIL: „FK-68 verweist selbst auf Kap. 68"):** adressiert — alle vier Vorkommen auf die korrekte Quellrelation (FK-34 §34.8.4 → Kap. 68; FK-68 §68.2.2 = stale Owner-Zeile) umgeschrieben.
- **Kontext-Sinnhaftigkeit (PASS):** unveraendert; der reale Code-Delta (alter Score-Hook, fehlender Mandatory-Payload-Contract, Contract-Pin, Risk-Window-Excerpt) bleibt namentlich korrekt.

---

## Geaenderte Dateien
- `stories/AG3-066-review-divergence-quorum/story.md` (ERROR 1: vier „FK-68 verweist selbst"-Stellen `:31`/`:65`/`:98`/`:105` auf FK-34-§34.8.4-Hoheit + stale-FK-68-§68.2.2-Owner-Zeile umgeschrieben, Anker `:572`→`:573` korrigiert; ERROR 2: FK-34-No-majority/Passthrough-Routing an AG3-103 `:66`/`:93`/`:98`/`:108` entfernt, ersetzt durch FK-34-§34.8.2-Autoritaet + Code-AC4-Abdeckung; valides FK-68-§68.2.2-Routing beibehalten. AG3-057-Template-Struktur und ARCH-55 englische Keys unveraendert).
- `stories/AG3-066-review-divergence-quorum/remediation-r5.md` (dieser Report).
- `stories/AG3-066-review-divergence-quorum/status.yaml` (**nicht geaendert** — kein Feld war falsch).
