# AG3-063 — Remediation r1 (Antwort auf review-r1.md)

Scope dieser Remediation: ausschliesslich `story.md` (umgeschrieben). `status.yaml`
wurde geprueft und **nicht** geaendert (Begruendung unten, Finding 4.WARNING). Keine
Produktionscode-, Test- oder Konzeptdateien angefasst. AG3-057-Template-Struktur
(Abschnitte 1–6, Quell-Konzepte, In/Out-of-Scope-mit-Owner, AC, DoD, Guardrails,
Sub-Agent-Hinweise) beibehalten.

---

## Must-Fix (ERROR)

### MF-1 / 3.WARNING — Ist-Zustand Ebene 2 faktisch falsch
**Finding:** „Ebene 1 und Ebene 2 fehlen komplett" (alt `story.md:22`) widerspricht der
vorhandenen Ebene-2-Exploration-Pruefung (`exploration/review/doc_fidelity.py`); der
Gap-Befund sagt enger: fehlen „als gemeinsamer ConformanceService"
(`gap-fk-26-35.md:289-293`).
**Resolution:** §1 umgeschrieben. Ebene 2 ist jetzt als **vorhanden, aber nicht im
gemeinsamen `ConformanceService` konsolidiert** beschrieben, mit echten Ankern:
`DocFidelityChecker.check()` (`exploration/review/doc_fidelity.py:59-119`), gewired
`composition_root.py:217-247`, Stage-1-Stopp `review.py:136-147`. Nur **Ebene 1** ist als
„fehlt vollstaendig" markiert.

### MF-1 / 3.WARNING — Ist-Zustand Ebene 4 zu stark („gebaut und produktiv")
**Finding:** Ebene 4 als „gebaut und produktiv" ist falsch; der produktive Port ist ein
verpflichtender Warning-Stub ohne Callable (`runtime_ports.py:197-218`; Composition Root
`:2165-2175`).
**Resolution:** §1 + §2.1(3) + §2.2 umgeschrieben. Ebene 4 ist jetzt als
**nicht-blockierender Closure-Seam ohne produktiven Evaluator** beschrieben (Protocol
`finalization.py:53-69`; Warning-Port `runtime_ports.py:197-218`, gewired
`composition_root.py:2165-2175`). Der produktive `feedback_fidelity`-Evaluator ist
explizit **AG3-067** (FK-38 §38.3.1) zugeordnet; AG3-063 liefert nur die
`check_fidelity(level=feedback)`-Fassade und laesst den Warning-Seam unveraendert.

### MF-2 — Scope/AC: delegieren/konsolidieren statt parallel ersetzen (Kontext-Sinnhaftigkeit, zweite Wahrheit)
**Finding (4.ERROR + 2.AC-ERROR):** Alter Scope „Ebenen 1 + 2 neu implementieren"
(`story.md:35`) wuerde eine zweite Design-Fidelity-Wahrheit erzeugen, da
`ExplorationReview` Stage 1 bereits Doc-Fidelity ausfuehrt und bei FAIL stoppt
(`review.py:136-147`). AC pruefen nicht, dass der vorhandene Checker an
`ConformanceService` delegiert/abgeloest wird.
**Resolution:** §2.1(2) trennt jetzt klar: **Ebene 1 neu**, **Ebene 2 konsolidieren** —
der vorhandene `DocFidelityChecker.check()` (`doc_fidelity.py:84-119`) wird auf
`check_fidelity(level=design)` umgestellt (Delegation/Abloesung), kein zweiter Einstieg.
Neues **AC3** verlangt explizit: kein paralleler Design-Fidelity-Einstieg; Assertion auf
genau einen Auswertungspfad; kein zweiter Reviewer/Feedback-Schreibpfad.

### MF-3 — Telemetrie/formale Conformance-Events mit Tests fehlen
**Finding (1.ERROR):** FK-32 §32.3 Schritt 5 + §32.10 verlangen Telemetrie; formale Spec
verlangt `assessment.started`/`level.evaluated`/`assessment.completed`
(`formal-spec/conformance/events.md:24-52`); FK-91 nennt die API-Event-Namen
(`91_api_event_katalog.md:252-254`). Alter AC-Satz deckt das nicht ab.
**Resolution:** Neuer **In-Scope 6** (Telemetrie + Event-Trias) und neues **AC7**
(Contract-Test mit exakten Payload-Keys gegen die formale Spec). Mapping-Entscheidung
explizit gemacht: `llm_call` (`source_component: conformance_service`, `role:
doc_fidelity`) **plus** die drei `conformance_*`-API-Events (FK-91), projiziert aus der
formalen Trias. Tier-3-Sonderfall geklaert: `level.evaluated`/`completed` mit
`status: FAIL`, **kein** `llm_call`. Quell-Konzepte-Block um die Event-Refs ergaenzt.

### MF-4 — Manifest-Index-Owner: kuratiert, kein Runtime-Schreibpfad
**Finding (1.ERROR):** Alt verlangte „persistiert/liest" und „liest/schreibt
manifest-index.json" (`story.md:37`, `:52`), widerspricht FK-32 §32.4.4 (Index nicht
automatisch generiert, kuratiert, Pflege durch Menschen, `32_...:260-271`).
**Resolution:** §2.1(4) auf **read/validate/resolve-Consumer** umgeschnitten; **kein
Runtime-Schreibpfad waehrend des Assessments**. Initiale Index-Erzeugung als
Installer/Admin in §2.2 mit eigenem Owner ausgelagert. **AC4** umgeschrieben auf
„liest und validiert" + Assertion „`check_fidelity` schreibt den Index nicht".

### MF-5 — AC um Jenkins/Sonar Remote-Gates erweitern
**Finding (2.AC-ERROR):** DoD/Pflichtbefehle unvollstaendig; `AGENTS.md:31-53` verlangt
Jenkins + Sonar inkl. `scripts/ci/check_remote_gates.ps1` und verbietet roten
Gate-Zustand.
**Resolution:** **AC9** um Remote-Gates erweitert: Jenkins gruen, Sonar-Gate gruen via
`check_remote_gates.ps1`, strikte Metriken `violations=0`/`critical_violations=0`/
`security_hotspots=0`; „Repo nie mit rotem Gate hinterlassen". §4 DoD entsprechend
ergaenzt. Vier Konzept-Gates konkret benannt (`check_concept_frontmatter.py`,
`compile_formal_specs.py`).

### MF-6 — Anchor-/Grep-Aussagen praezisieren (3.NIT)
**Finding:** `doc_fidelity/__init__.py` ist nicht „1 Zeile", sondern 0 Bytes/0 Zeilen;
`FidelityResult`-Grep ist repo-weit nicht „0 Treffer" (`DocFidelityResult` existiert,
`doc_fidelity.py:41`).
**Resolution:** §1 sagt jetzt **„leere Datei (0 Bytes / 0 Zeilen)"** (verifiziert:
`wc -c` = 0). Grep-Scope auf `src/agentkit/` + den gemeinsamen `FidelityResult`-Typ
praezisiert; expliziter Hinweis, dass `DocFidelityResult` (`doc_fidelity.py:41`) ein
anderer, vorhandener Typ ist. Neuer Sub-Agent-Hinweis „Grep-Praezision".

---

## WARNING

### 4.WARNING — `status.yaml` `unblocks: []` begruenden
**Finding:** `unblocks: []` fraglich, weil AG3-063 in der Verify/Closure-Welle liegt und
AG3-064/067 fachlich angrenzen (`_STORY_INDEX.md:54-58`).
**Resolution (status.yaml NICHT geaendert — bewusst):** Im Index deklariert **keine**
Story `depends_on: AG3-063` — AG3-064 `depends_on: AG3-021, AG3-042, AG3-052`
(`_STORY_INDEX.md:55`), AG3-067 `depends_on: AG3-043, AG3-053, AG3-061`
(`_STORY_INDEX.md:58`). Ein `unblocks`-Eintrag waere damit eine erfundene Kante
gegen den realen Index-Stand (Verstoss gegen „kein zweiter Wahrheits-Owner"). Statt ein
Feld faktisch falsch zu machen, ist die fachliche Angrenzung jetzt **in `story.md`
explizit begruendet**: §2.2 ordnet die feedback-Fidelity-Produktivlogik AG3-067 und die
Stage-Registrierung/Integrity-Gate-Pruefung AG3-064 zu, sodass die Beziehung sichtbar
ist, ohne eine nicht-deklarierte `unblocks`-Kante zu behaupten. `status.yaml` bleibt
korrekt (`status: draft`, `phase: review_pending`, `depends_on: AG3-043, AG3-061` —
deckt sich mit `_STORY_INDEX.md:54`).

---

## Cross-Story-Voraussetzungen (genuin)

- **AG3-067 (FK-37/FK-38)** — Produktiver Ebene-4-`feedback_fidelity`-Evaluator +
  post-merge Mandatory-Target-Rueckkopplung. AG3-063 liefert **nur** die
  `check_fidelity(level=feedback)`-Fassade und laesst den Warning-Seam
  (`runtime_ports.py:197-218`) unveraendert. Solange AG3-067 nicht gemerged ist, bleibt
  Ebene 4 nicht-blockierend (Warning) — das ist kein offener AG3-063-Rest, sondern der
  korrekte Cut. Kein formaler `depends_on` (AG3-067 haengt nicht an AG3-063 und
  umgekehrt; rein fachliche Angrenzung).
- **AG3-064 (FK-33) / Integrity-Gate** — Stage-Registrierung der Conformance-Stages
  (Trust/Producer/Override) und die Closure-Pruefung, dass je relevanter Ebene ein
  `doc_fidelity`-`llm_call` in der Telemetrie vorliegt (FK-32 §32.10 / FK-35).
  AG3-063 **emittiert** die Events; das **Pruefen** bleibt AG3-064/Integrity-Gate.
- **AG3-061 (FK-28)** — EvidenceAssembler/BundleManifest (bereits als `depends_on`
  deklariert). Conformance-Service konsumiert ggf. das Manifest, baut es nicht.
- **Installer/Admin-Indexer** — initiale Erzeugung des kuratierten
  `_guardrails/manifest-index.json` (FK-32 §32.4.4). AG3-063 ist read/validate-Consumer;
  ein realer initialer Index muss vom Installer/Admin bereitgestellt werden, sonst
  greift fail-closed (kein stilles „keine Referenzen").

---

## Verifikation der Anker (Stichprobe, gelesen)

- `verify_system/doc_fidelity/__init__.py` — `wc -c` = 0, `wc -l` = 0 → „leere Datei".
- `exploration/review/doc_fidelity.py:41` `DocFidelityResult`, `:59-119`
  `DocFidelityChecker.check()`; `review.py:136-147` Stage-1-REJECTED.
- `composition_root.py:217-247` `build_exploration_review`; `:2165-2175`
  `_build_doc_fidelity_feedback_port`.
- `closure/runtime_ports.py:197-218` `ProductiveDocFidelityFeedbackPort` (Warning, kein
  Callable); `closure/post_merge_finalization/finalization.py:53-69`
  `DocFidelityFeedbackPort`-Protocol.
- `core_types/qa_artifact_names.py:36/76/89` `DOC_FIDELITY_FILE/STAGE/PRODUCER`.
- `concept/technical-design/32_...:123-135` (Schritt 5 Telemetrie), `:260-271` (Index
  kuratiert), `:518-534` (llm_call-Event).
- `formal-spec/conformance/events.md:24-52` (Event-Trias + Pflicht-Payloads);
  `91_api_event_katalog.md:252-254` (FK-91 conformance_*-Namen).
- `AGENTS.md:31-53` (Remote-Gates Jenkins/Sonar + `check_remote_gates.ps1`).
- `_STORY_INDEX.md:54-58` (AG3-063/064/067 depends_on).
