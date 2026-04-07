---
concept_id: DK-09
title: Umsetzungsautomatisierung und Werkzeuge
module: tools-and-skills
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: tools-and-skills
defers_to: []
supersedes: []
superseded_by:
tags: [tools, skills, ccag, permissions, automation]
---

# 09 — Umsetzungsautomatisierung und Werkzeuge

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 12
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Neben Governance und Qualitätssicherung bringt AgentKit Infrastruktur
mit, die den Entwicklungsprozess selbst produktiver und zuverlässiger
macht. Zwei Komponenten sind dabei zentral: die parameterbasierte
Tool-Governance (CCAG) und das spezialisierte Skill-System.

### 9.1 Parameterbasierte Tool-Governance (CCAG)

Claude Code bietet standardmäßig ein einfaches Permission-System: Der
Mensch wird gefragt, ob ein Tool ausgeführt werden darf, und seine
Antwort gilt nur für die aktuelle Session. Bei hochautomatisierten
Abläufen mit vielen Sub-Agents führt das zu zwei Problemen: Erstens
scheitern Agents an Permissions, die der Mensch in einer früheren
Session bereits erteilt hat, weil die Freigabe nicht gespeichert wurde.
Zweitens kann das native System nur nach Tool-Name filtern, nicht nach
Parametern. Man kann nicht "git push auf Story-Branches erlauben, aber
auf Main blockieren", wenn beides derselbe Tool-Name ist.

CCAG löst beide Probleme:

**Sessionübergreifende Persistenz.** Jede erteilte Freigabe wird als
Regel in einer YAML-Datei gespeichert und steht in allen zukünftigen
Sessions sofort zur Verfügung. Über Wochen und Monate wächst ein
projektspezifischer Regelsatz, der die häufigsten Operationen
automatisch freigibt und den Menschen nur noch bei genuinen Neuheiten
fragt.

**Parameterbasierte Regeln.** Regeln matchen nicht nur auf den
Tool-Namen, sondern auf beliebige Parameter: Dateipfade, Befehle,
URLs, Flags. Damit lassen sich feingranulare Policies abbilden, etwa
"Schreibzugriff nur innerhalb des Projektverzeichnisses" oder "git push
erlaubt, aber nicht mit --force und nicht auf Main".

**LLM-gestützte Regelgenerierung.** Wenn der Mensch einen neuen
Tool-Aufruf freigibt, kann er ein LLM aufrufen, das den spezifischen
Aufruf zu einer verallgemeinerten Regel generalisiert. Statt die
exakte Befehlszeile zu speichern, erzeugt das LLM eine Regex-Regel,
die ähnliche zukünftige Aufrufe ebenfalls abdeckt. Der Mensch sieht
eine Vorschau und kann anpassen, bevor die Regel gespeichert wird.

**Rollenspezifische Scopes.** Regeln unterscheiden zwischen
Hauptagent und Sub-Agents. Sub-Agents erhalten engere Rechte als der
Hauptagent. Ein Sub-Agent darf beispielsweise nicht außerhalb des
Projektverzeichnisses schreiben, während der Hauptagent das darf.
Diese Unterscheidung wird über eine Hierarchie in der Regeldatenbank
aufgelöst.

**Sofortige Propagation.** Wenn ein Sub-Agent in einer tiefen
Verschachtelung auf ein Permission-Problem stößt, sieht der Mensch das
sofort in seiner Konsole, nicht erst wenn der Agent nach Minuten der
Arbeit scheitert. Die Freigabe propagiert sofort an alle laufenden
Agents.

Der Effekt für die Story-Umsetzung: Die Wahrscheinlichkeit, dass
Agents an Permissions scheitern, sinkt drastisch. Die Guards ([03-governance-und-guards.md](03-governance-und-guards.md)) bleiben dabei intakt, denn CCAG ersetzt keine Governance-Regeln,
sondern ergänzt sie um eine komfortable, lernfähige Permission-Schicht.

### 9.2 Spezialisierte Skills

AgentKit bringt für verschiedene Aufgabenstellungen spezialisierte
Skills mit. Ein Skill ist eine vordefinierte Prompt-Anleitung, die
einen Agenten methodisch durch eine komplexe Aufgabe führt. Skills
standardisieren nicht nur den Ablauf, sondern heben die Qualität des
Ergebnisses, indem sie bewährte Methodik einbetten, die ein Agent ohne
Anleitung nicht konsistent anwenden würde.

**Beispiele für mitgelieferte Skills:**

| Skill | Aufgabe | Was er standardisiert |
|-------|---------|---------------------|
| User Story Creation | Neue Stories erstellen | VektorDB-Abgleich, Anforderungsstruktur, Akzeptanzkriterien, Größenschätzung |
| LLM Discussion | Multi-LLM-Sparring zu einer Fragestellung | Rollenverteilung, Rundenstruktur, unabhängige Positionsbildung, Konvergenzprüfung |
| Semantic Review | LLM-basierte Code-Bewertung | Strukturiertes Scoring-Schema, Fokus auf die 12 definierten Checks |
| Research | Strukturierte Internetrecherche | Systematische Suche, Quellenvielfalt, Bewertungskriterien, Ergebnisablage |

Skills werden bei der Installation ([08-installation-und-bootstrap.md](08-installation-und-bootstrap.md)) automatisch ins
Zielprojekt deployt. Neue Skills können hinzugefügt werden, ohne den
Kern von AgentKit zu ändern. Die Qualität der Story-Umsetzung hängt
wesentlich davon ab, dass Agents nicht bei jeder Aufgabe ihre eigene
Methodik erfinden, sondern auf erprobte Abläufe zurückgreifen.
