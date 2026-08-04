---
concept_id: META-DEC-2026-08-04-ABHAENGIGKEITSVOLLSTAENDIGKEIT-UND-HOOK-FEHLERSICHTBARKEIT
title: Concept-Decision-Record — Abhaengigkeitsvollstaendigkeit und Hook-Fehlersichtbarkeit
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, installation, dependencies, hooks, observability, AG3-206]
formal_scope: prose-only
---

# Concept-Decision-Record — Abhaengigkeitsvollstaendigkeit und Hook-Fehlersichtbarkeit

Datum: 2026-08-04. Record gemaess META-CONCEPT-CONSISTENCY P3/W4 fuer
AG3-206.

## 1. Anlass

In einer Fremdinstallation liefen an einem Tag 164
`hook_non_blocking_error`-Ereignisse auf. 90 davon meldeten
`ModuleNotFoundError: No module named 'tomlkit'`, obwohl `tomlkit` seit jeher
als Pflicht-Abhaengigkeit in `pyproject.toml` deklariert war. Alle betroffenen
Guards starben vor ihrer Fachlogik. Ein Fehler verschluckender Hook war dabei
von einem erfolgreich ausgefuehrten Hook nicht unterscheidbar.

Der bereits ratifizierte Record
META-DEC-2026-08-03-ABHAENGIGKEITEN-LEBEN-IN-EINER-VENV setzt die groben
Pfosten: AK3 lebt mit seinen Abhaengigkeiten in einer virtuellen Umgebung, und
ein Preflight muss deklarierte gegen importierbare Abhaengigkeiten pruefen.
Dieser Record detailliert deren Eigentum, Reihenfolge und Sichtbarkeit.

## 2. Entscheidung

### 2.1 Die Deklaration ist die einzige Paketwahrheit

Der Runtime-Preflight leitet den Pflichtsatz direkt aus der Paketdeklaration
ab. In einer installierten Distribution liest er `Requires-Dist`; bei einer
expliziten Quellpruefung liest er `project.dependencies` aus
`pyproject.toml`. Beide sind verschiedene Projektionen derselben
Paketdeklaration. Eine zweite, im Anwendungscode gepflegte Liste von
Distributionen oder Importnamen ist verboten.

Der Nachweis umfasst fuer jede Pflicht-Abhaengigkeit die installierte
Distribution und ihre oeffentlichen Top-Level-Importe. Extra-gebundene
optionale Abhaengigkeiten sind nicht Teil dieses Pflichtsatzes. Ein nicht
lesbarer oder nicht eindeutig aufloesbarer Deklarationszustand ist kein PASS.

### 2.2 Vollstaendigkeit wird vor Seiteneffekten bewiesen

Der Preflight laeuft vor Konfigurationsauswertung, Fremdsystem-Probes,
Bundle-Erzeugung und Zielprojektmutation. Bei einem Befund entsteht
ausschliesslich der fehlgeschlagene erste Installer-Checkpoint. Bei einem
abhaengigkeitsspezifischen Befund nennt die Diagnose Distribution, Ursache und
ein Installationskommando fuer genau den Interpreter aus `sys.executable`. Bei
einer fehlenden oder unlesbaren Deklaration nennt sie stattdessen
Deklarationsquelle und Ursache; Distribution und Installationskommando werden
ohne auswertbare Deklaration nicht erfunden.

Dieser Record entscheidet nicht, ob eine Umgebung global oder virtuell sein
darf und auch nicht, wer eine virtuelle Umgebung erzeugt. Diese Art- und
Lebenszyklusentscheidung bleibt beim Venv-Record und AG3-189. Hier wird nur
die Vollstaendigkeit des ausfuehrenden Interpreters entschieden.

### 2.3 Ein Hook darf seinen eigenen Ausfall nicht als Erfolg darstellen

Alle zur Hook-Auswertung notwendigen Fachimporte liegen innerhalb der
fail-closed Fehlergrenze des jeweiligen Einstiegspunkts. Import- und
Auswertungsfehler erzeugen eine maschinenlesbare Blockentscheidung und einen
Exit-Code ungleich null. Mitgelieferte Zielprojekt-Hooks duerfen diesen Zustand
nicht durch Shell-Konstrukte wie `|| true` in Erfolg verwandeln.

Die bestehende oeffentliche Installer-Oberflaeche bleibt erhalten. Ihre
stdlib-only Eingangsgrenze fuehrt den Abhaengigkeits-Preflight aus, bevor sie
den eigentlichen Checkpoint-Orchestrator oder runner-gebundene Exporte lazy
laedt. Das gilt auch fuer den ueblichen kombinierten Import von `InstallConfig`
und `install_agentkit`. Dadurch kann auch ein am Top-Level importiertes
fehlendes Paket diagnostiziert werden, ohne dass der Import des
Installer-Pakets seine eigene Diagnose verhindert.

### 2.4 Persistierte Hook-Fehler werden deterministisch sichtbar

Ein read-only CLI-Bericht wertet JSONL-Transcripte aus. Er zaehlt
`hook_non_blocking_error`-Attachments, gruppiert sie nach dem exakten
`command` des Hook-Handlers,
normalisiert ANSI-Steuercodes und Zeilenenden und dedupliziert identischen
normalisierten Fehlertext nur innerhalb dieses Hooks unter Beibehaltung seiner
Haeufigkeit. Optionale inklusive Zeitgrenzen muessen einen expliziten
UTC-Offset tragen. Unlesbare Zeilen, ungueltige Attachments oder ungueltige
Zeitstempel brechen den Bericht ab; ein unbekannter Zustand wird nicht als
leerer Erfolg gemeldet.

## 3. Abgrenzung und offene Fehler ausserhalb des Mandats

`pyproject.toml` wird durch diese Umsetzung weder veraendert noch repariert;
der Preflight prueft die vorhandene Deklaration. Es entstehen keine
Kompatibilitaetsschicht und kein alternativer Installationspfad.

Vier aktive Hook-Kommandos in der benutzerspezifischen Datei
`C:/Users/Sir Freejack/.claude/settings.json` verschlucken ihren Fehler durch
`2>/dev/null || true`: `orchestrator-guard.py`, `agent-branch-guard.sh`,
`bugfix-test-guard.py` und `review-prompt-guard.py`. Das ist ein ERROR, liegt
aber ausserhalb des Repositories und damit ausserhalb des AG3-206-Mandats.
Dieser Record autorisiert keine Aenderung daran; fuer die Korrektur ist ein
separates Mandat des Product Owners erforderlich.

Daneben besteht ein belegter Konzept-/Realitaetswiderspruch: FK-30s
Glossareintrag `hook-enforcement` (aktuell Zeilen 71–76) sowie §30.2.4,
Tabelle und Fail-closed-Absatz (aktuell Zeilen 217–225), behaupten,
jeder Hook-Crash mit Exit-Code 1, Timeout oder Exception blockiere das Tool und
werde dem Agenten als Fehler angezeigt. Der Vorfall vom 2026-08-03 belegt das
Gegenteil: 164 `hook_non_blocking_error`-Attachments wurden persistiert, ohne
die Tool-Aufrufe zu blockieren oder dem Agenten sichtbar zu werden. FK-76
§76.1–76.2 (aktuell Zeilen 96–124) besitzt die harness-spezifischen
stdin/stdout-/Exit-Code-Konventionen und damit die Autoritaet fuer die
tatsaechliche Claude-Code- und Codex-Semantik. FK-30 und FK-76 sind fuer
AG3-206 nicht zur Aenderung freigegeben; der Widerspruch bleibt deshalb
ausdruecklich offen und ist kein PASS. Aufloesen muessen ihn der FK-76-Owner
fuer den Harness-Vertrag und der FK-30-Owner fuer die daraus folgende
harness-neutrale Enforcement-Aussage, bei noetiger Grundentscheidung mit dem
Product Owner.

## 4. Impact-Sweep (P3/W4)

Geprueft wurden der Venv-Decision-Record als Anker fuer die Art der Umgebung,
FK-22 fuer den Story-Setup-Scope, FK-10 fuer Runtime-Topologie,
FK-15 fuer Fehler- und Sicherheitsgrenzen, FK-30 und FK-31 fuer den
Project-Edge und seine Bundles, FK-50 und FK-51 fuer Installer-Checkpoints und
CLI, FK-76 fuer Observability, FK-91 fuer den API-Katalog sowie der
Architektur-Conformance-Vertrag. Die neue Aussage detailliert ausschliesslich
den bereits verlangten Abhaengigkeits-Preflight und die daraus folgende
fail-closed Hook-Grenze. Sie verschiebt keine Runtime-, Secret-, API- oder
Deployment-Unit-Zustaendigkeit und eroeffnet keine neue Konzeptdomaene. Der
Abhaengigkeitscheck ist beim Installer-Owner FK-50 verankert; FK-22 behauptet
keinen Lauf mehr bei `POST /phases/setup/start`.

FK-30 und die reale Harness-Semantik sind nicht widerspruchsfrei; die bekannte
Luecke ist in Abschnitt 3 mit Ownern und Locatoren benannt. FK-30 und FK-76
bleiben unveraendert, weil das Mandat ihre Aenderung ausschliesst. Insbesondere
bleibt die Durchsetzung der Venv AG3-189 vorbehalten.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| Venv-Decision-Record vom 2026-08-03 | geprueft, nicht geaendert | Er liefert den Anker und bleibt Eigentuemer der Umgebungsart; AG3-206 detailliert nur deren Vollstaendigkeitsnachweis. |
| FK-22 Zweck, Ablauf, Preflight und Fehlerbehandlung | geprueft und zurueckgenommen | Der Installer-Check wurde aus dem Story-Setup entfernt; `POST /phases/setup/start` startet weiterhin unmittelbar den zehnteiligen Story-Preflight. |
| FK-50 CP 1 und Fehlerbehandlung | geaendert | Der Installer ist Owner der stdlib-only Eingangsgrenze, Deklarationsableitung, fruehesten Reihenfolge und Diagnose. |
| FK-10, FK-15, FK-31, FK-51, FK-91 | geprueft, nicht geaendert | Bestehende Runtime-, Security-, Edge-, Upgrade- und API-Zustaendigkeiten bleiben unveraendert. |
| FK-30 Glossar `hook-enforcement` (Zeilen 71–76), §30.2.4 (Zeilen 217–225) und FK-76 §76.1–76.2 | Widerspruch offen, nicht geaendert | FK-30 behauptet Blockade und Agentensichtbarkeit jedes Hook-Crashs; der reale Harness persistierte 164 Fehler non-blocking und unsichtbar. Aufloesung durch FK-76-/FK-30-Owner, ggf. Product Owner. |
| Architektur-Conformance-Vertrag | geprueft, nicht geaendert | Lazy Imports und lokale Hook-Fehlergrenzen verschieben keine Deployment Unit und fuehren keine neue Abhaengigkeitskante ein. |
| `src/agentkit/backend/installer/` | geaendert | Der deklarationsgetriebene Check laeuft vor Checkpoints und Mutationen; der oeffentliche Namespace bleibt lazy erhalten. |
| `src/agentkit/backend/cli/` | geaendert | Installer-Verben erhalten die fruehe Sperre; `hook-errors` stellt persistierte Befunde read-only dar. |
| Harness-Adapter und Zielprojekt-Bundle | geaendert/geprueft | Fachimporte liegen innerhalb der fail-closed Hook-Grenze; mitgelieferte Hooks enthalten keinen Error-Bypass. |
| Gezielte Installer-, CLI- und Harness-Tests | geaendert | Deklarationsableitung, Abbruch vor Mutation, Aggregation, Importfehler und Bypass-Verbot werden belegt. |
| Wegwerf-venvs unter `var/` | real geprueft | Je genau ein deklariertes Paket fehlt: `tomlkit` sowie das am Top-Level importierte `pydantic`. Installer-Import und CLI diagnostizieren vor tieferen Imports; beide Hook-Adapter blockieren ohne `pydantic` maschinenlesbar mit Exit 2. |
| Fremdinstallationstranscript vom 2026-08-03 | real geprueft, PASS | Der Orchestrator hat `hook-errors` gegen die Original-JSONL der Fremdinstallation (`~/.claude/projects/T--codebase-intima/`) gefahren — ausserhalb des Repository-Mandats des Umsetzers, daher durch den Auftraggeber selbst. Mit `--since 2026-08-03T00:00:00Z --until 2026-08-03T23:59:59Z` liefert `3aa6a7b8-…jsonl` 176 Fehler in fuenf Hook-Gruppen (`post commit_hook` 26, `post health_monitor` 26, `pre commit_hook` 28, `pre skill_usage_check` 28, `python .agentkit/hooks/pre_tool_use.py` 68), `0bb1451f-…jsonl` 1676 in acht Gruppen. Jede Gruppe dedupliziert auf **genau einen** Fehlertext (`No module named 'tomlkit'` bzw. `No module named 'agentkit.governance'`) — 301 Ereignisse zu einer Zeile. Der Lauf belegt zugleich die `command`-Achse: `post commit_hook` und `post health_monitor` sind derselbe `hookName` `PostToolUse` und waeren ohne sie verschmolzen. |
| `C:/Users/Sir Freejack/.claude/settings.json` | ERROR, nicht geaendert | Vier aktive externe Hooks verschlucken Fehler; die notwendige Aenderung liegt ausserhalb des erteilten Mandats. |
