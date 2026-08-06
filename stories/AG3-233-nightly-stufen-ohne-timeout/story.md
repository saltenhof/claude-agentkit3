# AG3-233 — „Non-blocking" gilt für das Ergebnis, nicht für die Dauer

- **Typ:** bugfix
- **Groesse:** S
- **Abhaengigkeiten:** keine
- **Herkunft:** Jenkins #1249 gegen `56c170e5`, 2026-08-06

## Befund

Build #1249 stand nach **30 Minuten** immer noch in der Stufe „Concept Authority
Prose Nightly (non-blocking)". Bisherige Volldurchlaeufe lagen bei 18 Minuten;
dieselbe Stufe brauchte in #1246 fuenf.

Der LLM-Hub war dabei **erreichbar** — Listener auf 9600, Dienst antwortet. Die
Stufe haengt also nicht an einem toten Dienst, sondern an einem Aufruf ohne
Abbruchbedingung.

```
Jenkinsfile:5      timeout(time: 300, unit: 'MINUTES')   global, fuenf Stunden
Jenkinsfile:329ff  Stufe W2: set +e … exit 0, KEIN eigenes timeout()
Jenkinsfile:350ff  Stufe W3: dito
scripts/ci/check_concept_authority_prose.py:  kein einziges `timeout`
```

## Warum das mehr ist als eine fehlende Zeile

Beide Stufen behandeln **sorgfaeltig** den Fall „das Skript liefert einen
Fehlercode": `set +e`, Exit einfangen, Meldung, `exit 0`. Der Fall „das Skript
kehrt nie zurueck" ist nirgends behandelt.

Und es sind ausgerechnet die **einzigen beiden Stufen, die einen externen
LLM-Dienst aufrufen** — also die einzigen, bei denen genau das der realistische
Ausfall ist. Der sorgfaeltig abgesicherte Fall ist der unwahrscheinlichere.

**Eine Stufe, die das Urteil nicht blockieren soll, aber die Pipeline fuenf
Stunden festhalten kann, ist nicht non-blocking.** Der Name beschreibt eine
Eigenschaft, die nur zur Haelfte umgesetzt ist — dieselbe Klasse wie die
Fehlermeldung, die etwas anderes behauptet als sie prueft (AG3-232), und die
Regel, die ein nicht existierendes Modul verbietet (AG3-229).

## Der Zweitschaden

Ein Build, der in einer nicht-blockierenden Stufe haengt, blockiert alles
dahinter: SonarQube, den Quality Gate und jede Aussage darueber, ob der
Kandidat landbar ist. Am 2026-08-06 hat dieselbe Mechanik in umgekehrter Form
schon einmal zugeschlagen — ein abbrechendes Gate verdeckte die Befunde der
Gates dahinter (#1248). Hier verdeckt ein haengendes Gate sie.

## Scope

### In Scope

- **Beide Nightly-Stufen bekommen eine Obergrenze**, nach der sie abbrechen und
  das Ergebnis als „nicht ermittelt" melden — nicht als „bestanden".
- **Das Skript selbst bekommt eine Abbruchbedingung** fuer den Aufruf des
  externen Dienstes. Eine Grenze allein auf Pipeline-Ebene hilft niemandem, der
  das Skript lokal ausfuehrt — und lokale Ausfuehrung ist in jedem Auftrag
  dieses Projekts verlangt.
- **Die Meldung unterscheidet drei Ausgaenge**: Befunde gefunden / keine
  Befunde / **nicht ermittelt**. Der dritte fehlt heute, und ohne ihn sieht ein
  abgebrochener Lauf aus wie ein sauberer.
- Dasselbe fuer `check_concept_scope_consistency.py` (W3).

### Out of Scope

- Die Frage, ob diese Stufen ueberhaupt bleiben. Der PO hat am 2026-08-05
  festgestellt, dass der LLM-Hub instabil ist und **nicht mehr die
  Zielarchitektur traegt** — die Bewertung wandert auf die Harness Bridge. Diese
  Story macht den Ist-Zustand belastbar; sie entscheidet nicht ueber seine
  Zukunft.
- Der globale 300-Minuten-Timeout. Er ist die letzte Reissleine und bleibt.

## Akzeptanzkriterien

1. **Keine Stufe kann die Pipeline laenger als ihre erklaerte Obergrenze
   aufhalten.** Nachgewiesen an einem Lauf gegen einen Dienst, der nicht
   antwortet — nicht an einem, der schnell antwortet.
2. **Ein Abbruch ist als Abbruch erkennbar**, in der Konsolenausgabe und im
   Ergebnis. Ein nicht ermitteltes Urteil darf unter keinen Umstaenden wie ein
   bestandenes aussehen (`CLAUDE.md` §FAIL-CLOSED).
3. **Die Stufe bleibt nicht-blockierend im Ergebnis**, so wie heute: Befunde
   fuehren nicht zum roten Build. Diese Eigenschaft darf die Aenderung nicht
   verlieren.
4. **Das Skript ist auch lokal abbruchfaehig**, ohne Pipeline-Umgebung.
5. **Die Obergrenze ist begruendet**, nicht geraten — abgeleitet aus den
   gemessenen Laufzeiten (fuenf Minuten in #1246, ueber dreissig in #1249).
6. `ruff` clean bis auf den AG3-218-`C901`; `mypy --strict`; alle
   deterministischen Gates gruen.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg.
- AC 1 ist **nicht** durch einen schnell antwortenden Dienst belegbar.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FAIL-CLOSED — AC 2; ein nicht ermitteltes Urteil ist kein
  bestandenes
- `CLAUDE.md` §SEVERITY-SEMANTIK — „nicht ermittelt" ist ein eigener Ausgang
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — die Grenze gehoert dorthin, wo
  der Aufruf stattfindet, nicht nur in die Pipeline
