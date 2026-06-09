# AG3-066 — Remediation r3 (Antwort auf review-r3.md)

**Datum:** 2026-06-08
**Scope der Remediation:** ausschliesslich `story.md` + `status.yaml` (Dependency-Korrektur). Kein Produktionscode, keine Tests, keine `concept/`-Dateien angefasst.
**Autoritative Quellen (re-read und verifiziert):**
- `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` §34.8.2 (`:490-519`), §34.8.3 (`:521-568`), §34.8.4 Event-Felder (`:570-593`; „Kap. 68"-Verweis `:572`; Feldtabelle `:575-582`; Mermaid Nicht-Divergenz-Event `:589`).
- `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` Frontmatter `authority_over: eventing/telemetry-hooks` (`:9-13`); Sektionsstruktur `## 68.2 Event-Modell` (`:213`) → `### 68.2.2 Event-Katalog` (`:287`) → `#### Review-Divergenz` mit `score`/`routing`-Payload-Zeile (`:358-362`).
- `src/agentkit/telemetry/hooks/divergence_hook.py` (`_SCORE_LOW`/`_SCORE_HIGH` `:30-31`, `_PASS_VERDICTS` `:34`, Payload `score`/`routing` `:93-94`, Docstring „out of scope" `:8-11`, `_is_pass`/`_PASS_VERDICTS` `:143-144`, `_find_diverging_pair` `:147-166`).
- `src/agentkit/telemetry/events.py` (`EventType.REVIEW_DIVERGENCE` `:64`; `MANDATORY_PAYLOAD_FIELDS` `:173-221`, ohne `REVIEW_DIVERGENCE`).
- `tests/contract/telemetry/test_event_catalog.py` (`_EXPECTED_MANDATORY_FIELDS` `:112-141`; `test_mandatory_payload_fields_match_contract` `:149-150`).
- `src/agentkit/telemetry/risk_window/normalizer.py` (`REVIEW_DIVERGENCE → INTEGRITY` `:40`; `_EXCERPT_KEYS` mit `"score"` `:56-67`).
- `stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md` (FK-68 §68.2 als Quell-Konzept `:12`; In-Scope §2.1.4 nur Glossar-value-Liste `:48`).
- `var/concept-gap-analysis/_STORY_INDEX.md` (AG3-066-Cut `:57`; AG3-103 fuehrt FK-68 §68.2 als Owner `:144`).

---

## Round-3 Befund: verbleibender must-fix ERROR

### ERROR (r3) — FK-34/FK-68-Konflikt nicht genuin aufgeloest: als „bekannter Stale-Eintrag" reklassifiziert und an einen AG3-103-Scope geroutet, der die konkrete Payload-Zeile nicht abdeckt

**Beleg (Reviewer, verifiziert):**
- FK-68 besitzt Telemetrie-/Eventing-/Telemetry-Hooks-Hoheit (`68_telemetrie...md:9-13`) und deklariert `review_divergence` noch mit `reviewer_a`/`reviewer_b`/`score (LOW/MEDIUM/HIGH)`/`routing` (Payload-Zeile `:358-362`, unter `### 68.2.2 Event-Katalog`).
- FK-34 §34.8.4 schreibt den neuen Feldsatz vor und verweist auf „Kap. 68" (`:572`, `:575-582`) → echter FK-uebergreifender Widerspruch.
- **Kern des r3-Befunds:** AG3-103 fuehrt in Quell-Konzepten und In-Scope nur die **FK-68 §68.2-Glossar-`event-type-id`-value-Liste** (`AG3-103/story.md:12`, `:48`), **nicht** die §68.2.2-**Payload-Feldzeile** `review_divergence`. Die value-Liste (welche Event-Typen existieren) und die Payload-Feldtabelle (welche Felder ein Event traegt) sind getrennte Dimensionen — das Routing-Ziel deckte die konkrete Zeile bisher nicht ab.
- AG3-066 haengt nicht von AG3-103 ab (`status.yaml:8`) → keine Ordnungsgarantie; „Stale bis spaeter" = aufgeschoben, nicht behoben (Verstoss gegen ZERO DEBT / „genuin aufloesen").

**Behebung — genuine, geordnete Aufloesung (scope-treu, keine `concept/`-Aenderung in dieser Code-Story):**

1. **Harte Ordering-Dependency AG3-103 aufgenommen** (`status.yaml depends_on: + AG3-103`). Damit wird die FK-68-Payload-Zeile **vor** der Code-Schema-Migration dieser Story FK-34-konform nachgezogen. Konsequenz: Konzept und Code tragen zu **keinem** Zeitpunkt zwei widerspruechliche Divergenz-Formate — der Befund ist behoben, nicht aufgeschoben (FIX THE MODEL / SINGLE SOURCE OF TRUTH). Die „bekannter Stale-Eintrag"-Reklassifizierung ist vollstaendig entfernt.
2. **Routing praezisiert auf die exakte Zeile.** §1-Konfliktcheck und §2.2 benennen jetzt explizit die **FK-68 §68.2.2-Payload-Feldzeile** `review_divergence` (`:358-362`) als doc-only-Auftrag an AG3-103 und stellen klar: diese Zeile sitzt strukturell innerhalb des bereits gefuehrten §68.2-Owner-Cuts von AG3-103 (`#### Review-Divergenz` ⊂ `### 68.2.2 Event-Katalog` ⊂ `## 68.2 Event-Modell`). Zusaetzlich ist als **Routing-Praezisierung** vermerkt, dass AG3-103 neben der §68.2-Glossar-value-Liste die §68.2.2-Payload-Feldzeile explizit benennen muss — das schliesst die vom Reviewer benannte Scope-Luecke des Owners.
3. **Code-Migration unveraendert in Scope** (Hook-Payload, `MANDATORY_PAYLOAD_FIELDS`, Contract-Pin, `_EXCERPT_KEYS`; AC5a beibehalten) — wie vom Reviewer gefordert („Keep the code consumer migration already added in AC5a.").

Die vom Reviewer angebotene Alternative „FK-68-Tabellenkorrektur in AG3-066 aufnehmen" wurde **verworfen**, weil AG3-066 eine `code`-Story ist und `concept/`-Aenderungen ausserhalb ihres BC-Cuts liegen (STRUKTURREGELN / Rollentrennung). Der gewaehlte Branch — prior doc-only-Story als harte Dependency — ist genau die zweite vom Reviewer akzeptierte Option.

---

## Per-Dimension-Verdikte aus review-r3 — Abdeckung

- **Konzept-Vollstaendigkeit (FAIL: Konflikt nur acknowledged, nicht resolved):** behoben — AG3-103 ist jetzt harte `depends_on`-Dependency und zieht die FK-68 §68.2.2-Payload-Zeile **vor** der Code-Migration nach; kein „Stale-Eintrag" mehr.
- **Klarheit/Eindeutigkeit (FAIL: AG3-103-Scope deckt die Payload-Zeile nicht):** behoben — Routing zeigt jetzt praezise auf die §68.2.2-**Payload-Feldzeile** (getrennt von der §68.2-Glossar-value-Liste) und vermerkt den expliziten Routing-Auftrag an den Owner; die Zeile sitzt strukturell im bereits gefuehrten §68.2-Cut.
- **AC-Schaerfe (WEAK: ACs koennen passen waehrend FK-68-Tabelle widerspruechlich bleibt):** behoben durch die Ordnungs-Dependency — die FK-68-Tabelle ist beim Start von AG3-066 bereits angeglichen; AC5a (Pin + Contract-Pin + `_EXCERPT_KEYS`) bleibt unveraendert.
- **Kontext-Sinnhaftigkeit (PASS):** unveraendert; reale Consumer/Owner bleiben namentlich benannt.

---

## Code-/Konzept-Anker-Pruefung (gegen den realen Code/Concept, r3)

Alle in der Story zitierten Anker erneut verifiziert:
- `divergence_hook.py`: `_SCORE_LOW`/`_SCORE_HIGH` `:30-31`, `_PASS_VERDICTS` `:34`, Payload `score`/`routing` `:93-94`, Docstring `:8-11`, `_is_pass`/`_PASS_VERDICTS` `:143-144`, `_find_diverging_pair` `:147-166` — **korrekt**.
- `events.py`: `EventType.REVIEW_DIVERGENCE` `:64`, `MANDATORY_PAYLOAD_FIELDS` `:173-221` (ohne `REVIEW_DIVERGENCE`) — **korrekt**.
- `normalizer.py`: `REVIEW_DIVERGENCE → INTEGRITY` `:40`, `_EXCERPT_KEYS` `:56-67` (mit `score`) — **korrekt**.
- `test_event_catalog.py`: `_EXPECTED_MANDATORY_FIELDS` `:112-141`, `test_mandatory_payload_fields_match_contract` `:149-150` — **korrekt**.
- FK-34: §34.8.2 `:490-519`, §34.8.3 `:521-568`, Event-Felder `:575-582`, „Kap. 68" `:572`, Nicht-Divergenz `:589` — **korrekt**.
- FK-68: `authority_over` `:9-13`; **Anker-Korrektur**: die Payload-Zeile wurde von der frueheren Punktangabe `:362` auf den vollstaendigen Block `:358-362` (`#### Review-Divergenz`) praezisiert und um die Sektions-Verortung §68.2.2/§68.2 ergaenzt — der reale Zeilenwert `:362` bleibt enthalten, die Sektionszuordnung ist jetzt belegt (`:287`/`:213`).
- Routing-Anker: AG3-066-Cut `_STORY_INDEX.md:57`; AG3-103 (FK-68 §68.2) `_STORY_INDEX.md:144` — **korrekt**.

Es waren **keine falschen Code-Anker** zu korrigieren; die einzige Anker-Praezisierung betrifft den FK-68-Konzept-Block (`:362` → `:358-362` + Sektionsbeleg).

---

## status.yaml — Aenderung

`depends_on` um **AG3-103** ergaenzt (`AG3-037, AG3-043, AG3-103`). Begruendung: Die genuine, geordnete Aufloesung des FK-34/FK-68-Konflikts erfordert, dass die doc-only-Owner-Story der FK-68 §68.2.2-Payload-Zeile **vor** der Code-Schema-Migration laeuft. Das ist eine bewusste Praezisierung des coarse Index-Cuts (`_STORY_INDEX.md:57`), keine Erweiterung der Code-Facharbeit. Titel/Typ/Size unveraendert korrekt.

## Geaenderte Dateien
- `stories/AG3-066-review-divergence-quorum/story.md` (FK-68-Quell-Konzept-Bullet auf §68.2.2-Payload-Zeile + Dependency praezisiert; §1-Konfliktcheck auf geordnete Aufloesung via harte Dependency umgestellt; §2.2-FK-68-Routing + Reviewer-C-Bullet konsistent gezogen; §5-Konzepttreue + §6-Hinweise nachgezogen; FK-68-Anker `:362` → `:358-362`. AG3-057-Template-Struktur beibehalten).
- `stories/AG3-066-review-divergence-quorum/status.yaml` (`depends_on: + AG3-103`).
- `stories/AG3-066-review-divergence-quorum/remediation-r3.md` (dieser Report).
