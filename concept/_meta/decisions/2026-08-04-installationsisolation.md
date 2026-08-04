---
concept_id: META-DEC-2026-08-04-INSTALLATIONSISOLATION
title: Concept-Decision-Record — Dauerhafte Installations- und Interpreterisolation
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, deployment, installer, interpreter, FK-10, FK-22, FK-30, FK-76]
formal_scope: prose-only
---

# Concept-Decision-Record — Dauerhafte Installations- und Interpreterisolation

Datum: 2026-08-04. Entscheider: Product Owner.

## 1. Anlass

AK2 und AK3 teilen gegenwaertig den Importnamen `agentkit`. Eine globale
editierbare AK3-Installation legte `_editable_impl_agentkit.pth` im
Benutzer-`site-packages` ab und machte dadurch AK3 fuer beliebige
PATH-Interpreter sichtbar. Damit konnte AK3 AK2-Hooks ueberschreiben; zugleich
blieb unbemerkt, wenn Git-, MCP- oder Harness-Einsprungpunkte einen beliebigen
`python` aus `PATH` statt des AK3-Interpreters starteten.

Der Paketnamenskonflikt wird durch AG3-208/AG3-209 getrennt geloest. Die
Installationsisolation bleibt dennoch dauerhaft erforderlich, weil AK3 eigene
Drittbibliotheken auf einer fremden Entwicklermaschine mitbringt und deren
System- oder Benutzerumgebung nicht kontaminieren darf.

## 2. Entscheidung

**2.1 Eine dedizierte Umgebung ist die einzige zulaessige AK3-Runtime auf der
Entwicklermaschine.** Der Installer erzeugt eine fehlende virtuelle Umgebung
selbst und installiert AK3 samt allen deklarierten Abhaengigkeiten dorthin. Eine
brauchbare vorhandene Umgebung wird wiederverwendet. Eine unbrauchbare wird mit
benanntem Grund abgelehnt und weder repariert noch ersetzt.

**2.2 Globale Source-Installationen schlagen fail-closed fehl; installierte
Wheels sind global nicht benutzbar.** Eine regulaere oder editierbare
Source-Installation darf AK3, Paketmetadaten, `.pth`-Dateien oder
Abhaengigkeiten nicht in System- oder Benutzer-`site-packages` hinterlassen. Bei
einem bereits gebauten Wheel besitzt pip keinen Paket-Hook vor dem Schreiben.
Deshalb verweigert die paketweite Importgrenze nach der technischen Installation
jede AK3-Nutzung ausserhalb einer isolierten Umgebung. Derselbe Schutz greift
vor der ersten Fachlogik aller deklarierten Console-Entry-Points.

**2.3 Es gibt genau einen Interpreter-Owner.** CLI, Installer, Git-Hooks,
MCP-Server und Harness-Hooks beziehen den absoluten AK3-Interpreter aus
derselben Aufloesung. Diese prueft eine aktive virtuelle Umgebung,
`include-system-site-packages = false` und eine existente Interpreterdatei.
Direkte Einsprungpunkt-Nutzung von `sys.executable` oder `python`/`python3` aus
`PATH` ist verboten und wird durch ein deterministisches CI-Gate erkannt.

## 3. Begruendung des Umleitungsverhaltens

Ein von einem nicht-virtuellen Interpreter gestartetes `pip install .` oder
`pip install -e .` erzeugt zuerst die dedizierte Umgebung und installiert AK3
dorthin. Danach endet genau dieser aeussere Pip-Aufruf trotzdem mit einem
Fehler, dessen Meldung Grund, Zielpfad und isolierte CLI nennt.

Diese Kombination ist absichtlich:

- Der Fehler ist das belastbare Urteil ueber den angeforderten Vorgang: Eine
  globale Installation ist unzulaessig und darf nicht als erfolgreich gelten.
- Der Seiteneffekt erfuellt zugleich die Installer-Verantwortung. Der Nutzer
  muss weder die vollstaendige AK3-Abhaengigkeitsmenge kennen noch eine
  passende Umgebung von Hand vorbereiten.
- Verworfen wurde der harte Fehlschlag mit blosser Anleitung. Er haette dem
  Nutzer genau das Wissen und die Handarbeit auferlegt, die der Installer
  besitzen und ausfuehren soll.

Der Fehler nach erfolgreicher Umleitung ist daher kein partieller Rollback und
kein versehentliches Verhalten auf einem Fehlerpfad. Er trennt zwei Urteile:
Die dedizierte Installation ist erfolgreich hergestellt; die angeforderte
globale Installation bleibt verboten und fehlgeschlagen.

Ein direktes `pip install agentkit-*.whl` laedt das In-Tree-Backend nicht. Das
Wheel-Format bietet dem Paket keinen standardisierten Pre-Install-Hook, der pip
vor dem Schreiben von Paket und Abhaengigkeiten stoppen oder stattdessen eine
zweite Umgebung provisionieren koennte. Diese Protokollgrenze wird nicht als
erfolgreiche Isolation ueberbehauptet: Die technische Wheel-Installation kann
global erfolgen. AK3 selbst bleibt dort durch die paketweite Importgrenze und
die daraus abgeleiteten Console-Entry-Points fail-closed unbenutzbar und nennt
die dedizierte virtuelle Umgebung als zulaessigen Weg.

Ein anschliessendes `pip uninstall agentkit` mit dem nicht-virtuellen
Ausgangsinterpreter entfernt in diesem Fall **nichts** aus der dedizierten
Umgebung: Der aeussere Interpreter hat dort keinen Installations-Record und hat
global nichts installiert. Maschinen-Uninstall muss den benannten dedizierten
Umgebungspfad sowie Bundle-Store/Shims gezielt entfernen. Ebenso bereinigt die
Umleitung keine bereits vor AG3-189 vorhandene globale Kontamination; deren
Entfernung ist eine separate, explizit freizugebende Operation.

## 4. Konsequenzen und Nachweise

- Der reale Nicht-venv-Pfad muss regulaere und editierbare Installation
  nachweisen: unveraenderte System-/Benutzer-`site-packages`, vollstaendige und
  ausfuehrbare Zielumgebung sowie fehlschlagender aeusserer Aufruf mit Grund und
  Pfad.
- Der Zielpfad darf fuer Tests/Operatoren ueber eine absolute PEP-517-
  Config-Setting-Angabe gesetzt werden; die produktive Vorgabe ist
  plattformspezifisch maschinenlokal.
- Der Wheel-Negativnachweis installiert ein gebautes Wheel mit einem
  nicht-virtuellen Wegwerf-Interpreter in ein eigenes Target-Verzeichnis und
  belegt anschliessend, dass bereits `import agentkit` die Nutzung verweigert.
- Eine globale Vorinstallation wird nicht automatisch entfernt. Auf einer
  Maschine mit produktivem AK2 darf sie nur nach eigener PO-Freigabe bereinigt
  werden.
- AG3-208/AG3-209 duerfen die Isolation nicht mit dem Paketnamenskonflikt
  entfernen; dessen Ende beseitigt nur einen von zwei Gruenden.

## 5. Impact-Sweep (P3/W4)

Geprueft wurden FK-10 als Eigentuemer von Runtime, Deployment,
Maschinen-Provisionierung und Uninstall, FK-22 fuer die deterministische
Setup-/Preflight-Grenze, FK-50 fuer die bestehenden Installer-Checkpoints,
FK-30/FK-76 fuer die Harness-Hook-Ausfuehrung, FK-13 fuer die deklarierte
Weaviate-Abhaengigkeit, `pyproject.toml` fuer Build-Backend und Entry Points,
`PROJECT_STRUCTURE.md` fuer Deployment-Unit-Grenzen sowie der Record
`META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN`. Die Entscheidung
detailliert die bereits in AG3-189 gesetzte Isolationspflicht. Sie aendert weder
die spaetere Zwei-Distributions-Entscheidung noch Paketnamen oder Wire-Vertraege.

## 6. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-10 §10.2.0/§10.2.1 | geaendert | Ebene 2 ist eine dedizierte Umgebung statt einer systemweiten Paketinstallation; Ebene 3 setzt diese Umgebung voraus. |
| FK-10 §10.2.3 | geaendert | Alle AK3-Einsprungpunkte sind an den einen absoluten Interpreter gebunden. |
| FK-10 §10.2.6 | geaendert | Erzeugung, Wiederverwendung, Ablehnung unbrauchbarer Umgebungen und globale Verweigerung sind autoritativ beschrieben. |
| FK-10 §10.2.9 | geaendert | Maschinen-Uninstall entfernt die dedizierte Umgebung; ein aeusseres `pip uninstall` besitzt sie nicht. |
| FK-22 §22.1 | geaendert | Interpreterisolation ist deterministische Laufzeit-Vorbedingung vor den zehn fachlichen Setup-Checks. |
| FK-50 Installer-Checkpoints | geprueft, keine Aenderung | Der vorhandene Package-/Dependency-Checkpoint konsumiert die Vorbedingung; Checkpoint-Topologie und weitere Vertrage bleiben unveraendert. |
| FK-30/FK-76 Harness-Hooks | beruehrt und bestaetigt | Die materialisierten Befehle bleiben die vorgeschriebenen Wrapper `agentkit-hook-claude`/`agentkit-hook-codex`; deren Pfade werden absolut aus dem plattformtypischen Executable-Verzeichnis der zentral aufgeloesten Umgebung gebunden. Direkte Modulpfade bleiben verboten. |
| FK-13 Abhaengigkeiten | geprueft, keine Aenderung | Deklarierte Pflichtabhaengigkeiten werden vollstaendig in die dedizierte Umgebung installiert. |
| `pyproject.toml` | geaendert | Das In-Tree-PEP-517-Backend erzwingt die Source-Grenze; `requires-python` ist die alleinige numerische Quelle der Python-Untergrenze; die deklarierten Console-Entry-Points speisen das statische Interpreter-Gate. |
| `PROJECT_STRUCTURE.md` | geprueft, keine Aenderung | Es entsteht keine neue Deployment Unit oder Verzeichniswurzel. |
| `META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN` | geprueft, nicht ersetzt | Die spaetere Trennung loest den Namenskonflikt; die Drittbibliotheksisolation bleibt. |
| AG3-208/AG3-209 | geprueft, nicht vorweggenommen | Keine Paketumbenennung oder Distributionsmigration in AG3-189. |
