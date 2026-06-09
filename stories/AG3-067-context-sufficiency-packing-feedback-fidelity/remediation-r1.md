# AG3-067 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` + `status.yaml` only. No production code,
tests, or concept files touched. Every code anchor below was re-verified against
the real tree at remediation time and corrected to `file:line`. The AG3-057
template structure (sections 1–6) is preserved; the AC list grew from 8 to 10
because two AC-anchors were missing (caller-side 6-field paths, real Layer-2
integration point).

## Must-Fix ERRORs

### MF1 — `feedback_fidelity`-Ist-Zustand korrigiert (review §Klarheit ERROR, §Must-Fix 1)
**Finding:** „Grep → 0 Treffer" war falsch/vermischt. Closure-Port, Aufruf und
Stub existieren bereits — nur der echte Evaluator/Prompt fehlt.
**Resolution:** §1-Bullet umgeschrieben: `DocFidelityFeedbackPort.evaluate_feedback_fidelity`
(`finalization.py:63-67`) wird als Schritt 6 vor Postflight aufgerufen (`:147-150`),
produktiver nicht-blockierender Stub-Port `runtime_ports.py:208-218`. Fehlend ist
explizit nur der reale post-merge-Evaluator + Prompt `doc-fidelity-feedback.md`
(expected_check `feedback_fidelity`) hinter dem Port. (Resolved in-story.)

### MF2 — Mandatory-Target-Rueckkopplung gegen reales `Finding`/`RemediationFeedback` (review §AC-Schaerfe ERROR, §Must-Fix 2)
**Finding:** Story behauptete `Finding.source == "adversarial_mandatory_target"`
und forderte Findings im FK-38-Pseudocode-Shape. Das reale `Finding`
(`protocols.py:206-213`) hat KEIN `source`/`check_id`/`status`, sondern
`layer`/`check`/`severity`/`message`/`trust_class`/`file_path`/`line_number`/`suggestion`.
**Resolution:** §1-Bullet + In-Scope 5 + AC8 + Hinweise spezifizieren das Mapping:
`layer="adversarial"`, `check=<target_id>`, `severity=Severity.BLOCKING`,
`trust_class` der Adversarial-Quelle, `message` mit dem unerfuellten Target;
die FAIL-Findings landen als `blocking_findings` in `RemediationFeedback`
(`remediation/feedback.py:25`). Zwei Tests asserten gegen die realen Felder, nicht
gegen `source`/`check_id`/`status`. (Resolved in-story.)

### MF3 — FK-37 6-Feld-Bezugswege vollstaendig, inkl. caller-seitig `diff_summary`/`evidence_manifest` (review §Konzept-Vollst. WARNING, §Must-Fix 3)
**Finding:** Story forderte nur vier Builder-Loader; FK-37 §37.2.2 (REF-035)
verlangt fuer ALLE sechs Felder einen kanonischen Bezugsweg, inkl. caller-seitiger
Einspeisung von `diff_summary` und `evidence_manifest` aus `context.json`
(`concept/technical-design/37_…:369-385`).
**Resolution:** Quell-Konzept-Header, In-Scope 1 und neues **AC2** ergaenzen die
zwei caller-seitigen Bezugswege explizit (uebernommen aus `context.json`,
eingespeist, bewertet; fehlender Bezug → `missing` trotz Daten auf Disk) mit
Negativtest je Feld. (Resolved in-story.)

### MF4 — Realer Layer-2-Einbaupunkt als AC/Scope-Anker (review §Kontext-Sinnhaftigkeit ERROR, §Must-Fix 4)
**Finding:** Story fokussierte `bundle.py`, nannte aber den realen Pre-Step-Einbaupunkt
nicht: `build_review_bundle` wird in `run_layer2_llm` aufgerufen
(`layer2_integration.py:87-93`), erreicht ueber `run_layer2_llm_failclosed`
(`system.py:1653-1660`).
**Resolution:** Konfliktcheck-Absatz, neues **AC6** und Hinweise verdrahten
Sufficiency + Packing **vor** `runner.run(...)` im realen Layer-2-Pfad; AC6 testet
gegen den realen Aufrufpfad, nicht nur isoliert in `bundle.py`. (Resolved in-story.)

### MF5 — `ConformanceService`-Signatur + AG3-063-Abhaengigkeit geklaert (review §Konzept-Vollst. ERROR, §Must-Fix 5)
**Finding:** `check_fidelity(feedback)` war eine Pseudo-Fassade. FK-32 §32.3 definiert
`check_fidelity(level, evaluator, context)` mit `level="feedback"` und
`expected_checks=[f"{level}_fidelity"]` (`32_…:123-128`/`:160-169`). Im realen Source
gibt es noch keinen `ConformanceService`.
**Resolution:** Alle Vorkommen auf `check_fidelity(level="feedback", evaluator=…, context=…)`
korrigiert (Konfliktcheck, In-Scope 4, In/Out-Abgrenzung, Hinweise). AG3-063 ist im
`_STORY_INDEX.md` NICHT als `depends_on` von AG3-067 gefuehrt (autoritativ:
AG3-043/AG3-053/AG3-061) — daher explizit gegen den vorhandenen
`DocFidelityFeedbackPort`-Adapter abstrahiert, nicht gegen die AG3-063-Klasse als
harte Voraussetzung. Kein zweiter Doc-Fidelity-Pfad. (Resolved in-story; siehe
Cross-Story-Hinweis 1.)

## WARNINGs

### W1 — „vierfeldrig"/„vier Loader" praezisiert (review §Klarheit WARNING)
`ReviewBundle` hat acht Felder, nicht vier. §1 trennt jetzt: `Layer2ReviewInput`
(FK-27 §27.5.2) ist das vierfeldrige Textinput-Modell; `ReviewBundle`
(`bundle.py:44-69`, acht Felder) traegt weitere operative Felder, aber nicht
`arch_references`/`evidence_manifest`. (Resolved in-story.)

### W2 — AC „sechs Felder gesamt" praezisiert (review §AC-Schaerfe WARNING, vormals AC4)
Umformuliert zu „die sechs **semantischen `ContextBundle`-Kontextfelder** zusaetzlich
zu den bestehenden operativen `ReviewBundle`-Metadaten" (jetzt AC5 + In-Scope 3).
(Resolved in-story.)

### W3 — AC7 deterministisch gemacht (review §AC-Schaerfe WARNING, vormals AC7)
„Assertion/Review" ersetzt durch konkretes AC9: kein neues produktives
`*bundle*builder*`/`*pack*`-Duplikat neben `build_review_bundle`; der reale
Layer-2-Pfad (AC6) nutzt genau den erweiterten Builder (Modul-/Symbol-Assertion +
Aufrufpfad-Assertion). (Resolved in-story.)

### W4 — `status.yaml` `unblocks` (review §Kontext-Sinnhaftigkeit WARNING)
AG3-101 haengt von AG3-067 ab (`_STORY_INDEX.md:142`). `unblocks: []` war falsch.
**Resolution:** `unblocks: [AG3-101]` gesetzt. (Resolved in status.yaml.)

## Korrigierte/verifizierte Code-Anker
Alle vom Review genannten Anker gegen den realen Tree nachgeprueft und uebernommen:
`bundle.py:44-69` (ReviewBundle), `bundle.py:36-39`/`:109` (Trunkierung),
`bundle.py:130` (`build_review_bundle`), `protocols.py:206-213` (reales `Finding`),
`finalization.py:63-67` (Port-Methode) + `:147-150` (Aufruf Schritt 6),
`runtime_ports.py:208-218` (Stub-Port), `layer2_integration.py:87-93`
(`run_layer2_llm` → `build_review_bundle`), `system.py:1653-1660`
(`run_layer2_llm_failclosed`), `remediation/feedback.py:25` (`RemediationFeedback`).
Konzept-Anker: FK-37 §37.2.2/§37.2.3/§37.2.5 (`37_…:358-473`), FK-32 §32.3
(`32_…:123-128`/`:160-169`), FK-38 §38.1.4 (`38_…:235-255`).

## status.yaml
`unblocks: [AG3-101]` ergaenzt (siehe W4). `depends_on` unveraendert
(`AG3-043`/`AG3-053`/`AG3-061`) — deckt sich mit dem autoritativen `_STORY_INDEX.md:58`.
AG3-063 wurde bewusst NICHT als `depends_on` aufgenommen (siehe MF5 / Cross-Story-Hinweis 1):
der Index fuehrt es nicht, und Ebene 4 ist gegen den vorhandenen Port abstrahiert.
`phase: review_pending` bleibt korrekt fuer den laufenden Review-Zyklus.

## Genuine cross-story Voraussetzungen / Folge-Einheiten
1. **AG3-063 (Welle 1) — `ConformanceService.check_fidelity`-Fassade (FK-32).** Owner
   der gemeinsamen Doc-Fidelity-Fassade. NICHT als hartes `depends_on` von AG3-067
   gefuehrt (`_STORY_INDEX.md:54`/`:58`). AG3-067 bleibt lauffaehig, weil Ebene 4
   gegen den bereits existierenden `DocFidelityFeedbackPort` abstrahiert; landet
   AG3-063 spaeter, wird der `ConformanceService` hinter denselben Port verdrahtet.
   Kein Scope-Transfer; keine zweite Doc-Fidelity-Logik.
2. **AG3-079 (Welle 1) — Produzent `mandatory_target_results`/`adversarial.json` (FK-48).**
   AG3-067 konsumiert nur (`_STORY_INDEX.md:80`). Gegen das Artefakt-Schema
   `adversarial.json` abstrahieren; AG3-067 bleibt ohne AG3-079 lauffaehig (kein
   Adversarial-Artefakt → keine Mandatory-Target-Findings).
3. **AG3-064 (Welle 1) — `context_sufficiency`-Stage + fail-open Policy-Warning-Pfad (FK-33).**
   Hier wird der Builder/Producer geliefert und der Warning gespeist; bei fehlender
   Stage gegen das Artefakt-Schema testen (AC3). Schnitt: Stage dort, Builder hier.
4. **AG3-061 (depends_on) — `BundleManifest` (FK-28).** Quelle des `evidence_manifest`-Felds;
   gegen dessen Typ programmieren. Bereits korrekt als `depends_on` gefuehrt.
5. **AG3-101 (Welle 10, doc-only) — FK-37/FK-38-Naming-Prosa (`ContextBundle`/`VerifyContext`).**
   Die FK-Prosa-vs-Code-Drift (`ContextBundle` Prosa ↔ reales `ReviewBundle`; FK-38
   `Finding`-Pseudocode `source`/`check_id`/`status` ↔ reales `Finding`) gehoert in
   den doc-only Konzept-Nachzug AG3-101 (haengt von AG3-067 ab), NICHT in den
   AG3-067-Code-Cut. AG3-067 bindet typisiert an das reale Modell und meldet den
   Drift, mehr nicht. (status.yaml `unblocks: AG3-101` gepflegt.)
