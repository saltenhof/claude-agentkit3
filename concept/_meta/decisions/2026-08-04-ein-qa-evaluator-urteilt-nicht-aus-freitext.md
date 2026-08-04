---
concept_id: META-DEC-2026-08-04-EIN-QA-EVALUATOR-URTEILT-NICHT-AUS-FREITEXT
title: Concept-Decision-Record — Ein QA-Evaluator urteilt nicht aus Freitext
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, verify-system, llm-evaluator, fail-closed, AG3-212]
formal_scope: prose-only
---

# Concept-Decision-Record — Ein QA-Evaluator urteilt nicht aus Freitext

Datum: 2026-08-04. Record gemaess META-CONCEPT-CONSISTENCY P3/W4. Grundlage der
Umsetzung in AG3-212, Befund 3.

## 1. Anlass

Ein unabhaengiges Review des `verify_system` fand am 2026-08-04, dass der
QA-Evaluator nach gescheiterter JSON-Schemavalidierung aus **regex-extrahiertem
Freitext** weiterurteilt (`llm_evaluator/structured_evaluator.py:507`).

Der Befund ist nicht, dass jemand geschlampt haette: **FK-11 §320 schreibt
diesen Pfad normativ vor** — eine dreistufige Auswertung, deren „Stufe 3:
Regex-Fallback (letztes Mittel)" ausdruecklich als „Robustheits-Fallback" und
„kein Regelfall" beschrieben ist.

Damit stand eine Konzeptaussage gegen die hoeherrangigen Projektregeln:

- „NO ERROR BYPASSING — keine heimlichen Fallbacks auf schlechtere
  Datenqualitaet oder weichere Regeln"
- „FAIL-CLOSED — unklare oder unvollstaendige Zustaende werden nicht
  grosszuegig toleriert"

## 2. Entscheidung (PO, 2026-08-04)

> „Wenn der Evaluator ein JSON, also eine formal definierte Struktur, nicht
> parsen kann, dann soll er auch nicht auf Regex zurueckfallen. Dann ist die
> Struktur kaputt und dann muss man das Problem an der Wurzel packen."

> „Und wenn ein Konzept etwas anderes schreibt, dann muss es an der Stelle
> nachgezogen werden, also korrigiert werden."

### 2.1 Stufe 3 faellt

Bei gescheiterter Schemavalidierung gilt ausschliesslich der begrenzte Retry,
danach FAIL. Es gibt keinen Pfad, auf dem ein QA-Urteil aus unstrukturiertem
Text entsteht.

Die fachliche Begruendung ist die Rolle des Bausteins: Ein Evaluator ist eine
**Bewertungsfunktion**. Haelt er sein eigenes Ausgabeschema nicht ein, ist seine
Antwort unbrauchbar — nicht rettungsbeduerftig. Ein Rettungsversuch erzeugt ein
Urteil, das aussieht wie jedes andere, aber auf einer schwaecheren Grundlage
steht als das Format zusagt. Genau diese Bauart hat AK3 bereits einmal teuer
bezahlt (Pooling-Strategie, 2026-08-02): der Mechanismus arbeitete einwandfrei
und setzte den falschen Wert durch.

### 2.2 „An der Wurzel packen" ist Teil des Auftrags

Ein FAIL, das nur „Schema verletzt" meldet, verschiebt das Problem vom Fallback
in ein Protokoll, das niemand liest. Der Fehlerpfad muss die Ursache
**auffindbar** machen: welcher Evaluator, welches Modell, welche
Schemaverletzung, welcher Response-Ausschnitt. Eine kaputte Struktur ist ein
Defekt am Prompt- oder Modellvertrag und wird dort behoben.

### 2.3 Das Konzept wird korrigiert, nicht kommentiert

FK-11 §320 verliert Stufe 3. Die Beschreibung sagt danach, was gilt — nicht,
was einmal galt. Ein Hinweis „Stufe 3 wird nicht mehr verwendet" erfuellt das
**nicht**: er hinterliesse zwei Aussagen zur selben Frage und damit genau die
zweite Wahrheit, gegen die AK3 antritt.

Das ist die allgemeine Regel, hier nur angewandt: **Weicht ein Konzept vom
beschlossenen Verhalten ab, wird das Konzept an der Stelle nachgezogen.** Nicht
der Code an das veraltete Konzept, nicht eine Fussnote an beides.

## 3. Verworfene Alternativen

**Stufe 3 behalten, ihr Ergebnis nicht urteilsfaehig machen** (erzwungenes
FAIL/INCONCLUSIVE). Haette den Regex-Pfad als toten Code konserviert und die
Frage „warum steht das da" der naechsten Story vererbt.

**Stufe 3 unveraendert lassen, als dokumentierte Ausnahme.** Waere die Ausnahme
fuer genau die Bauart gewesen, gegen die AG3-191 und AG3-212 antreten — ein
Urteilsmechanismus, der bei fehlender Praezision ungenauer weiterarbeitet und
dasselbe Ergebnisformat liefert.

**Den Code still an FK-11 anpassen.** Haette die Prioritaetsordnung umgekehrt:
`CLAUDE.md` gewinnt gegen das Fachkonzept, nicht umgekehrt.

## 4. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-11 §320 (dreistufige Auswertung) | zu aendern in AG3-212 | Stufe 3 entfaellt; die Beschreibung fuehrt danach nur noch die geltenden Stufen. |
| `verify_system/llm_evaluator/structured_evaluator.py:507` | zu aendern in AG3-212 | Regex-Auswertung entfaellt; Schemafehler -> begrenzter Retry -> FAIL mit auffindbarer Ursache. |
| FK-27, FK-33, FK-69, `concept/formal-spec/` | zu pruefen in AG3-212 | Weitere Stellen, die die dreistufige Auswertung oder den Regex-Fallback beschreiben, werden mitgezogen. Halb nachgezogen ist ZERO-DEBT-Verstoss. |
| FK-11 §78.14-Bezug (LLM als Bewertungsfunktion) | geprueft, nicht geaendert | Die Entscheidung staerkt diese Aussage: eine Bewertungsfunktion mit unlesbarer Ausgabe liefert kein Urteil. |
| Tests, die den Regex-Pfad festschreiben | zu entfernen in AG3-212 | Ein Test, der den entfernten Pfad verlangt, ist Teil der Schicht (AG3-191 AC 5, hier sinngemaess). |
