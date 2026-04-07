---
concept_id: DK-06
title: Agent Requirements Engine (ARE)
module: are-integration
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: domain-are-integration
defers_to: []
supersedes: []
superseded_by:
tags: [are, requirements, scope-mapping, evidence, completeness]
---

# 06 — Agent Requirements Engine (ARE)

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 9
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

## 6. Anforderungsvollständigkeit durch Agent Requirements Engine

AgentKit integriert optional die Agent Requirements Engine (ARE) als
externe Säule. ARE verwaltet Anforderungen als typisierte Objekte
(Regulatorik-Klauseln, Geschäftsregeln, Report-Mappings, System- und
Qualitätsanforderungen) in einer zentralen Datenbank. Jede Story erhält
bei Erstellung automatisch alle wiederkehrenden Pflichtanforderungen
ihres Scope, ohne manuelles DoD-Abhaken.

ARE erzwingt Vollständigkeit, nicht Qualität: Jede als `must_cover`
verlinkte Anforderung muss explizite Evidence haben, bevor eine Story
geschlossen werden kann. Ein Agent kann Evidence fälschen, aber er kann
keine Anforderung ignorieren. Das Gate blockiert, solange auch nur eine
Pflichtanforderung ohne Evidence ist. Diese Vollständigkeitsgarantie
wirkt auf den implementierenden Worker ebenso wie auf den QA-Agenten.

Ob die eingereichte Evidenz den Anspruch der Anforderung tatsächlich
erfüllt, bleibt Aufgabe der Verify-Phase ([04-qualitaetssicherung.md](04-qualitaetssicherung.md)) und des
menschlichen Reviewers.

### 6.1 Andock-Punkte in AgentKit

ARE ist eine eigenständige Komponente außerhalb von AgentKit. Die
Integration erfolgt über vier konkrete Andock-Punkte im AgentKit-
Ablauf. Alle vier sind nur aktiv, wenn ARE in der Pipeline-Konfiguration
aktiviert ist. Ohne ARE-Konfiguration lösen dieselben Stellen im
Ablauf keinen Fehler aus, sie entfallen einfach.

| Andock-Punkt | Wo im Ablauf | Was passiert | Wer ruft ARE auf |
|--------------|--------------|-------------|------------------|
| Anforderungen verlinken | Story-Erstellung ([02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md) Abschnitt 2.1) | Wiederkehrende Pflichtanforderungen werden automatisch mit der Story verknüpft. Story-spezifische Anforderungen werden explizit zugeordnet. | Pipeline-Skript im Erstellungsprozess |
| Anforderungskontext laden | Setup-Phase (vor Worker-Start) | Das Pipeline-Skript der Setup-Phase ruft ARE ab, bereitet den Bundle auf und legt ihn als Teil des strukturierten Story-Kontexts ab. Der Worker findet die Anforderungsliste beim Start vor — er muss sie nicht selbst holen. Der Orchestrator-Agent erhält kein Bundle, sondern nur ein Statussignal, ob der Schritt erfolgreich war. | Deterministisches Pipeline-Skript (Setup-Phase) |
| Evidence einreichen | Worker-Implementierung und Verify-Phase | Der Worker reicht während der Implementierung Evidence pro Anforderung ein (z.B. Testreport, Commit-Referenz). Der QA-Agent kann ebenfalls Evidence einreichen. | Worker-Agent und QA-Prozess |
| ARE-Gate prüfen | Verify-Phase, Schicht 1 (deterministische Checks) | Deterministisches Skript fragt ARE ab: Haben alle must_cover-Anforderungen dieser Story Evidence? Ergebnis: PASS oder FAIL mit Liste der unbelegten Anforderungen. | Deterministisches Pipeline-Skript |

### 6.2 Scope-Zuordnung

Damit ARE die richtigen Anforderungen für eine Story finden kann,
muss eine Brücke zwischen der AgentKit-Welt (Repositories, Module)
und der ARE-Welt (Scopes) existieren. Diese Brücke wird bei der
Installation konfiguriert und bei der Story-Erstellung automatisch
ausgewertet.

#### Zwei Zuordnungstabellen

AgentKit pflegt zwei getrennte Zuordnungstabellen in der
Pipeline-Konfiguration:

| Tabelle | Was zugeordnet wird | Wann relevant |
|---------|---------------------|---------------|
| Repo → Scope | Jedes Code-Repository wird genau einem ARE-Scope zugeordnet (z.B. Backend-Repo → Scope "backend") | Bei Stories mit identifizierten Participating Repos |
| Modul → Scope | Jeder Wert des GitHub-Project-Feldes "Modul" (eine fachliche Klassifikation) wird genau einem ARE-Scope zugeordnet | Fallback, wenn keine Participating Repos identifiziert wurden |

Root-Repos und reine Dokumentations-Repos werden von der
Repo-Scope-Zuordnung ausgenommen — nur Code-Repositories brauchen
eine Zuordnung.

#### Konfiguration bei Installation

Die Zuordnung wird während der AgentKit-Installation (oder beim
Update) festgelegt. Der Installer erkennt automatisch alle
Code-Repositories und alle Modul-Werte aus dem GitHub Project und
prüft, ob bereits eine Scope-Zuordnung existiert.

Bei fehlenden Zuordnungen fragt der Installer den Menschen:
Interaktiv über eine nummerierte Auswahl aus den in ARE verfügbaren
Scopes. Bei agentischer Installation (kein Terminal) gibt der
Installer den Status "ausstehende Zuordnung" zurück, und der
orchestrierende Agent muss die Zuordnung explizit auflösen.

Bereits zugeordnete Einträge werden bei Updates nicht erneut
abgefragt. Nur neue Repos oder neue Modul-Werte lösen eine
Zuordnungsanfrage aus.

#### Scope-Ableitung bei Story-Erstellung

Bei der Story-Erstellung wird der ARE-Scope automatisch aus der
Story abgeleitet, nicht manuell angegeben:

| Priorität | Quelle | Wann greift sie |
|-----------|--------|-----------------|
| 1 (primär) | Participating Repos | Wenn die Story betroffene Dateipfade hat. Jedes Repo wird über die Repo→Scope-Tabelle aufgelöst. |
| 2 (Fallback) | Modul-Feld | Wenn keine Participating Repos identifiziert wurden (z.B. reine Konzeptarbeit). Der Modul-Wert wird über die Modul→Scope-Tabelle aufgelöst. |

Die resultierenden Scope-Schlüssel steuern die ARE-Anforderungssuche:
Nur Anforderungen, deren Scope mit mindestens einem abgeleiteten
Scope-Schlüssel übereinstimmt, werden als Kandidaten für die
Story-Verknüpfung vorgeschlagen.

#### Verantwortlichkeiten

| Wer | Was |
|-----|-----|
| Mensch | Entscheidet bei der Installation, welcher ARE-Scope zu welchem Repo und Modul gehört |
| Mensch | Prüft bei der Story-Erstellung die automatisch zugeordneten Anforderungen |
| Automation | Leitet zur Laufzeit die Scopes aus den Participating Repos oder dem Modul ab |
| Automation | Sucht die passenden Anforderungen, evaluiert Applicability-Rules, verknüpft automatisch |

### 6.3 Kontextvorbereitung als Pipeline-Verantwortung

Das Laden und Aufbereiten des ARE-Bundles ist deterministische
Infrastrukturarbeit — kein Bestandteil der Orchestrierung. Diese
Unterscheidung hat direkte Konsequenzen für die Rollenverteilung.

**Was AgentKit übernimmt (deterministisch, vor Agent-Start):**
Das Pipeline-Skript der Setup-Phase ruft ARE ab, holt die
must_cover-Anforderungen für die Story und legt das aufbereitete
Bundle als Teil des strukturierten Story-Kontexts ab. Dieser Schritt
ist maschinengesteuert, vorhersagbar und unabhängig vom
Orchestrator-Agenten.

**Was der Orchestrator-Agent tut:**
Der Orchestrator-Agent erhält ein Statussignal, ob der ARE-Bundle-Abruf
erfolgreich war. Er startet daraufhin den Worker. Den Bundle-Inhalt
kennt er nicht und braucht er nicht — er trifft keine inhaltlichen
Entscheidungen auf Basis von Anforderungsdetails. Er ruft ARE nicht
selbst auf, bereitet keinen Bundle auf und modifiziert keine
Kontextdateien.

**Was der Worker tut:**
Der Worker findet die Anforderungsliste beim Start in seinem Kontext
vor. Er muss ARE für das initiale Laden nicht selbst ansprechen —
das wurde bereits erledigt. Er nutzt ARE ausschließlich zum Einreichen
von Evidence während seiner Implementierung.

**Snapshot-Bindung:**
Der initiale Requirements-Bundle gilt als autoritativer Snapshot für
den gesamten Run. Worker und QA-Agent konsumieren diesen Kontext,
sie erzeugen oder verändern ihn nicht. Der Orchestrator-Agent erhält
den Bundle-Inhalt nicht — er bekommt nur das Statussignal der
Setup-Phase. Eine Neubewertung oder
Aktualisierung des Bundles ist nur über eine explizit definierte,
deterministische Reassessment-Phase zulässig — nie durch agentische
Improvisation während eines laufenden Runs.

**Fehlender Bundle ist ein Startblocker:**
Ist der Bundle bei Worker-Start nicht vorhanden, ungültig oder nicht
lesbar, handelt es sich um einen Precondition Failure. Der Worker-Start
wird verweigert. AgentKit markiert den Zustand entsprechend und löst
einen definierten Recovery-Pfad aus. Der Orchestrator-Agent beschafft
den Bundle nicht eigenständig nach — er leitet den Fehlzustand weiter.

**Abgrenzung zu Scope-Drift:**
Scope-Drift beginnt dort, wo der Orchestrator-Agent fehlende
Infrastrukturleistungen durch eigene Kontextmaterialisierung,
Kontextmutation oder ad hoc Hilfsskripte kompensiert. Das ist eine
Ausprägung des in [00-uebersicht.md](00-uebersicht.md), Abschnitt 3 beschriebenen Scope-Drift durch
Hilfsbereitschaft: Das Einzelverhalten erscheint rational (der Bundle
muss irgendwie zum Worker), aber die Verantwortungsgrenze zwischen
Pipeline-Infrastruktur und Orchestrierung verschwimmt. Die relevante
Grenze ist nicht, ob der Orchestrator ARE aufruft, sondern ob er den
autoritativen Ausführungskontext selbst materialisiert oder mutiert.

### 6.4 Fallback ohne ARE

Ohne ARE gibt es keinen maschinellen Vollständigkeits-Check auf
Anforderungsebene. Die Definition of Done wird dann über statische
Checklisten im Story-Template abgebildet, deren Einhaltung der
Semantic Review ([04-qualitaetssicherung.md](04-qualitaetssicherung.md)) und der Mensch bewerten. Das ist weniger
robust, aber funktional: AgentKit läuft vollständig ohne ARE, verliert
aber die maschinenprüfbare Anforderungsvollständigkeit.
