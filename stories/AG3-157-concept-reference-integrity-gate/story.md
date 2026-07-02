# AG3-157 — Konzept-Referenz-Integritäts-Gate (W1): Auflösbarkeit aller Querverweise (Dokument-IDs, §-Anker, formal.*-IDs, Dateipfade) als deterministisches CI-Pflichtgate + scope-qualifizierte defers_to-Azyklik

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [] — startbar: W1 ist nach META §7-Fahrplan Punkt 1 der
  erste Werkzeug-Baustein („deterministisch, billig, sofortiger Nutzen;
  keine Abhängigkeiten"); rein statische Prüfung ohne LLM, ohne
  Backend-/Schema-Bezug.
- **unblocks:** [AG3-158] — **Sequenz-Kante** nach META §7-Fahrplan
  (W1 zuerst, W4 danach), **keine technische Abhängigkeit**.
- **Quell-Konzept:** META-CONCEPT-CONSISTENCY
  (`concept/_meta/konzept-konsistenz-governance.md`) §5/W1 (Spezifikation
  inkl. Zusatzauftrag defers_to-Zyklen), §6 (Betriebsmodell: Pflichtgate in
  derselben CI-Stufe wie die vier bestehenden Konzept-Gates), §7 (Fahrplan
  Punkt 1), §3/P5 (Referenz-Integrität, Befund-Schwere ERROR),
  §4 (Severity-Zuordnung)
- **Herkunft:** Konzept-Konsistenz-Governance (META-Dokument, aktiv);
  PO-Freigabe 2026-07-02. Kein GAP-Nenner-Bezug — eigener Strang.

## Kontext / Problem

P5 (META §3) normiert: Alle Querverweise im Korpus (FK-/DK-/META-
Dokument-IDs, §-Abschnittsanker, formal.*-IDs, Dateipfade) müssen
auflösen; tote Anker sind das Frühsymptom auseinandergelaufener Dokumente
(Beispiel: „FK-02 verwies auf FK-71 §67.x" — die Abschnitte heißen seit
der Umnummerierung §71.x). Befund-Schwere ERROR. Der Ist-Zustand deckt
das nur in schmalen Ausschnitten ab (am Code verifiziert 2026-07-02):

- **`scripts/ci/compile_formal_specs.py`** (:41-44) kompiliert die
  Formal-Specs (Dokumente/IDs/Referenzen/Szenarien) und ruft zwei Audits
  aus `tools/concept_compiler/drift.py`:
  - `audit_formal_prose_links` (:34-100): prüft **Dokument-Ebene** —
    `prose_refs` der Formal-Docs existieren als Datei (:49-54), die
    Prosa deklariert reziprok `formal_refs`, `<!-- PROSE-FORMAL: … -->`-
    Anker referenzieren nur bekannte Formal-**Dokument**-IDs (:83-88),
    strict-Anchor-Policy (:90-96).
  - `audit_concept_doc_classification` (:103-154): jedes Konzeptdokument
    ist formal verlinkt oder explizit `prose-only`.
  **Was fehlt:** §-Anker-Auflösung gegen reale Überschriften,
  `formal.*`-**Item**-IDs in Prosa-Fließtext (nur Doc-IDs in
  PROSE-FORMAL-Ankern werden geprüft), Dateipfad-Verweise in Prosa,
  META-/Decision-Record-IDs.
- **`scripts/ci/check_concept_frontmatter.py`** prüft L7 „FK-/DK-Body-
  Referenzen müssen auflösen" (:475-484) — aber nur **Existenz der
  Dokument-ID** (`BODY_REF_RE` :58 matcht ausschließlich
  `(FK|DK)-\d{2}`), keine §-Anker, keine META-IDs, keine Pfade; und nur
  über `concept/technical-design/*.md` + `concept/domain-design/*.md`
  **nicht-rekursiv** (`load_concept_docs` :109-125) — `concept/_meta/**`
  (inkl. `decisions/`) und `concept/formal-spec/**`-Prosa sind
  unabgedeckt. L3 prüft `defers_to`-**Ziel-Existenz** (:262-273); L9
  prüft Azyklik **nur über `parent_concept_id`** — `defers_to` ist per
  Code-Kommentar ausdrücklich ausgenommen (:369-372).
- **Zusatzauftrag-Befund (META §5/W1, am Bestand verifiziert 2026-07-02):**
  Der dokumentweite `defers_to`-Graph ist stark zyklisch —
  Frontmatter-verifiziert: FK-63 → FK-70 **und** FK-70 → FK-63
  (`63_auswertung_und_dashboard.md` / `70_story_planung_…​.md`),
  FK-02 ↔ FK-71 (`02_domaenenmodell_…​.md` / `71_artefakt_envelope_…​.md`);
  dazu lange transitive Schleifen über FK-20/27/29/54. Da
  `defers_to`-Kanten **scope-qualifiziert** sind (target + scope +
  reason, z. B. FK-47-Frontmatter :12-30), sind Zyklen auf Dokumentebene
  nicht per se Fehler — azyklisch sein muss die Zuständigkeit **pro
  Scope** (kein Scope darf im Kreis delegiert werden).
- **Registry-Modellierung (verifiziert):** Die Registry
  `concept/technical-design/_meta/domain-registry.yaml` modelliert
  **nur** die BC-Mitgliedschaft (`contract_docs`/`member_docs` je
  Domäne, :1-21 Schema-Kommentar). Die `authority_over`-Scopes und die
  scope-qualifizierten `defers_to`-Kanten leben in der **Frontmatter der
  Dokumente** (META §2 benennt beide zusammen als maßgebliche
  Zuständigkeits-Quelle). Der Scope-Delegationsgraph von W1 ist daher aus
  den Frontmatter-`defers_to`-Einträgen (target + scope) zu bauen, nicht
  aus der Registry-YAML allein.
- **CI-Einbettung (verifiziert):** Die vier bestehenden Konzept-Gates
  laufen als eigene Jenkins-Stufen (`Jenkinsfile`: „Concept Frontmatter
  Lint" :244-256, „Formal Spec Compile" :258-270, „Concept Contract
  Checks" :272-285 mit `check_concept_code_contracts.py` +
  `check_architecture_conformance.py`). W1 wird an derselben Stelle
  blocking eingehängt (META §6).

## Scope

### In Scope

1. **Neues CI-Pflichtgate `scripts/ci/check_concept_reference_integrity.py`**
   (deterministisch, kein LLM, blocking; `scripts/ci/`-Muster wie die
   bestehenden Gates; wiederverwendbare Prüflogik nach
   `tools/concept_compiler/` analog `compile_formal_specs.py` →
   `drift.py`). Geprüft wird die Auflösbarkeit **aller** Querverweise
   über den gesamten Korpus unter `concept/` (domain-design,
   technical-design inkl. `_meta/` und `decisions/`, formal-spec-Prosa;
   META §2):
   - **Dokument-IDs** (FK-NN, DK-NN, META-*-IDs inkl. Decision-Records)
     gegen den Bestand;
   - **§-Anker** (z. B. „FK-71 §71.3") gegen die **realen Überschriften**
     des Zieldokuments — die P5-Fehlerklasse „FK-02 → FK-71 §67.x" stirbt
     aus;
   - **formal.*-IDs** in Prosa gegen die kompilierte Spec-Landschaft
     (Wiederverwendung des Compile-Ergebnisses von
     `tools/concept_compiler` — `declared_ids`; keine zweite
     Compile-Wahrheit);
   - **Dateipfade** in Konzeptprosa gegen das Repository.
   Jeder nicht auflösende Verweis ist ERROR (P5, §4). Abgrenzungsregeln
   (was als Verweis zählt: Code-Blöcke, Beispiel-Pfade, bewusste
   Negativ-Beispiele) werden deterministisch und dokumentiert festgelegt;
   Ausnahmen sind explizit markiert, nie heuristisch geraten.
2. **Zusatzauftrag defers_to-Semantik (META §5/W1 wörtlich):** W1 schreibt
   die Semantik fest und prüft sie: `defers_to`-Kanten sind
   scope-qualifiziert; **Scope-Delegationsketten müssen azyklisch sein**
   (Scope im Kreis delegiert → **ERROR**); **Dokumentebenen-Zyklen**
   (FK-63↔FK-70, FK-02↔FK-71, transitive Schleifen über FK-20/27/29/54)
   werden zunächst **nur reportet** (Baseline des Bestands, mit
   begründeten Einträgen — stille Baselines unzulässig, §6). Quelle des
   Graphen: Frontmatter-`defers_to` (target + scope) aller Korpus-Dokumente;
   `authority_over`-Scopes aus der Frontmatter; BC-Projektion aus
   `concept/technical-design/_meta/domain-registry.yaml`.
3. **Erweiterung, nicht Ersatz:** Die bestehende Prose-Link-Prüfung von
   `compile_formal_specs.py`/`drift.py` und die Frontmatter-Lints
   (L3/L7/L9) bleiben unverändert bestehen (META §6: „Die bestehenden
   Gates bleiben unverändert bestehen; die neuen Werkzeuge ergänzen
   sie"); W1 dedupliziert nicht durch Umbau, sondern prüft die heute
   ungedeckten Verweisklassen. Überschneidung (Doc-ID-Existenz) ist
   dokumentiert und deterministisch identisch.
4. **CI-Verdrahtung:** Aufnahme als blocking Stufe in derselben CI-Stufe
   wie die vier bestehenden Konzept-Gates (`Jenkinsfile`, analog
   :244-285); lokale Aufrufbarkeit wie die Bestands-Gates
   (`PYTHONPATH=src python scripts/ci/check_concept_reference_integrity.py`).
5. **Befund-Format:** reproduzierbar referenzierte Befunde (Dokument,
   Anker/Zeile, Verweistext, Zielobjekt), englische Befund-Codes
   (ARCH-55), Severity nach §4; Exit-Code-Vertrag wie die Bestands-Gates.

### Out of Scope (mit Owner)

- **W4 Decision-Record-Gate** (Commit-/Diff-Prüfung): **AG3-158**
  (Sequenz-Nachfolger nach §7).
- **W2 LLM-Authority-Prosa-Prüfung** (normative Aussagen vs. Authority):
  **AG3-159**.
- **W3 Scope-Konsistenz-Sweep** (Widerspruchssuche pro Scope): **AG3-160**.
- **Sanierung der Bestands-Befunde:** gefundene tote Anker/Verweise des
  Bestands werden in dieser Story nur so weit bereinigt, wie das Gate
  sonst nicht grün einführbar wäre; inhaltliche Konzept-Korrekturen mit
  normativer Wirkung laufen über den regulären Prozess (P3,
  Decision-Record — bei Bedarf eigener Konzept-Diff mit Record). Reine
  Anker-/Tippfehler-Fixes (keine Änderung normativer Sätze) sind von der
  Record-Pflicht ausgenommen (§5/W4-Abgrenzung).
- **Dokumentebenen-Zyklen auflösen:** nicht Teil von W1 (Report/Baseline
  only); eine spätere Entflechtung ist ein eigener Konzept-Strang.
- **Umbau der vier Bestands-Gates:** keiner (META §6).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `scripts/ci/check_concept_reference_integrity.py` | neu | Gate-Einstiegspunkt (blocking, Exit-Code-Vertrag wie Bestands-Gates) |
| `tools/concept_compiler/reference_integrity.py` (o. ä., im bestehenden Paket) | neu | Prüflogik: Verweis-Extraktion, §-Anker-Auflösung gegen Überschriften, formal.*-ID-Abgleich (gegen `compile_formal_specs`-Ergebnis), Pfad-Auflösung, Scope-Delegationsgraph + Azyklik-Prüfung, Dokumentebenen-Zyklen-Report |
| `concept/_meta/…` (Baseline-Datei für Dokumentebenen-Zyklen, Format-Design dieser Story) | neu | Begründete Baseline der bestehenden Dokumentebenen-Zyklen (keine stillen Einträge, §6) |
| `Jenkinsfile` | ändern | Neue blocking Stufe in derselben CI-Stufe wie die vier Konzept-Gates (analog :244-285) |
| `concept/technical-design/*.md` u. a. (nur falls für grüne Einführung nötig) | ändern (minimal) | Bereinigung nicht auflösender Bestands-Verweise ohne normative Änderung (Anker-Fixes) |
| `tests/unit/tools/concept_compiler/test_reference_integrity.py` + `tests/fixtures/concept_compiler/**` | neu | Positiv-/Negativ-Fixtures: toter Doc-Verweis, toter §-Anker, unbekannte formal.*-ID, toter Pfad, Scope-Delegationszyklus (ERROR), Dokumentebenen-Zyklus (Report/Baseline) |

## Akzeptanzkriterien

1. **Alle vier Verweisklassen geprüft, fail-closed:** Je ein
   Fixture-Negativtest beweist, dass das Gate bei (a) unbekannter
   Dokument-ID, (b) nicht existentem §-Anker eines existierenden
   Zieldokuments, (c) unbekannter formal.*-ID und (d) nicht existentem
   Dateipfad mit ERROR und Exit-Code ≠ 0 scheitert — kein Warn-Only-Modus,
   kein stilles Überspringen (P5: ERROR).
2. **§-Anker gegen reale Überschriften:** Die P5-Beispielklasse ist als
   Testfall gepinnt: ein Verweis „FK-71 §67.3" gegen ein Zieldokument mit
   Abschnitten §71.x wird als toter Anker erkannt; der korrekte Verweis
   „FK-71 §71.3" löst auf.
3. **Korpus-Abdeckung:** Das Gate prüft nachweislich den gesamten Korpus
   unter `concept/` einschließlich `concept/_meta/**` (inkl.
   `decisions/`) und der formal-spec-Prosa — belegt durch einen Testfall
   mit Befund in einem `_meta`-Dokument (heute von L7/Drift-Audit
   unabgedeckt).
4. **Scope-Delegations-Azyklik:** Ein Fixture mit im Kreis delegiertem
   Scope (A defers_to B für Scope X, B defers_to A für Scope X — auch
   transitiv) erzeugt deterministisch ERROR; die scope-qualifizierte
   Semantik ist im Gate-/Modul-Docstring festgeschrieben (W1
   „schreibt diese Semantik fest").
5. **Dokumentebenen-Zyklen Report + Baseline:** Der Bestand (mindestens
   FK-63↔FK-70, FK-02↔FK-71) erscheint im Report, bricht den Lauf aber
   nicht; jeder Baseline-Eintrag trägt eine Begründung — ein
   Baseline-Eintrag ohne Begründung lässt das Gate selbst fehlschlagen
   (fail-closed, §6: stille Baselines unzulässig); ein **neuer**, nicht
   gebaselineter Dokumentebenen-Zyklus erscheint als neuer Befund im
   Report.
6. **Keine zweite Compile-Wahrheit:** Der formal.*-ID-Abgleich konsumiert
   das Ergebnis des bestehenden `concept_compiler`-Compiles (keine eigene
   Spec-Parselogik); die vier Bestands-Gates laufen unverändert grün
   (Regressionsbeleg).
7. **Grüne Einführung auf dem realen Korpus:** Das Gate läuft auf `main`
   grün (Bestands-Anker-Befunde bereinigt bzw. — nur für die
   Dokumentebenen-Zyklen — begründet gebaselinet); die CI-Stufe ist im
   `Jenkinsfile` verdrahtet und blocking.
8. **Determinismus:** Zwei Läufe auf identischem Stand liefern
   byte-identische Befundlisten (Sortierung/IDs stabil — Voraussetzung
   für Baseline-Stabilität).
9. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
   Befund-Codes, Baseline-Feldnamen).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates + neues W1-Gate).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Sequenz-Vorläufer
  für AG3-158); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** W1 (concept/_meta/konzept-konsistenz-governance.md §5/§6/§7; kein GAP-Nenner-Bezug — eigener Strang).

## Konzept-Referenzen

- META-CONCEPT-CONSISTENCY (`concept/_meta/konzept-konsistenz-governance.md`):
  §3/P5 (Referenz-Integrität; „FK-71 §67.x"-Fehlerklasse; ERROR),
  §4 (Severity-Tabelle: toter Anker = ERROR),
  §5/W1 (Spezifikation: vier Verweisklassen; „Erweitert die bestehende
  Prose-Link-Prüfung von `compile_formal_specs.py`"; Zusatzauftrag
  defers_to: Scope-Delegationsketten azyklisch = ERROR,
  Dokumentebenen-Zyklen zunächst Report/Baseline),
  §6 (Pflichtgate in derselben CI-Stufe wie `check_concept_frontmatter`,
  `check_concept_code_contracts`, `compile_formal_specs`,
  `check_architecture_conformance`; Baselines nur mit Begründung),
  §7 (Fahrplan Punkt 1: W1 zuerst, keine Abhängigkeiten)
- Registry-Quellen: `concept/technical-design/_meta/domain-registry.yaml`
  (BC-Mitgliedschaft `contract_docs`/`member_docs`);
  Frontmatter-Verträge `authority_over`/`defers_to` (scope-qualifiziert)
  der Korpus-Dokumente — zusammen die maßgebliche Zuständigkeits-Quelle
  (META §2)
- Bestands-Prüfflächen: `scripts/ci/compile_formal_specs.py` (:41-44),
  `tools/concept_compiler/drift.py` (`audit_formal_prose_links` :34-100,
  `audit_concept_doc_classification` :103-154),
  `scripts/ci/check_concept_frontmatter.py` (L3 :262-273, L7 :475-484,
  L9-defers_to-Ausnahme :369-372, Korpus-Ladung :109-125)

## Guardrail-Referenzen

- **P1–P5/§4-Severity (META, Guardrail-Grundlage dieses Strangs):** W1
  operationalisiert P5; die Severity-Zuordnung des META-Dokuments ist
  bindend (toter Verweis = ERROR, nie Warning-Dekoration).
- **FAIL-CLOSED:** Nicht auflösende Verweise, unbegründete
  Baseline-Einträge und Scope-Delegationszyklen brechen das Gate; es gibt
  keinen Skip-Schalter.
- **SEVERITY-SEMANTIK (CLAUDE.md):** ERROR ohne aufschiebende Wirkung;
  der Dokumentebenen-Zyklen-Report ist ein sichtbarer, begründeter
  Baseline-Zustand — kein weggeklicktes Warning.
- **SINGLE SOURCE OF TRUTH:** formal.*-Abgleich gegen das eine
  Compile-Ergebnis; Zuständigkeits-Graph aus der einen
  Frontmatter-/Registry-Quelle — keine parallele Verweis-Datenbank.
- **FIX THE MODEL, NOT THE SYMPTOM:** Die Anker-Fehlerklasse wird durch
  ein Gate am Entstehungsort verhindert, nicht durch punktuelle
  Nachkorrekturen.
- **STRUKTURREGELN:** Neue Prüflogik in bestehenden Werkzeug-Paketen
  (`scripts/ci/`, `tools/concept_compiler/`) — kein neues
  Top-Level-Verzeichnis.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Nicht einschlägig — reines Repo-/CI-Werkzeug ohne
  Schema-Bezug (explizit geprüft: keine neuen Tabellen, kein
  State-Backend-Zugriff).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Verweis-/Anker-Modell,
  Auflösungsregeln und Scope-Delegationsgraph-Logik = **A**
  (technologiefreier Kern, AT-frei); Markdown-/Frontmatter-Extraktion und
  Baseline-Datei-IO = **T**; Befund-Serialisierung/Report-Mapping = **R**.
- **Bundle-Assets:** Keine betroffen (verifiziert: reines
  Repo-CI-Werkzeug; `bundles/**` wird weder gelesen noch deployt
  verändert).
- **ARCH-55:** Quellcode, Befund-Codes, Baseline-Schlüssel und
  Report-Feldnamen englisch; deutschsprachig bleibt nur Konzept-Prosa.
