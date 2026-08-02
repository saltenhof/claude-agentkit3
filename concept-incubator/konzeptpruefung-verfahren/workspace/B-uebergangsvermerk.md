---
title: Uebergangsvermerk — Abloesung der W2/W3-Pre-Merge-Pflicht
status: draft
doc_kind: workspace-proposal
date: 2026-08-02
authority_over: []
note: >
  Enthaelt den exakten Wortlaut zum Eintragen. Der Eintrag selbst ist
  NICHT erfolgt — ein zweiter Agent arbeitet parallel in den
  betroffenen normativen Dateien.
---

# Uebergangsvermerk — Abloesung der W2/W3-Pre-Merge-Pflicht

## 1. Zielstellen und Reihenfolge

| # | Zielstelle | Art | Voraussetzung |
|---|---|---|---|
| 1 | `AGENTS.md`, Abschnitt "Pflicht-Gates vor 'fertig'" | **Ersetzt** die beiden Bulletpoints zu W2 und W3 (heute Zeilen 73–87) | keine — `AGENTS.md` ist lokale Agenteninstruktion, kein normatives Konzeptdokument. **Sofort eintragbar.** |
| 2 | `concept/_meta/konzept-konsistenz-governance.md` §6 "Betriebsmodell" | **Ergaenzt** einen datierten Absatz nach dem W2/W3-Spiegelstrich | Normative Aenderung -> braucht ein Concept-Decision-Record mit Betroffenheitsmatrix (P3/W4). **Erst zusammen mit dem Konzeptdelta.** |

**Empfehlung zur Reihenfolge:** Nur Zielstelle 1 sofort eintragen. Der
Governance-Absatz ist normativ und wuerde ohne Record genau das Gate
verletzen, das durch diesen Umbau ausdruecklich **nicht** ausgesetzt
wird. Bis dahin gilt: die Werkzeugbeschreibung in §5 (W2/W3) bleibt
inhaltlich richtig — ausgesetzt ist die **Betriebspflicht** in §6, und
die steht bis zum Record in `AGENTS.md`.

---

## 2. Wortlaut fuer `AGENTS.md` (Zielstelle 1)

### 2.1 Was entfernt wird

Die beiden bestehenden Spiegelstriche, beginnend mit
"Vor der Landung normativer Konzeptaenderungen W2 gegen die geaenderte
Range ausfuehren" und "Vor der Landung normativer Konzeptaenderungen W3
fuer jeden betroffenen `authority_over`-Scope ausfuehren".

### 2.2 Was an ihre Stelle tritt (exakter Wortlaut)

```markdown
- **Die W2/W3-Pre-Merge-Pflicht ist seit 2026-08-02 ausgesetzt (PO-Entscheidung).**
  Die Konzeptpruefung wird umgestellt: weg von LLM-Hub-Gates, an die
  Konzeptanteile geschickt werden in der Hoffnung auf saubere
  Modellantworten, hin zu nativen KI-Agenten ueber die Harness-Bridge,
  denen von aussen nur Leitplanken, Ziele und Nachweispflichten
  vorgegeben werden und die ihre Strategie selbst waehlen. Bis das neue
  Verfahren normiert ist, gilt:
  - `check_concept_authority_prose.py` (W2) und
    `check_concept_scope_consistency.py` (W3) sind **kein
    Abnahmekriterium** mehr. Ein nicht gefahrener, abgebrochener oder
    unvollstaendiger Sweep blockiert die Landung nicht.
  - **Ein Lauf bleibt erlaubt, und ein inhaltlicher Befund bleibt
    verbindlich.** Wer W2/W3 faehrt und einen Befund erhaelt, behebt ihn
    an der Wurzel oder traegt ihn begruendet in die Baseline ein.
    Ausgesetzt ist die Pflicht zum Lauf, nicht der Umgang mit dem
    Ergebnis.
  - **Ein nicht durchgelaufener Sweep wird niemals als "gruen"
    berichtet.** "Konzept-Gates gruen" bezeichnet ausschliesslich die
    statischen Gates. Wer beides zusammenzieht, wiederholt die
    Ueberbehauptung aus AG3-179 Runde 1.
  - **Der Grund ist Erfuellbarkeit, nicht Bequemlichkeit.** Eine Regel,
    die im Repo steht und nicht erfuellbar ist, erzieht dazu, sie still
    zu uebergehen oder "Gates gruen" zu behaupten — beides ist bereits
    passiert. Belegt in
    `stories/AG3-179-run-mutex-intent-liveness/report.md`: ein
    reproduzierbarer `HUB_UNREACHABLE` an einer Partition von 35666
    Zeichen im qwen-Adapter, und ein fehlender Retry in
    `collect_scope_findings`, der einen kompletten Sweep an einem
    einzigen nicht-woertlichen Modellzitat beendet.
- **Unveraendert verbindlich und blockierend bleiben alle
  deterministischen Konzept-Gates:** `check_concept_frontmatter.py`,
  `compile_formal_specs.py`, `check_concept_reference_integrity.py` (W1),
  `check_concept_code_contracts.py`, `check_architecture_conformance.py`
  sowie `check_concept_decision_record.py` (W4) samt Record- und
  Betroffenheitsmatrix-Pflicht. Die Aussetzung betrifft **ausschliesslich**
  die beiden LLM-gestuetzten Sweeps. Es gibt weiterhin keinen gate-freien
  Pfad in die normative Welt.
- **Was bis zur Normierung des neuen Verfahrens an ihre Stelle tritt:**
  Eine normative Konzeptaenderung wird vor der Landung einem
  **unabhaengigen Agenten** vorgelegt — anderer Principal, andere
  Session als der Verfasser — mit drei benannten Pruefachsen:
  (1) zeigen die Aenderungen auf die richtigen normativen Zielstellen und
  auf Dokumente, die den Scope besitzen duerfen, (2) ist die Aenderung in
  sich und gegen den beruehrten Bestand widerspruchsfrei, (3) trifft sie
  den Problemraum und ist sie ohne eigene Annahmen umsetzbar. Befunde
  werden an der Wurzel behoben; "konnte nicht geprueft werden" ist ein
  zulaessiges Ergebnis und niemals PASS. Das ist die bereits geltende
  Codex-Review-Grundregel aus `CLAUDE.md`, angewandt auf
  Konzeptaenderungen — sie braucht keine neue Mechanik.
```

---

## 3. Wortlaut fuer `concept/_meta/konzept-konsistenz-governance.md` §6 (Zielstelle 2)

Einzufuegen als eigener Absatz **nach** dem bestehenden
"W2/W3 laufen nightly …"-Spiegelstrich. Der bestehende Spiegelstrich
wird **nicht geloescht**, sondern durch den Nachsatz ueberlagert — die
Werkzeugbeschreibung bleibt gueltig, ihre Betriebspflicht nicht.

```markdown
- **Aussetzung der W2/W3-Vor-Landungspflicht (2026-08-02, PO).** Die
  vorstehend beschriebene Pflicht, W2 und W3 vor der Landung normativer
  Konzeptaenderungen auszufuehren, ist ausgesetzt. Grund ist nicht ein
  ausbleibender Nutzen — W3 hat zuletzt einen echten und behobenen
  Widerspruch geliefert — sondern die Sproedigkeit des Hub-gestuetzten
  Betriebs: ein reproduzierbarer Transportabbruch oberhalb einer
  Partitionsgroesse und ein fehlender Retry gegen nicht-woertliche
  Modellzitate machen einen vollstaendigen Sweep unerreichbar, ohne dass
  ein Befund vorliegt. Eine unerfuellbare Pflicht erzieht zur stillen
  Umgehung; das ist der teurere Fehler.

  Ausgesetzt ist die **Betriebspflicht**, nicht die Aufgabe. Die von W2
  und W3 adressierten Fragen — behauptet ein Dokument etwas ueber einen
  Scope, den es nicht besitzt, und widersprechen sich Aussagen desselben
  Scopes — bleiben Pruefgegenstand und wandern in das agentische
  Verfahren (DK-16/FK-78), das sie **aenderungsgetrieben** stellt statt
  korpusgetrieben. Bis dessen Normierung tragen sie die drei
  Pruefachsen der unabhaengigen Vorlage nach `AGENTS.md`.

  Unveraendert bleiben P1–P5 dieses Dokuments, W1 und W4 als
  Pflichtgates sowie die Regel, dass ein unvollstaendiger Sweep niemals
  als PASS gilt. Ein bewusst in Kauf genommener Rest ist benannt: das
  neue Verfahren folgt der Aenderung und sieht ruhenden Bestand nicht
  wieder an. Ob dafuer ein Bestandsdetektor erhalten bleibt, ist eine
  offene PO-Entscheidung.
```

**Pflichtbeigabe zu Zielstelle 2:** ein Concept-Decision-Record
`concept/_meta/decisions/2026-08-02-konzeptpruefung-agentisches-verfahren.md`
mit Anlass, Alternativen und Betroffenheitsmatrix. Betroffen sind
mindestens: `konzept-konsistenz-governance.md` (§5 W2/W3, §6, §7),
`AGENTS.md`, FK-78 §78.14 und §78.17 Nr. 3 (der Folge-Story
"Hub-Batch-Komfort fuer W2/W3" faellt die Grundlage weg), sowie
`concept/_meta/authority-prose-baseline.yaml` (Weiterfuehrung oder
Einfrierung).
