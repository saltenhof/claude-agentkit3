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
tags: [meta, decision-record, deployment, installer, interpreter, skill-bundles, FK-10, FK-21, FK-22, FK-36, FK-43, FK-50, FK-76]
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

Die Importgrenze entscheidet dabei ueber die Provenienz des gerade importierten
Pakets, nicht ueber den Distributionsnamen allein: Wheel-Dateiliste oder
standardisierte Editable-Quelle muessen genau auf diese `agentkit`-Quelle
zeigen. Eine vorhandene gleichnamige Fremd-/Alt-Distribution blockiert den
In-Tree-PEP-517-Bootstrap deshalb nicht.

**2.3 Es gibt genau einen Interpreter-Owner.** CLI, Installer, Git-Hooks,
MCP-Server und Harness-Hooks beziehen den absoluten AK3-Interpreter aus
derselben Aufloesung. Diese prueft eine aktive virtuelle Umgebung,
`include-system-site-packages = false` und eine existente Interpreterdatei.
Direkte Einsprungpunkt-Nutzung von `sys.executable` oder `python`/`python3` aus
`PATH` ist verboten und wird durch ein deterministisches CI-Gate erkannt.
Dasselbe Gate inventarisiert ausfuehrbare Shell-Kommandos in allen produktiv
bindbaren Skill-Bundle-Versionen. Es untersucht jede Markdown-Code-Fence
einschliesslich Fortsetzungszeilen und erkennt Kommandos anhand ihrer
Interpreter-/Wrapper-Tokens statt anhand der Fence-Sprache. `text`, `plain`,
ein leerer oder ein unbekannter Sprach-Tag sowie eine Ueberschrift koennen einen
darin stehenden Interpreteraufruf nicht von der Pruefung ausnehmen; reine
Inventuren enthalten nur Pfade oder Modulnamen.
Das Gate weist nackte `python`/`python3`-Aufrufe und Python-`-m`-Ziele ohne
Moduldatei beziehungsweise Paket-`__main__.py` sowie nackte `agentkit`-Wrapper
aus `PATH` zurueck. Installer-gespeiste absolute
Interpreter-/Wrapperwerte laufen durch den vorhandenen Materialisierungs-Owner
des BC `agent-skills`; der Installer implementiert keine zweite Substitution.
Shell-Quotes, Backslashes und Fortsetzungszeilen werden rein textuell
normalisiert. Enthaelt ein geprueftes Textstueck `$(`, einen Backtick oder
`$'`, wird es allein aufgrund dieses Markers als `undecidable` mit Locator und
Rohtext abgelehnt; Balance, Escape-Semantik und Shell-Auswertung werden nicht
betrachtet.
Ergaenzend weist das Gate ein nacktes Selektorliteral in den Argumenten jedes
produktiven Python-Aufrufs unabhaengig von Callable- oder Prozess-API-Provenienz
zurueck; nachweisliche Datenwerte stehen in einer fail-stale Ausnahmeliste, die
bei jedem erfolgreichen Lauf vollstaendig sichtbar ist. Unbekannte Hook-Typen
werden fail-closed als nicht auditierbar gemeldet.

Ausfuehrbare Konzeptbeispiele und formale Command-Signaturen schreiben den
physischen Einstieg deshalb als `<absolute-agentkit-wrapper>`,
`<absolute-agentkit-hook-{harness}-wrapper>` oder
`<absolute-ak3-interpreter>`. Der jeweilige Suffix ist die logische
CLI-/Hook-Signatur; der Platzhalter bezeichnet den vom zentralen Owner
aufgeloesten absoluten Pfad und darf nie als Literal materialisiert werden.
Reine Aussagen ueber verbotene Altformen, Paket-/Modulnamen und
Programmiersprachen sind keine ausfuehrbaren Beispiele.

**2.4 Die Python-Untergrenze hat keine tool-spezifische Kopie.**
`project.requires-python` ist die einzige numerische Quelle. Insbesondere darf
Ruff keinen eigenen `target-version`-Wert fuehren; das deterministische Gate
weist einen solchen Override zurueck, damit eine Aenderung der Quelle alle
Konsumenten erreicht.

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
- Derselbe reale Nachweis erzeugt eine `venv --system-site-packages`, macht das
  Wheel ueber deren System-Site sichtbar und belegt die Verweigerung sowohl fuer
  `import agentkit` als auch fuer einen produktiven `python -m`-Einstieg.
- Ein realer Bootstrap-Nachweis haelt eine gleichnamige Distribution im
  Wegwerf-Interpreter sichtbar und fuehrt regulaeren wie editierbaren
  `--no-build-isolation`-Aufruf aus; beide muessen die dedizierte Umgebung
  herstellen, statt vor dem Redirect am Parent-Package-Import zu scheitern.
- Eine globale Vorinstallation wird nicht automatisch entfernt. Auf einer
  Maschine mit produktivem AK2 darf sie nur nach eigener PO-Freigabe bereinigt
  werden.
- AG3-208/AG3-209 duerfen die Isolation nicht mit dem Paketnamenskonflikt
  entfernen; dessen Ende beseitigt nur einen von zwei Gruenden.
- Die numerische Mindest-Konformversion jedes Skill-Bundles gehoert
  ausschliesslich `src/agentkit/backend/skills/version_policy.py`; dieser
  Beschluss und FK-43 fuehren keine zweite Floor-Tabelle. Historische
  unveraenderliche Varianten von `create-userstory-core` bleiben im Store,
  liegen aber unter der produktiven Mindest-Konformversion des Owners.
- Die produktiv konforme Variante von `execute-userstory-core` bindet ihre
  `run-phase`-Aufrufe an denselben absoluten Wrapper. Historische Varianten mit
  Direktaufrufen nicht existenter Module bleiben unveraendert unter der
  produktiven Mindest-Konformversion; Struktur-, Reproducer- und Policy-Arbeit
  bleibt beim bereits verwendeten Verify-Phase-Owner.
- Die produktiv konforme Variante von `concept-incubation-core` bindet ihre
  Toolchain-Scriptaufrufe an den installergebundenen absoluten Interpreter.
  Historische Varianten mit in einem `text`-Fence versteckten nackten
  PATH-Python-Aufrufen bleiben unveraendert unter der produktiven
  Mindest-Konformversion.
- Die vier Compaction-Resilience-Hooks aus FK-36 verwenden in Lifecycle-Prosa
  und Konfigurationsbeispielen denselben zentral aufgeloesten und
  shell-gerenderten absoluten AK3-Interpreter. Ein nackter PATH-Interpreter ist
  dort kein zulaessiger Hook-Vertrag.

## 5. Impact-Sweep (P3/W4)

Geprueft wurden FK-10 als Eigentuemer von Runtime, Deployment,
Maschinen-Provisionierung und Uninstall, FK-21 fuer die produktiven
Story-Creation-Aufrufe, FK-22 fuer die deterministische Setup-/Preflight-Grenze,
FK-36 fuer die vier Compaction-Resilience-Hooks, FK-43 fuer Bundle-Versionierung
und Materialisierung, FK-50 fuer CP9, CP10, CP10b und die
Installer-zu-Skills-Grenze, FK-30/FK-31/FK-76 fuer die
Harness-Hook-Ausfuehrung, FK-13 fuer den MCP-Registrierungsvertrag,
`pyproject.toml` fuer
Build-Backend und Entry Points, `PROJECT_STRUCTURE.md` fuer
Deployment-Unit-Grenzen sowie der Record
`META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN`. Die Entscheidung
detailliert die bereits in AG3-189 gesetzte Isolationspflicht. Sie aendert weder
die spaetere Zwei-Distributions-Entscheidung noch Paketnamen oder Wire-Vertraege.

## 6. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-10 §10.2.0/§10.2.1 | geaendert | Ebene 2 ist eine dedizierte Umgebung statt einer systemweiten Paketinstallation; Ebene 3 setzt diese Umgebung voraus. |
| FK-10 §10.2.3 | teilweise; H1-Rest gesperrt | Der Interpretervertrag ist geaendert. Der Korpus-Sweep weist in der fuer AG3-214 gesperrten FK-10 jedoch weiterhin 25 nackte, ausfuehrbare `agentkit`-Darstellungen aus; diese Runde aendert sie nicht und behauptet fuer FK-10 keine vollstaendige Bereinigung. |
| FK-21 §21.10.2/§21.11.4/§21.11.7 | geaendert | Der Story-Creation-Skill verwendet fuer ProjectEdge, VektorDB-Preflight und Export nur installergebundene absolute Interpreter-/Wrapperwerte; das nicht existente `python -m agentkit` ist entfernt. |
| FK-10 §10.2.6 | geaendert | Erzeugung, Wiederverwendung, Ablehnung unbrauchbarer Umgebungen, Provenienz der importierten Distribution, vollstaendige Isolation auch in `--system-site-packages`-venvs und globale Verweigerung sind autoritativ beschrieben. |
| FK-10 §10.2.9 | geaendert | Maschinen-Uninstall entfernt die dedizierte Umgebung; ein aeusseres `pip uninstall` besitzt sie nicht. |
| FK-22 §22.1 | geaendert | Interpreterisolation ist deterministische Laufzeit-Vorbedingung vor den zehn fachlichen Setup-Checks. |
| FK-36 §36.7.2-§36.8.1 | geaendert | Alle vier Compaction-Resilience-Hooks und ihre Konfigurationsbeispiele verwenden den zentral aufgeloesten und shell-gerenderten absoluten AK3-Interpreter statt eines nackten PATH-Interpreters. |
| FK-43 §43.4.2/§43.5.2 | geaendert | Der gemeinsame `PlaceholderSubstitutor` besitzt die abgegrenzten Spawn-Header- und Materialisierungswege. Installer-gespeiste Interpreter-/Wrapper-Tokens laufen durch den Materialisierungsweg; produktive Bundle-Versionen, alle Code-Fences unabhaengig von ihrem Sprach-Tag, kommandofoermige Inventuren, Fortsetzungszeilen und `-m`-Ziele werden statisch geprueft. Historische normverletzende Bundle-Versionen bleiben unveraendert unter den ausschliesslich vom Code-Owner gefuehrten Mindest-Konformversionen. |
| FK-50 CP9/CP10/CP10b/§50.5 | teilweise; H1-Rest gesperrt | ProjectEdge-Wrapper, Story-Knowledge-Base-MCP und Concept-Hooks verwenden in den bereits nachgezogenen Stellen den zentral aufgeloesten absoluten Interpreter. Der H1-Sweep weist daneben die nackten CLI-Darstellungen in §50.1 sowie das nackte `agentkit-are-mcp` im ARE-Registrierungsbeispiel aus; FK-50 ist fuer AG3-214 gesperrt und wird hier nicht geaendert. Der Installer substituiert nicht selbst. |
| FK-30/FK-76 Harness-Hooks | geaendert | Die Claude-/Codex-Materialisierungen zeigen ausschliesslich absolute Wrapperplatzhalter; deren Pfade werden aus dem plattformtypischen Executable-Verzeichnis der zentral aufgeloesten Umgebung gebunden. Direkte Modulpfade und nackte Wrappernamen bleiben verboten. |
| FK-31 §31.6.2 | geaendert | Das harness-spezifische Adversarial-Guard-Beispiel materialisiert denselben absoluten Wrapperpfad statt eines nackten Wrappernamens. |
| FK-13 §13.4.3 | geaendert | Der Story-Knowledge-Base-MCP registriert den zentral aufgeloesten absoluten AK3-Interpreter; ein nacktes `python` ist kein Registrierungswert. |
| FK-03/FK-04/FK-15/FK-18/FK-20-FK-22/FK-26/FK-28-FK-31/FK-33/FK-35/FK-38/FK-39/FK-42/FK-45/FK-49/FK-53-FK-56/FK-58/FK-60/FK-62/FK-63 | geaendert | Alle dortigen ausfuehrbaren Operator-/Recovery-/Runbook-Beispiele und Command-Tabellen verwenden den absoluten `agentkit`-Wrapperplatzhalter. Paket-, Modul- und Verbotsnennungen bleiben als Nennungen sichtbar. |
| Formale Command-Spezifikationen (`deterministic-checks`, `escalation`, `exploration`, `guard-system`, `implementation`, `installer`, `integrity-gate`, `principal-capabilities`, `setup-preflight`, `story-closure`, `story-creation`, `story-reset`, `story-split`, `story-workflow`, `telemetry-analytics`, `verify`) sowie `installer/scenarios.md` | geaendert | Physische Command-Signaturen beginnen mit dem absoluten Wrapperplatzhalter; der ProjectEdge-Launcher mit dem absoluten Interpreterplatzhalter. Nachfolgende Verben und Argumente bleiben der logische Wire-/CLI-Vertrag. |
| Decision Records `2026-07-11-resume-als-soll-crash-continuation`, `2026-08-02-port-9702-single-owner-und-endpunkt-herkunft`, `2026-08-03-erstzugang-bootstrap` | geaendert | Ausfuehrbare CLI-Pfade verwenden den absoluten Wrapperplatzhalter. |
| FK-41/FK-51/FK-91 und `2026-08-04-ein-writer-ein-vertrag` | H1-Rest gesperrt | Der Sweep weist dort weitere nackte ausfuehrbare Wrapper-/Interpreterdarstellungen aus. Diese Dateien gehoeren AG3-214; die vollstaendige Locatorliste ist Bestandteil des Runden-Nachweises, nicht stillschweigend als bereinigt gewertet. |
| `konzept-konsistenz-governance.md` | H1-Rest gesperrt | Zwei nackte Python-Aufrufe sind ausfuehrbare Governance-Anweisungen, aber die Datei gehoert AG3-219 und bleibt unveraendert. |
| `pyproject.toml` | geaendert | Das In-Tree-PEP-517-Backend erzwingt die Source-Grenze; `requires-python` ist ohne Ruff-Override die alleinige numerische Quelle der Python-Untergrenze; die deklarierten Console-Entry-Points speisen das statische Interpreter-Gate. |
| `PROJECT_STRUCTURE.md` | geprueft, keine Aenderung | Es entsteht keine neue Deployment Unit oder Verzeichniswurzel. |
| `META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN` | geprueft, nicht ersetzt | Die spaetere Trennung loest den Namenskonflikt; die Drittbibliotheksisolation bleibt. |
| AG3-208/AG3-209 | geprueft, nicht vorweggenommen | Keine Paketumbenennung oder Distributionsmigration in AG3-189. |

**Nachfolgequalifizierung (2026-08-05) zu den Matrixzeilen FK-21 und formale
Command-Spezifikationen:** Dieser Record entscheidet ausschliesslich die
Interpreter- und Wrapperisolation. Die spaetere Entscheidung
[`2026-08-05-delegationsrichtung-und-kontextschonung.md`](2026-08-05-delegationsrichtung-und-kontextschonung.md)
entscheidet die Akteursfrage: Der Story-Creation-Skill nimmt den Weg ueber
Project Edge; physische Signaturen mit `<absolute-agentkit-wrapper>` bezeichnen
den menschlichen beziehungsweise administrativen Operator-CLI-Pfad, nicht den
Agentenpfad. Der physische Isolationsvertrag dieses Records bleibt davon
unveraendert.
