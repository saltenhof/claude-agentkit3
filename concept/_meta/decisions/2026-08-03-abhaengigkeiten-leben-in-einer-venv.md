---
concept_id: META-DEC-2026-08-03-ABHAENGIGKEITEN-LEBEN-IN-EINER-VENV
title: Concept-Decision-Record — AK3 und seine Abhaengigkeiten leben in einer venv
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, installation, dependencies, FK-10, FK-51]
formal_scope: prose-only
---

# Concept-Decision-Record — AK3 und seine Abhaengigkeiten leben in einer venv

Datum: 2026-08-03. Entscheider: Product Owner.

## 1. Anlass

In einer Fremdinstallation (`intima`) sind an einem Tag **164 Hook-Fehler**
aufgelaufen, 90 davon mit derselben Ursache: `ModuleNotFoundError: No module
named 'tomlkit'`. Das Paket steht seit jeher als **Pflicht**-Abhaengigkeit in
`pyproject.toml`. Es fehlte trotzdem.

Die Wirkung war total und unsichtbar zugleich: saemtliche Guards —
`commit_hook`, `skill_usage_check`, `health_monitor`, `budget`,
`prompt_integrity` — sind vor der ersten Zeile Fachlogik am Import gestorben.
Wer sich auf sie verliess, hatte keine. Gemerkt hat es niemand, weil ein Hook,
der seinen eigenen Fehlschlag verschluckt, von einem funktionierenden Hook nicht
zu unterscheiden ist.

## 2. Der eigentliche Befund: AK3 hatte keine Politik

AK3 waehlt heute **weder** den globalen **noch** den virtuellen Weg. Es waehlt
gar nicht — es **erbt**:

- Der Installer fuehrt **kein** `pip install` aus. `lifecycle/update.py` haelt
  das ausdruecklich fest: „driver decides and instructs, it does not execute
  `pip install`". Die Uebereinstimmung von Deklaration und Installation hat
  damit **keinen Eigentuemer**.
- Was AK3 stattdessen tut: es merkt sich, wo es zufaellig lag.
  `resolve_story_knowledge_base_command()` und der Git-Hook-Dispatch schreiben
  `sys.executable` fest — den Interpreter, der gerade den Installer ausfuehrte.

Das ist die dritte, unzulaessige Variante: nicht bewusst global, nicht sauber
gekapselt, sondern „was der Aufrufer dabeihatte". Genau daraus entstand der
vorgefundene Mischzustand — Paket auf Nutzerebene, Abhaengigkeit auf
Systemebene, funktionierend nur, weil beide zufaellig im Suchpfad stehen.

## 3. Entscheidung

**3.1 AK3 und seine Abhaengigkeiten leben in einer virtuellen Umgebung.**
Begruendung des PO: AK3 darf das System, auf dem es installiert wird, nicht
verschmutzen.

**3.2 Der AK3-spezifische Grund kommt hinzu und ist zwingend.** AK3 und AK2
teilen den Paketnamen `agentkit`. Eine globale Installation von AK3
**ueberschreibt AK2** und zerstoert dessen Hooks. Der Blueprint-Gedanke — ein
global geteilter Baustein — traegt hier deshalb gerade nicht: AK3 ist kein
gemeinsamer Unterbau, sondern ein Werkzeug neben einem gleichnamigen Vorgaenger.

**3.3 Eine gewaehlte Politik muss durchgesetzt werden, nicht gehofft.** Ein
Preflight prueft **deklarierte gegen tatsaechlich importierbare** Abhaengigkeiten
und bricht fail-closed ab. Ohne ihn vertagt sich der Fehler bis zum ersten
Hook-Aufruf und landet dort als 22-stufiger Importfehler in einem Transcript,
das niemand liest.

**3.4 Was nicht in der venv liegt, wird nicht stillschweigend akzeptiert.**
Faellt die Pruefung, ist das ein Installationsfehler mit Namen und Kommando —
kein Warnhinweis, den ein spaeterer Lauf verschluckt.

## 4. Konsequenzen

- Der Installer bekommt einen Eigentuemer fuer die Abhaengigkeitslage; heute hat
  ihn niemand.
- Jede neue Zeile in `pyproject.toml` ist ohne 3.3 ein stiller Totalausfall
  aller Guards. Das ist keine Prognose, sondern der belegte Ablauf vom 2026-08-03.
- Die Umsetzung ist in **AG3-206** geschnitten.
- Nicht entschieden und ausdruecklich offen: ob AK3 die venv selbst anlegt oder
  eine vorhandene verlangt. Beides erfuellt 3.1; die Wahl gehoert in AG3-206 und
  ist dort dem PO vorzulegen.
