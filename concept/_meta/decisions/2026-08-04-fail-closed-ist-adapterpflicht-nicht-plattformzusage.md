---
concept_id: META-DEC-2026-08-04-FAIL-CLOSED-IST-ADAPTERPFLICHT-NICHT-PLATTFORMZUSAGE
title: Concept-Decision-Record — Fail-closed ist Adapterpflicht, keine Plattformzusage
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, hooks, guards, harness-integration, fail-closed, AG3-206]
formal_scope: prose-only
---

# Concept-Decision-Record — Fail-closed ist Adapterpflicht, keine Plattformzusage

Datum: 2026-08-04. Record gemaess META-CONCEPT-CONSISTENCY P3/W4. Loest den
Widerspruch auf, den META-DEC-2026-08-04-ABHAENGIGKEITSVOLLSTAENDIGKEIT-UND-HOOK-FEHLERSICHTBARKEIT
(AG3-206) benannt, aber mandatsbedingt offen gelassen hat. PO-Freigabe zur
Aenderung von FK-30 und FK-76 erteilt am 2026-08-04.

## 1. Anlass

FK-30 sagte an zwei Stellen zu, was die Plattform nicht leistet:

- Glossar `hook-enforcement`: „Exit 0 erlaubt, Exit 2 blockiert, **jeder Crash
  ist fail-closed blockiert**."
- §30.2.4, Tabelle: „Andere (1, Crash) | **Blockiert (fail-closed)** | Agent
  sieht generischen Fehler", dazu der erlaeuternde Absatz „Ein crashender Hook
  (exit 1, Timeout, Exception) blockiert das Tool."

Der Vorfall vom 2026-08-03 beweist das Gegenteil. In einer Fremdinstallation
starben saemtliche Hooks am Top-Level-Import einer fehlenden
Pflicht-Abhaengigkeit. Ergebnis: 164 Hook-Crashes an einem Tag, **kein
einziger blockierend, keiner sichtbar.** Der Harness persistierte sie als
`hook_non_blocking_error`-Attachments und fuhr fort. Die Guards galten die
ganze Zeit als aktiv.

Der Widerspruch ist nicht kosmetisch. Solange die Norm die Blockade der
Plattform zuschreibt, hat kein Adapter einen Grund, sie selbst herzustellen —
und genau dieser fehlende Grund ist die Ursache des Vorfalls. Eine Zusage, die
nur im Dokument existiert, erzeugt Code, der sich auf sie verlaesst.

## 2. Entscheidung

### 2.1 Die Politik bleibt, ihr Traeger wechselt

**Fail-closed bleibt normativ** — daran aendert dieser Record nichts. Was faellt,
ist die Behauptung, die Plattform stelle es her. Fail-closed ist ab sofort eine
**Pflicht des AK3-Hook-Adapters**: jeder Fehlerpfad endet in Exit 2,
einschliesslich der Pfade vor der ersten Zeile Fachlogik.

Praktische Folge, die der Vorfall erzwingt: **Fachimporte gehoeren hinter die
Fehlergrenze, nicht auf Modulebene.** Ein Adapter, der beim Import stirbt, gibt
Exit 1 zurueck und laesst den Tool-Call durch. Umgesetzt in AG3-206
(`claude_code.py`, `codex/cli.py`).

### 2.2 Die Transporttatsache gehoert FK-76, die Pflicht FK-30

Die Owner-Trennung aus FK-76 §76.2 wird eingehalten, nicht umgangen:

- **FK-30** traegt weiter die harness-neutrale Politik: *dass* fail-closed gilt
  und *dass* der Adapter sie herstellen muss. §30.2.4 wurde korrigiert und um
  den normativen Auftrag ergaenzt.
- **FK-76 §76.4a** (neu) traegt die harness-spezifische Tatsache: wie Claude
  Code einen Exit ausser 0/2 behandelt (nicht blockierend, still persistiert,
  fuer den Agenten unsichtbar) und warum daraus die Adapterpflicht folgt.

Das ist keine Policy im Adapter im Sinne von §76.2: der Adapter deutet keinen
Exit-Code in `allow`/`deny` um. Er stellt sicher, dass die von FK-30 geforderte
Wirkung ueber diesen Transport ueberhaupt transportabel ist.

### 2.3 Ein Bypass in einer Hook-Registrierung ist ein Fehler

`|| true`, `2>/dev/null` und aequivalente Konstrukte in einer
Hook-Registrierung sind keine Absicherung, sondern verwandeln einen ohnehin
nicht blockierenden Ausfall zusaetzlich in einen unauffindbaren. Normativ
festgehalten in FK-30 §30.2.4.

**Vollzogen, nicht nur normiert.** Die vier externen Hooks in der
Benutzer-`settings.json`, die AG3-206 als ERROR ausgewiesen hatte, sind am
2026-08-04 entfernt worden. Der Befund bei der Pruefung war schaerfer als
erwartet: **keines der vier referenzierten Skripte existierte** — weder in AK3
noch in AK2 noch in irgendeinem Projekt unter `T:\codebase`. Sie scheiterten
seit unbekannter Zeit bei jedem `Read`/`Grep`/`Glob`/`Bash`-Aufruf in jedem
Projekt und waren allein durch `|| true` unsichtbar. Das `|| true` zu entfernen
haette daher nicht den Guard scharf gestellt, sondern jeden Tool-Aufruf
blockiert; die richtige Reparatur war das Entfernen der toten Registrierung.
Sicherung unter `~/.claude/settings.json.bak-2026-08-04-ag3-206`.

## 3. Verworfene Alternativen

**FK-30 unveraendert lassen und den Adapter „zusaetzlich" absichern.** Haette
zwei Wahrheiten ueber dieselbe Frage stehen lassen: eine Norm, die die
Plattform zusagt, und einen Code, der es nicht glaubt. Die naechste
Implementierung waehlt dann die Norm.

**Die Tatsache in FK-30 statt FK-76 aufschreiben.** Verstoss gegen die
Trennregel §76.2 — harness-spezifische Transportsemantik in einem
harness-neutralen Dokument. Beim naechsten unterstuetzten Harness waere FK-30
zu aendern gewesen, obwohl sich an der Politik nichts aendert.

**Fail-closed aufgeben, weil die Plattform es nicht traegt.** Waere die
Umkehrung der Beweislast: aus „der Mechanismus fehlt" folgt nicht „das Ziel war
falsch". Der Vorfall zeigt genau, was der Verzicht kostet.

## 4. Verhaeltnis zum Bestand

Der AG3-206-Record bleibt gueltig und unveraendert in seiner Substanz; seine
Betroffenheitsmatrix-Zeile zum FK-30/FK-76-Widerspruch wird auf diesen Record
verwiesen. AG3-206 hat den Widerspruch korrekt benannt statt ihn zu bestreiten
— genau dafuer war der Eintrag da.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-30 Glossar `hook-enforcement` | geaendert | Die Zusage „jeder Crash ist fail-closed blockiert" ist durch die Adapterpflicht ersetzt, mit Verweis auf FK-76 §76.4a. |
| FK-30 §30.2.4 Hook-Output | geaendert | Tabellenzeile und Erlaeuterung geben jetzt die gemessene Wirkung wieder; der normative Auftrag an den Adapter steht darunter, inklusive Bypass-Verbot. |
| FK-76 §76.4a | neu | Harness-spezifische Transportsemantik nicht-normaler Exit-Codes samt Konsequenz fuer den Adapter-Vertrag. |
| FK-76 §76.2 Trennregel | geprueft, nicht geaendert | Die Aufteilung folgt ihr: Politik bei FK-30, Transport bei FK-76. Keine Policy-Umdeutung im Adapter. |
| FK-55 §55.1a (Stufe-3-Abgrenzung) | geprueft, nicht geaendert | Die Nicht-Umgehbarkeitsstufen sind von dieser Aenderung unberuehrt. |
| FK-50 (Install-Orchestrierung, Hook-Registrierung) | geprueft, nicht geaendert | CP 9 registriert weiterhin unveraendert; das Bypass-Verbot betrifft den Inhalt der Registrierung, nicht ihre Orchestrierung. |
| `harness_adapters/claude_code.py`, `codex/cli.py` | geprueft, nicht geaendert | Erfuellen die Pflicht bereits seit AG3-206 (Exit 2 ohne `pydantic`, Fachimporte hinter der Fehlergrenze). Dieser Record normiert, was dort schon gilt. |
| AG3-206-Record, Matrix-Zeile FK-30/FK-76 | geaendert | Von „Widerspruch offen" auf „aufgeloest, siehe diesen Record". |
| Externe Hooks in `~/.claude/settings.json` | entfernt, ausserhalb des Repos | Vier tote Registrierungen ohne existierende Skripte; Sicherung abgelegt. Kein Repo-Artefakt betroffen. |
