# AG3-158 — Konzept-Decision-Record-Gate (W4): P3-Durchsetzung — Konzeptdiff an normativen Dokumenten erfordert Decision-Record-Referenz (Commit-Konvention + deterministischer Check)

- **Typ:** implementation
- **Größe:** S
- **depends_on:** [AG3-157] — **SEQUENZ-Kante** nach META §7-Fahrplan
  (Punkt 1: W1 zuerst — „deterministisch, billig, sofortiger Nutzen";
  Punkt 2: W4 danach). **Keine technische Abhängigkeit**: W4 braucht
  weder die W1-Prüflogik noch deren Baseline; die Kante ordnet nur die
  Umsetzungsreihenfolge des Strangs.
- **unblocks:** [AG3-159] — Sequenz-Kante nach §7 (W2 folgt als
  Punkt 3).
- **Quell-Konzept:** META-CONCEPT-CONSISTENCY
  (`concept/_meta/konzept-konsistenz-governance.md`) §5/W4
  (Prozess-Gate-Spezifikation), §3/P3 (Blast-Radius-Pflicht,
  Decision-Record + Betroffenheitsmatrix), §4 (Severity: normative
  Änderung ohne Record = ERROR, Review-Gate), §6 (W4 wirkt im Review;
  gilt manuell ab Inkrafttreten), §7 (Fahrplan Punkt 2)
- **Herkunft:** Konzept-Konsistenz-Governance (META-Dokument, aktiv);
  PO-Freigabe 2026-07-02. Kein GAP-Nenner-Bezug — eigener Strang.

## Kontext / Problem

P3 (META §3) verpflichtet jede Änderung an normativen Aussagen auf einen
Impact-Sweep mit Betroffenheitsmatrix, persistiert als
**Concept-Decision-Record** unter `concept/_meta/decisions/` (Benennung
`YYYY-MM-DD-<slug>.md`); §4 stuft eine normative Änderung ohne
Record/Matrix als **ERROR (Review-Gate)** ein. Durchgesetzt wird das
heute nur menschlich (am Bestand verifiziert 2026-07-02):

- **Kein Check existiert:** Kein Gate unter `scripts/ci/` prüft
  Konzept-Diffs auf Decision-Record-Referenzen; die vier bestehenden
  Konzept-Gates (`check_concept_frontmatter`, `compile_formal_specs`,
  `check_concept_code_contracts`, `check_architecture_conformance`)
  prüfen Struktur/Formal-Drift/Code-Contracts, nicht den
  Änderungs-**Prozess**.
- **Format-Präzedenz existiert:** Zwei Decision-Records liegen als
  Format-Vorbild vor —
  `concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`
  (concept_id `META-DEC-2026-07-02-K1-WORKTREE-TOPOLOGIE`,
  `doc_kind: decision-record`; Anlass/Entscheidung/Konsequenzen +
  Verankerungs-Matrix-Bezug) und
  `concept/_meta/decisions/2026-07-02-session-ownership-nachverankerung.md`
  (`META-DEC-2026-07-02-SESSION-OWNERSHIP`). Beide tragen Frontmatter
  nach dem Korpus-Muster (`cross_cutting: true`, `formal_scope:
  prose-only`).
- **W4 gilt bereits manuell:** META §6 setzt W4 als Review-Checkliste ab
  Inkrafttreten in Kraft — unabhängig vom Implementierungsstand des
  Checks. Diese Story liefert den deterministischen Check nach und
  verankert die Commit-Konvention.

## Scope

### In Scope

1. **Commit-Konvention (normiert + dokumentiert):** Ein Commit, dessen
   Diff normative Konzeptdokumente ändert, referenziert das zugehörige
   Decision-Record maschinenlesbar in der Commit-Message (Format-Design
   dieser Story, z. B. `Concept-Decision: 2026-07-02-<slug>`), **oder**
   der Diff enthält den `concept/_meta/decisions/`-Eintrag selbst. Die
   Konvention wird an der Stelle dokumentiert, an der die
   Gate-/Prozessregeln des Repos leben (Design-Entscheidung dieser
   Story; kein neues Top-Level-Verzeichnis).
2. **Deterministischer Check `scripts/ci/check_concept_decision_record.py`**
   (blocking; `scripts/ci/`-Muster): prüft je Commit-Range bzw. je
   Arbeitsstand — ändert der Diff normative Konzeptdokumente unter
   `concept/` und fehlt sowohl ein gleichzeitiger
   `concept/_meta/decisions/`-Eintrag als auch eine Record-Referenz in
   der Commit-Message → **Befund (ERROR)**. Referenzierte Records müssen
   existieren und dem Benennungsschema `YYYY-MM-DD-<slug>.md` folgen
   (tote Record-Referenz = ERROR; Anschlussfähigkeit an das
   W1-Verweismodell aus AG3-157, ohne technische Kopplung).
3. **Ausnahme-Abgrenzung mit prüfbarer Heuristik (festzulegen in dieser
   Story):** Reine Tippfehler-/Format-Fixes sind ausgenommen —
   Abgrenzungskriterium nach META §5/W4: **keine Änderung an normativen
   Sätzen**. Die Story legt die prüfbare Heuristik deterministisch fest
   und dokumentiert sie im Gate (Kandidaten, bewertet gegen den Korpus:
   Diff-Klassen wie Nur-Whitespace/Nur-Interpunktion/Anker-Korrekturen
   vs. Sätze mit normativen Modalmarkern — Präzedenz:
   `NORMATIVE_MODAL_RE` in `scripts/ci/check_concept_frontmatter.py:49-54`;
   plus expliziter Marker-Mechanismus für begründete Ausnahmen).
   Fail-closed-Grundsatz: Ist die Heuristik unsicher, gilt der Diff als
   normativ (Befund), nie umgekehrt.
4. **Review-Checkliste:** Der W4-Prüfschritt wird als Checklisten-Punkt
   der Konzept-Review-Praxis dokumentiert (META §6: „wirkt im Review");
   der deterministische Check ist die technische Untermauerung, ersetzt
   die Review-Pflicht aber nicht.
5. **Grüne Einführung:** Der Check läuft auf `main` grün (er bewertet
   Änderungen ab Einführung, keine retroaktive Bestands-Prüfung der
   Historie); CI-Verdrahtung in derselben Stufe wie die Konzept-Gates
   (`Jenkinsfile`, analog :244-285).

### Out of Scope (mit Owner)

- **W1 Referenz-Integrität** (Anker/IDs/Pfade): **AG3-157**.
- **W2/W3 LLM-Werkzeuge**: **AG3-159**/**AG3-160**.
- **Inhaltliche Qualität der Records** (Vollständigkeit der
  Betroffenheitsmatrix, Alternativen-Diskussion): bleibt Review-Pflicht
  (P3) — der Check erzwingt Existenz + Referenz, nicht Inhaltstiefe
  (bewusste Grenze; LLM-freie Deterministik).
- **Retroaktive Prüfung der Git-Historie:** kein Bestandteil; W4 wirkt ab
  Einführung (manuell gilt es bereits seit META-Inkrafttreten).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `scripts/ci/check_concept_decision_record.py` | neu | Deterministischer Check: Konzeptdiff-Erkennung, Normativitäts-Heuristik, decisions/-Eintrag- bzw. Commit-Referenz-Prüfung, Record-Existenz/Schema |
| `Jenkinsfile` | ändern | Blocking Stufe in der Konzept-Gate-Stufe (analog :244-285) |
| Prozess-/Gate-Dokumentation (Ablageort Design dieser Story, bestehende Struktur) | neu/ändern | Commit-Konvention + Review-Checklisten-Punkt dokumentiert |
| `tests/unit/tools/**` bzw. `tests/unit/scripts/**` (analog Bestands-Gate-Tests) + Fixtures | neu | Positiv-/Negativ-Fixtures: normativer Diff ohne Record (ERROR), mit decisions/-Eintrag (PASS), mit Commit-Referenz (PASS), tote Referenz (ERROR), Tippfehler-Fix (PASS via Heuristik), unsicherer Diff (fail-closed ERROR) |

## Akzeptanzkriterien

1. **Kernpfad fail-closed:** Ein Diff, der einen normativen Satz in einem
   Konzeptdokument ändert, ohne `concept/_meta/decisions/`-Eintrag im
   selben Diff und ohne Record-Referenz in der Commit-Message, führt
   deterministisch zu ERROR + Exit-Code ≠ 0 (Fixture-Test).
2. **Beide Erfüllungswege:** (a) gleichzeitiger decisions/-Eintrag im
   Diff und (b) maschinenlesbare Record-Referenz auf ein existierendes
   Record lassen den Check je einzeln PASSen (zwei Positiv-Fixtures);
   eine Referenz auf ein **nicht existierendes** Record oder ein Record
   außerhalb des Benennungsschemas `YYYY-MM-DD-<slug>.md` ist ERROR.
3. **Ausnahme-Heuristik prüfbar und fail-closed:** Ein reiner
   Tippfehler-/Format-Fix (keine Änderung normativer Sätze) PASSt ohne
   Record (Fixture); ein Diff, den die Heuristik nicht sicher als
   nicht-normativ klassifizieren kann, wird als normativ behandelt
   (Befund — Negativtest); die Heuristik ist im Gate dokumentiert und
   deterministisch (identischer Diff → identisches Ergebnis).
4. **Format-Vorbild-Konformanz:** Der Check akzeptiert die zwei
   existierenden Records
   (`2026-07-02-k1-worktree-topologie.md`,
   `2026-07-02-session-ownership-nachverankerung.md`) als
   schema-konform (Regressions-Pin des Benennungs-/Ablage-Schemas).
5. **Keine Fehlgriffe außerhalb des Geltungsbereichs:** Diffs, die nur
   Code/Tests/Stories ändern (kein `concept/`-Anteil), erzeugen nie einen
   Befund (Negativ-Fixture); Änderungen **nur** unter
   `concept/_meta/decisions/` selbst (Record-Nachpflege) sind kein
   normativer Konzeptdiff im Sinne des Checks.
6. **CI-Verdrahtung + grüne Einführung:** Die Stufe ist im `Jenkinsfile`
   blocking verdrahtet; der Lauf auf `main` ist grün; die
   Commit-Konvention und der Review-Checklisten-Punkt sind dokumentiert.
7. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
   Befund-Codes, Commit-Konventions-Schlüssel).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, Konzept-Gates inkl. W1-Gate + neues W4-Gate).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Sequenz-Vorläufer
  für AG3-159); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** W4 (concept/_meta/konzept-konsistenz-governance.md §5/§6/§7; kein GAP-Nenner-Bezug — eigener Strang).

## Konzept-Referenzen

- META-CONCEPT-CONSISTENCY (`concept/_meta/konzept-konsistenz-governance.md`):
  §3/P3 (Impact-Sweep, Betroffenheitsmatrix, Record-Ablage
  `concept/_meta/decisions/`, Benennung `YYYY-MM-DD-<slug>.md`;
  „die Matrix-Pflicht entfällt nie"),
  §4 (Severity: „Normative Änderung ohne Decision-Record/
  Betroffenheitsmatrix (P3) → ERROR (Review-Gate)"),
  §5/W4 (Commit-Konvention + technisch prüfbarer Check: „Konzeptdiff ohne
  gleichzeitigen decisions/-Eintrag oder Record-Referenz in der
  Commit-Message → Befund"; Ausnahme Tippfehler-/Format-Fixes —
  Abgrenzung „keine Änderung an normativen Sätzen"),
  §6 (W4 wirkt im Review; gilt ab Inkrafttreten auch manuell),
  §7 (Fahrplan Punkt 2: „Prozess + leichter Check; etabliert
  `concept/_meta/decisions/` und die Matrix-Pflicht. Keine technischen
  Abhängigkeiten.")
- Format-Vorbilder:
  `concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`,
  `concept/_meta/decisions/2026-07-02-session-ownership-nachverankerung.md`
- Heuristik-Präzedenz: `scripts/ci/check_concept_frontmatter.py`
  (`NORMATIVE_MODAL_RE` :49-54)

## Guardrail-Referenzen

- **P1–P5/§4-Severity (META, Guardrail-Grundlage dieses Strangs):** W4
  operationalisiert P3; die §4-Einstufung ERROR (Review-Gate) ist
  bindend.
- **FAIL-CLOSED:** Unsichere Normativitäts-Klassifikation gilt als
  normativ; tote Record-Referenzen sind ERROR; kein Bypass-Schalter.
- **ZERO DEBT:** Der Check verhindert genau die „Entscheidung geändert,
  Matrix später"-Schuld, die META §1 als Geburtsort der Widersprüche
  identifiziert.
- **SEVERITY-SEMANTIK (CLAUDE.md):** ERROR ohne aufschiebende Wirkung;
  die Ausnahme ist eine dokumentierte, prüfbare Abgrenzung — kein
  Ermessens-Bypass.
- **STRUKTURREGELN:** Check in `scripts/ci/`; keine neuen
  Top-Level-Verzeichnisse; Records ausschließlich unter
  `concept/_meta/decisions/` (SINGLE SOURCE OF TRUTH der
  Entscheidungs-Historie).

## Querschnitts-Auflagen

- **K5 Postgres-only:** Nicht einschlägig — reines Repo-/CI-Werkzeug ohne
  Schema-Bezug (explizit geprüft).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Normativitäts-/
  Geltungsbereichs-Regeln und Konventions-Modell = **A** (AT-frei);
  Git-Diff-/Commit-Message-Erhebung = **T**; Befund-Serialisierung = **R**.
- **Bundle-Assets:** Keine betroffen (verifiziert: reines
  Repo-CI-Werkzeug ohne Bundle-Bezug).
- **ARCH-55:** Befund-Codes, Commit-Konventions-Schlüssel und
  Heuristik-Bezeichner englisch.
