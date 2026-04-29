---
concept_id: DK-09
title: Tool-Governance (CCAG)
module: ccag-domain
domain: governance-and-guards
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: tool-governance
defers_to:
  - DK-12
  - FK-42
supersedes: []
superseded_by:
tags: [tools, ccag, permissions, automation]
formal_scope: prose-only
---

# 09 — Tool-Governance (CCAG)

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 12
**Datum:** 2026-04-02 (Skill-Teil ausgegliedert nach DK-12, 2026-04-29)
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Neben Governance und Qualitätssicherung bringt AgentKit Infrastruktur
mit, die den Entwicklungsprozess selbst produktiver und zuverlässiger
macht. Zwei Komponenten sind dabei zentral: die parameterbasierte
Tool-Governance (CCAG, hier) und das spezialisierte Skill-System
([12-skills-und-skill-system.md](12-skills-und-skill-system.md)).

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

**Modus-scharfe Behandlung unbekannter Permissions.** In explizit
interaktiven Sitzungen darf CCAG weiterhin einen nativen Host-Prompt
nutzen. Im aktiven Story-Run dagegen nicht: Dort wird eine unbekannte
Freigabe sofort blockiert und als auditierbarer Permission-Fall
materialisiert. Die menschliche Entscheidung erfolgt spaeter per
offiziellem AgentKit-Pfad statt im wartenden Tool-Call.

Der Effekt für die Story-Umsetzung: Die Wahrscheinlichkeit, dass
Agents unkontrolliert an Permissions haengen, sinkt drastisch. Die
Guards ([03-governance-und-guards.md](03-governance-und-guards.md))
bleiben dabei intakt, denn CCAG ersetzt keine Governance-Regeln,
sondern ergänzt sie um eine komfortable, lernfähige Permission-Schicht.

### 9.2 Spezialisierte Skills

> Skills (User Story Creation, LLM Discussion, Semantic Review,
> Research) und das Skill-System (versionierte Bundles, Symlink-
> Bindung) sind in **DK-12 (Spezialisierte Skills und Skill-System)**
> normiert.
