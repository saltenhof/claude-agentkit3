# AG3-228 — AK3 lehnt ab, was AK3 geschrieben hat

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: [AG3-226]` — dort entstand die Inventur und
  der Migrationsmechanismus
- **Herkunft:** Inventur aus AG3-226 R9–R11, 2026-08-06

## Anlass

`T:\codebase\intima` war vollstaendig blockiert: Die verschaerfte
Konfigurationspruefung wies `pipeline.permissions` fail-closed ab — einen
Schluessel, den **AK3 selbst geschrieben hatte**. Jeder Commit brach ab. Ein
`--no-verify` ist dort passiert; wir haben einen fremden Entwickler gezwungen,
seine eigenen Guardrails zu umgehen.

Die Untersuchung ergab, dass das kein Einzelfall war, sondern eine Klasse:

> **Ein Fall ist eine Feld- oder Cross-Field-Regel, fuer die ein produktiver
> AK3-Writer bei einem damals vertragsgueltigen Installerlauf mindestens einen
> Zustand in `.agentkit/config/project.yaml` persistieren konnte, den das
> heutige `ProjectConfig` ablehnt.**

Davon gibt es **elf**. AG3-226 hat auf PO-Entscheid zwei migriert
(`features.vectordb`, `pipeline.permissions`). **Neun sind offen.**

## Warum das dringend ist

**Sechs der neun sind Auslassungsfaelle.** AK3 schrieb ein Feld gar nicht, und
das heutige Modell verlangt es: `project_key`, `pipeline.sonarqube`,
`pipeline.ci`, `pipeline.sonarqube.scanner_version`, `pipeline.config_version`,
`pipeline.llm_roles`.

Ein Projekt, das vor der jeweiligen Verschaerfung installiert wurde, **laedt
seine Konfiguration heute nicht mehr**. Es ist arbeitsunfaehig — genau der
Zustand, in dem intima war. Das ist kein latenter Mangel, der irgendwann
auffaellt, sondern ein bereits eingetretener Zustand bei jeder betroffenen
Installation. Er faellt nur deshalb nicht auf, weil niemand nachgesehen hat.

`pipeline.config_version` ist der haerteste Fall: Der Upgrade-Reader verweigert
ausdruecklich fail-closed, eine Ausgangsversion zu erfinden. Ein Projekt ohne
dieses Feld kann sich also **nicht einmal upgraden**, um repariert zu werden.
Wer diese Story schneidet, faengt hier an.

## Das Universum ist aufgezaehlt — vor Arbeitsbeginn

`inventur.md` neben dieser Datei nennt je Fall: Feld und heutigen Locator, den
verschaerfenden Commit, den historischen und heute abgelehnten Wert, den
produktiven Writer-Commit und ob eine Migration existiert. Dazu die Methode
ueber vier Achsen (Historie, Writer, Modell, Vergleich), die bewussten
Ausschluesse und eine begruendete Geschlossenheitsaussage.

**Das ist der ausdrueckliche Unterschied zu AG3-189.** Dort kostete eine
Universalzusage ueber eine nie aufgezaehlte Menge 22 Reviewrunden: Jede Runde
fand die naechste Instanz, und keine Runde sagte etwas ueber die Menge. Hier
liegt die Menge vorher fest.

**Daraus folgt eine Regel fuer die Umsetzung:** Findet sich waehrend der Arbeit
ein zwoelfter Fall, wird er **gemeldet, nicht stillschweigend mitgenommen**. Er
gehoert in die Inventur, und seine Aufnahme in den Scope ist eine
PO-Entscheidung. Eine Story, die ihr eigenes Universum waehrend der Umsetzung
erweitert, hat kein Universum.

## Scope

### In Scope

- **Die neun offenen Faelle bekommen eine Migration** im produktiven
  Upgrade-Pfad. Der Mechanismus existiert bereits aus AG3-226
  (`installer/upgrade/config_migration.py`) und ist dort gegen TOCTOU,
  Symlinks an den Temp-Pfaden und Digest-Drift abgesichert.
- **Fuer jeden Fall wird entschieden und begruendet, was der Zielwert ist.** Bei
  einer Auslassung ist das eine Aussage darueber, was AK3 fuer dieses Projekt
  annehmen darf — und das ist nicht immer trivial. `project_key` etwa laesst
  sich nicht erfinden.
- **Verhaltensaendernde Migrationen werden sichtbar gemeldet**, mit Projekt,
  Feld und alter/neuer Wirkung — wie in AG3-226 fuer `features.vectordb`.
- **Der Fall, der sich nicht migrieren laesst**, wird als solcher benannt und
  bekommt einen fail-closed Weg mit verstaendlicher Meldung, was der Betreiber
  tun muss. Eine unbeantwortbare Frage wird nicht geraten.
- **Eine Regel, die verhindert, dass die Klasse zurueckkehrt.** Deterministisch,
  im regulaeren Gate: Wer das Konfigurationsmodell verschaerft, muss die
  Migration mitliefern oder die Verschaerfung begruenden.

### Out of Scope

- **Das Verhalten der betroffenen Felder wird nicht neu verhandelt.** Dass
  VektorDB Pflicht ist, dass Sonar CI voraussetzt, dass die Endpunktmenge eng
  ist — das steht fest. Diese Story migriert Bestandskonfigurationen darauf.
- Die beiden bereits in AG3-226 migrierten Faelle 8 und 9.
- Handgeschriebene oder operatorseitig veraenderte Konfigurationen. Die
  Inventur schliesst sie ausdruecklich aus, weil sie keinen von AK3 erzeugten
  Altzustand belegen.

## Akzeptanzkriterien

1. **Jeder der neun Faelle hat eine Migration oder eine begruendete
   Verweigerung** mit verstaendlicher Handlungsanweisung. Kein Fall bleibt
   unbeantwortet.
2. **Der Nachweis laeuft ueber den produktiven Upgrade-Pfad**, nicht ueber
   direkte Funktionsaufrufe. Je Fall eine Bestandskonfiguration, die den
   historischen Zustand traegt, danach gueltig ist.
3. **Ein Projekt ohne `pipeline.config_version` wird wieder erreichbar.** Wenn
   der Upgrade-Reader eine Ausgangsversion fail-closed verweigert, muss ein
   anderer, benannter Weg existieren — sonst ist die Story an ihrem haertesten
   Fall gescheitert und behauptet trotzdem Erfolg.
4. **Verhaltensaendernde Migrationen sind sichtbar.** Test je Fall, der die
   Meldung prueft, nicht nur die Transformation.
5. **Fremde und unbekannte Geschwisterschluessel bleiben unberuehrt.** Die
   Migration darf unter keiner Eingabe zum generischen „unbekannte Keys
   wegputzen" werden.
6. **Die Zusagen aus AG3-226 gelten unveraendert weiter:** eine
   digest-validierte Byte-Baseline, Compare-and-swap vor dem Replace,
   Symlink-/Junction-Schutz auch an den abgeleiteten Temp-Pfaden, und die
   Trennung zwischen eigener Migration und Nutzeraenderung. Beleg, dass der
   Umbau sie nicht schwaecht.
7. **Die Klasse kann nicht zurueckkehren.** Deterministischer Check im
   regulaeren Gate, mit sichtbarer und begruendeter Ausnahmeliste. Er ist gegen
   einen kuenstlich eingefuegten Verstoss geprueft — ein Gate, das falsch gruen
   meldet, entwertet jede Aussage, die es je gemacht hat.
8. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle sechs
   deterministischen Konzept-Gates gruen; volle Suite gruen auf Jenkins;
   Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Ein zwoelfter Fall, falls gefunden, ist gemeldet und **nicht** stillschweigend
  mitgenommen.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — „Keine Schuld ist billiger als ihre
  Beseitigung"; hier ist die Rechnung bereits bei einem Dritten angekommen
- `CLAUDE.md` §FAIL-CLOSED — AC 3, kein Erfinden einer Ausgangsversion
- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — migrieren, nicht zwei Formate
  parallel lesen
- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 2
