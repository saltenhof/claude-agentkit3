# AG3-066 — Remediation r4 (Antwort auf review-r4.md)

**Datum:** 2026-06-08
**Scope der Remediation:** ausschliesslich `story.md` + `status.yaml`. Kein Produktionscode, keine Tests, **keine** `concept/`-Datei, **keine** fremde Story-Datei (AG3-103) angefasst — wie vom Auftrag verlangt.
**Autoritative Quellen (re-read und verifiziert):**
- `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` §34.8.4 Telemetrie-Integration: Sektion+Intro `:570-574`, Feldtabelle `:575-582`, „Kap. 68"-Verweis `:572`, Mermaid Nicht-Divergenz `:589`.
- `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` `authority_over: eventing/telemetry-hooks` (`:9-13`); `#### Review-Divergenz`-Payload-Zeile `score`/`routing` (`:358-362`, in `### 68.2.2 Event-Katalog`).
- `stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md`: Quell-Konzept FK-68 **§68.2** Glossar-value-Liste (`:12`), In-Scope §2.1.4 nur Glossar-value-Liste (`:48`), AC4 nennt FK-68 §68.2 als interner-Widerspruch-Eintrag (`:58`) — **keine** §68.2.2-Payload-Feldzeile.
- `var/concept-gap-analysis/_STORY_INDEX.md`: AG3-066-Cut `depends_on: AG3-037, AG3-043` (`:57`); AG3-103 fuehrt FK-68 §68.2 als Owner (`:144`). Kein anderer Eintrag owned die §68.2.2-Payload-Feldzeile (AG3-081 ist Code-Scope BC14/BC15-Events, nicht die Divergenz-Prosa).
- `src/agentkit/telemetry/hooks/divergence_hook.py`: Docstring FK-68 §68.2.2 + „out of scope" (`:1-12`), `_SCORE_LOW`/`_SCORE_HIGH` (`:30-31`), `_PASS_VERDICTS` (`:34`), Payload `score`/`routing` (`:93-94`) — alle Anker **korrekt**.

---

## Round-4 Befund: verbleibender must-fix ERROR

### ERROR (r4) — Routing-Ziel AG3-103 traegt die §68.2.2-Payload-Zeilen-Pflicht nicht; der r3-Befund war ueber eine harte Dependency nur kaschiert, nicht geloest

**Beleg (Reviewer, verifiziert):**
- FK-34 definiert den `review_divergence`-Feldsatz autoritativ (`34_llm...md:570-582`) und verweist fuer das Event auf „Kap. 68" (`:572`).
- FK-68 owned Telemetrie/Eventing-Schema und deklariert `review_divergence` **noch** mit `score`/`routing` (`68_telemetrie...md:9-13`, `:358-362`).
- AG3-066 hatte AG3-103 als harte `depends_on` aufgenommen (frueher `status.yaml:8-11`) und behauptete, AG3-103 ziehe die §68.2.2-Payload-Zeile nach.
- **Aber:** AG3-103s eigener Scope/AC nennt nur die FK-68 **§68.2-Glossar-value-Liste** (`AG3-103/story.md:12`, `:48`, `:58`), **nicht** die §68.2.2-Payload-Feldzeile. Die behauptete Pflicht existiert beim Owner nicht — die Dependency garantierte eine Ordnung fuer eine Pflicht, die niemand traegt.

**Kernspannung mit dem Remediations-Auftrag:** Der Reviewer schlaegt als Fix vor, **AG3-103 selbst** zu aendern. Das ist genau verboten („Do NOT touch … concept files — ONLY story.md (+status.yaml)"; AG3-103/story.md ist eine **fremde** Story-Datei ausserhalb des AG3-066-Cuts, Rollentrennung). Die zulaessige Aktion ist „fix in-story **oder** korrekt an den Owner routen". Daher wurde die Symptom-Behandlung (harte Dependency) durch eine **modell-ehrliche** Loesung ersetzt.

**Behebung — entlang der Hoheiten, scope-treu (FIX THE MODEL, NOT THE SYMPTOM):**

1. **Konfliktaufloesung an den Hoheiten festgemacht statt an einer Reihenfolge.** FK-34 §34.8.4 (`:570-582`) ist die **autoritative Feldsatz-Quelle** fuer `review_divergence`, und FK-68 verweist fuer dieses Event **selbst** auf „Kap. 68" (`:572`). Damit ist die **Code-Schema-Migration FK-34-autoritativ** und **nicht** durch den Stand der FK-68-Prosa blockiert. Die stale FK-68-Prosa-Zeile ist eine separate `concept/`-doc-only-Schuld, die sichtbar an ihren Owner gehoert — nicht hinter einem Dependency-Pfeil versteckt.
2. **Harte `depends_on: AG3-103` entfernt** (`status.yaml` zurueck auf den Index-Cut `AG3-037, AG3-043`, `_STORY_INDEX.md:57`). Begruendung: Eine harte Abhaengigkeit auf eine Story, die die Pflicht **nicht** traegt, ist eine **fabrizierte Ordnungs-Garantie** — sie macht das Konzept nicht konsistent, sie verbirgt die Luecke nur. Das verstoesst gegen FIX THE MODEL; die Garantie war Schein.
3. **Routing praezisiert auf eine explizite Owner-Scope-Erweiterung an AG3-103.** §1 und §2.2 benennen jetzt klar: AG3-103 (FK-68 §68.2-Owner, doc-only) muss seinen Scope um die **§68.2.2-Payload-Feldzeile** `review_divergence` (`:358-362`) **erweitern** und sie von `score`/`routing` auf den FK-34-Feldsatz (`:570-582`) angleichen. Es ist explizit vermerkt, dass AG3-103s heutiger Scope nur die §68.2-Glossar-value-Liste fuehrt (`AG3-103/story.md:12`, `:48`, `:58`) und dass AG3-066 diesen Owner-Scope **nicht** aus der eigenen Story heraus erweitern darf (Rollentrennung). Damit ist die Luecke benannt und korrekt verortet, nicht verschwiegen und nicht ueberbehauptet.
4. **Code-Migration unveraendert in Scope** (Hook-Payload, `MANDATORY_PAYLOAD_FIELDS`, Contract-Pin, `_EXCERPT_KEYS`; AC5a beibehalten) — der reale Code-Delta und die Consumer sind vom Reviewer als PASS (Kontext-Sinnhaftigkeit) bestaetigt und bleiben.

**Warum nicht die Reviewer-Alternative „AG3-103 selbst aendern":** Das liegt ausserhalb der erlaubten Remediations-Oberflaeche (nur `story.md`/`status.yaml` von AG3-066). AG3-103s Scope-Pflicht kann nur in AG3-103s eigenem Remediations-/Authoring-Lauf eingetragen werden; AG3-066 leistet die ihm zustehende Haelfte: korrektes, explizites Routing der Pflicht an den verifizierten Owner und Entfernen der irrefuehrenden harten Abhaengigkeit.

---

## Per-Dimension-Verdikte aus review-r4 — Abdeckung

- **Konzept-Vollstaendigkeit (FAIL: AG3-103 owned die §68.2.2-Payload-Zeile nicht):** adressiert — die Konfliktaufloesung haengt nicht mehr an AG3-103s (nicht vorhandener) Pflicht, sondern an der FK-34-Hoheit (FK-68 verweist selbst dorthin). Die §68.2.2-Prosa-Zeile ist als **explizite Owner-Scope-Erweiterung** an AG3-103 geroutet, mit klarer Benennung der heutigen Scope-Luecke.
- **AC-Schaerfe (FAIL: Vorbedingungs-Story kann ihre ACs erfuellen ohne die Payload-Zeile):** adressiert — AG3-066 macht sich nicht mehr von einer Vorbedingungs-Story abhaengig, deren ACs die Zeile gar nicht erzwingen. AC5a (Code-Schema-Pin) bleibt scharf und FK-34-autoritativ, unabhaengig vom FK-68-Prosa-Timing.
- **Klarheit/Eindeutigkeit (FAIL: AG3-066 sagt AG3-103 „muss", AG3-103-Scope sagt nur §68.2-Glossar):** adressiert — die Story behauptet nicht mehr, AG3-103 trage die Pflicht bereits; sie benennt die Luecke explizit und routet sie als nachzutragende Owner-Pflicht, ohne fremde Story-Dateien zu aendern.
- **Kontext-Sinnhaftigkeit (PASS):** unveraendert; realer Code-Delta/Consumer bleiben namentlich korrekt.

---

## Code-/Konzept-Anker-Pruefung (gegen den realen Code/Concept, r4)

Alle zitierten Anker erneut verifiziert:
- `divergence_hook.py`: Docstring/FK-68-§68.2.2-Bezug+„out of scope" `:1-12`, `_SCORE_LOW`/`_SCORE_HIGH` `:30-31`, `_PASS_VERDICTS` `:34`, Payload `score`/`routing` `:93-94` — **korrekt**.
- FK-34 §34.8.4: Sektion+Intro `:570-574`, „Kap. 68" `:572`, Feldtabelle `:575-582`, Nicht-Divergenz-Mermaid `:589` — **korrekt**. **Anker-Praezisierung:** wo die Story auf das **ganze §34.8.4-Telemetrie-Integrations-Block als autoritative Feldsatz-Quelle** verweist, wird jetzt `:570-582` zitiert (Sektion+Tabelle); die reine Feldtabelle bleibt `:575-582`. Beide Werte sind real und konsistent.
- FK-68: `authority_over` `:9-13`; `#### Review-Divergenz`-Payload-Zeile `:358-362` (in `### 68.2.2`) — **korrekt**.
- AG3-103: FK-68 §68.2 Glossar als Quell-Konzept `:12`, In-Scope §2.1.4 nur Glossar-value-Liste `:48`, AC4 `:58` — **korrekt** belegt, dass die §68.2.2-Payload-Zeile **nicht** im Owner-Scope steht.
- Routing-/Index-Anker: AG3-066-Cut `_STORY_INDEX.md:57`, AG3-103 FK-68 §68.2 `_STORY_INDEX.md:144` — **korrekt**.

Es waren **keine falschen Code-Anker** zu korrigieren; die einzige Anker-Praezisierung betrifft die FK-34-Block-Referenz (`:575-582` → `:570-582` dort, wo die ganze §34.8.4-Hoheit gemeint ist).

---

## status.yaml — Aenderung

`depends_on` zurueck auf den Index-Cut **`AG3-037, AG3-043`** (`_STORY_INDEX.md:57`); **AG3-103 entfernt**. Begruendung: Die harte Abhaengigkeit war eine fabrizierte Ordnungs-Garantie fuer eine Pflicht, die AG3-103s Scope nicht traegt; sie loeste den FK-34/FK-68-Konflikt nicht, sondern kaschierte ihn. Die genuine Aufloesung laeuft ueber die FK-34-Feldsatz-Hoheit (Code-Migration) + sichtbares Owner-Scope-Routing an AG3-103 (Prosa). Titel/Typ/Size/`phase`/`status` unveraendert korrekt.

## Geaenderte Dateien
- `stories/AG3-066-review-divergence-quorum/story.md` (FK-68-Quell-Konzept-Bullet: harte-Dependency-Framing → FK-34-Hoheit + Owner-Scope-Routing + explizite AG3-103-Scope-Luecke; §1-Konfliktcheck auf Hoheiten-Aufloesung + entfernte Dependency umgestellt; Owner-Abgrenzungs-Absatz auf reinen Index-`depends_on` zurueckgezogen; §2.2-AG3-065-Notiz + FK-68-Prosa-Bullet als explizites Routing statt Ordering-Zwang; §5-Konzepttreue + §6-Hinweise nachgezogen; FK-34-Block-Anker `:575-582` → `:570-582` wo die ganze §34.8.4-Hoheit gemeint ist. AG3-057-Template-Struktur beibehalten, ARCH-55 englische Keys unveraendert).
- `stories/AG3-066-review-divergence-quorum/status.yaml` (`depends_on` zurueck auf `AG3-037, AG3-043`; AG3-103 entfernt).
- `stories/AG3-066-review-divergence-quorum/remediation-r4.md` (dieser Report).
