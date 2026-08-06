# AG3-220 — Jeder Wert hat genau einen Eigentuemer

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: [AG3-189, AG3-214]` — beide fassen aktuell
  Konzeptdateien an, die hier beruehrt werden.
- **Herkunft:** AG3-189 R15 am 2026-08-05.

## Befund — belegt, mit Locator

Der in AG3-189 beauftragte Konzeptkorpus-Sweep fasste 54 Dateien an und legte
dabei Widersprueche frei, die mit Interpreter-Isolation **nichts zu tun haben**.
Sie stehen hier, statt AG3-189 weiter aufzublaehen — dort waeren sie ein
zweiter, fremder Auftrag im selben Schnitt.

Gemeinsames Muster: **ein Wert oder eine Aussage hat zwei Eigentuemer.** Solche
Paare driften, und niemand ist zustaendig, es zu merken (`CLAUDE.md`
§REALITAETSNACHWEIS: „Ein Wert, der nur im Code lebt, driftet — und niemand ist
zustaendig, es zu merken." Hier ist es umgekehrt und genauso teuer).

### B1 — Installationsform

`concept/technical-design/01_systemkontext_und_architekturprinzipien.md:37`
nennt AK3 weiterhin ein „systemweit installiertes Python-Paket". Der Decision
Record `2026-08-04-installationsisolation.md` §2.1 sagt das Gegenteil, und
genau diese Annahme hat am 2026-08-02 AK2 zerstoert.

`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:535-537`
fuehrt dieselbe veraltete Formulierung. **FK-50 ist derzeit von Story AG3-214
gehalten** — dort nicht anfassen, sondern nach deren Abschluss.

### B2 — Python-Untergrenze

Der Record `:93-97,:220` erklaert `project.requires-python` zur **einzigen**
numerischen Quelle der Python-Untergrenze. FK-01 publiziert bei `:212` und
`:466` weiterhin `Python 3.14`.

### B3 — Bundle-Floors

FK-43 `:458-462` sagt, **ausschliesslich** `backend/skills/version_policy.py`
duerfe numerische Floors fuehren. FK-50 `:545-548` publiziert sie trotzdem —
und fuehrt fuer `create-userstory-core` `4.2.0`, waehrend der Code `4.3.0`
fuehrt. Der Drift ist also nicht theoretisch, er ist bereits eingetreten.

Ebenfalls offen: der Floor fuer `lookup-userstory-core`
(`version_policy.py:18`) hat keine semantische Begruendung im Konzept; FK-43
`:458-474` und der Record `:163-177` erklaeren nur Create, Execute und Concept
Incubation.

## Scope

### In Scope

- Je Wert **einen** Eigentuemer benennen und die uebrigen Stellen auf ihn
  verweisen lassen, statt die Zahl oder Formulierung zu wiederholen.
- Der maschinelle Schutz gegen doppelte Autoritaet: Er muss den **gesamten**
  Konzept- und Guardrail-Korpus erfassen, nicht nur ausgewaehlte
  Eigentuemertexte, und semantische Versionswerte unabhaengig von Backticks
  erkennen. Ein Schutz, der den bereits eingetretenen FK-50-Drift nicht findet,
  schuetzt nichts.
- Fehlende Begruendungen ergaenzen (Floor fuer `lookup-userstory-core`) oder
  den Floor entfernen, wenn er unbegruendet ist.

### Out of Scope

- **Der normative Widerspruch ueber agentische CLI-Aufrufe.** Siehe unten; das
  ist eine PO-Entscheidung, keine Redaktionsarbeit.
- Interpreter-/Wrapper-Aufrufe in Konzeptbeispielen — das ist AG3-189.
- Umformulierungen ohne Eigentuemerfrage. Diese Story raeumt Doppelautoritaet
  auf, nicht Stil.

## AUSDRUECKLICH NICHT IN DIESER STORY — PO-Entscheidung offen

Der Sweep hat einen echten normativen Widerspruch freigelegt:

- `concept/technical-design/45_phase_runner_cli.md:329-355` **verbietet Agents
  jeden direkten CLI-Aufruf.**
- `concept/technical-design/43_skills_system_task_automation.md:466-470` und der
  Record `2026-08-04-installationsisolation.md:168-172` **setzen agentische
  `run-phase`-Aufrufe ueber den Wrapper als produktiv voraus.**
- `concept/technical-design/21_story_creation_pipeline.md:829-839` steht mit
  `export-story-md` im selben Konflikt.

Zwei normative Owner sagen Gegenteiliges darueber, **ob ein Agent die CLI
ueberhaupt aufrufen darf**. Das ist keine Formulierungsfrage: Es entscheidet,
ob der Weg Agent → CLI ein vorgesehener Betriebspfad ist oder ein Verstoss.

Dem PO vorgelegt am 2026-08-05, Antwort offen. **Solange sie offen ist, darf
keine der beiden Seiten stillschweigend umgeschrieben werden** — wer hier eine
Seite „konsistent macht", trifft die Entscheidung heimlich.

## Akzeptanzkriterien

1. **Je Wert aus B1-B3 genau ein Eigentuemer**, benannt und an allen anderen
   Stellen referenziert statt wiederholt. Belegt durch Locator-Liste vorher /
   nachher.
2. **Der maschinelle Schutz findet den FK-50-Drift** — nachgewiesen dadurch,
   dass er ihn vor der Behebung meldet und danach schweigt.
3. **Der Schutz erfasst den gesamten Korpus** (`concept/**`, `guardrails/**`)
   und erkennt semantische Versionswerte unabhaengig von Backticks. Negativtest
   je Auspraegung.
4. **Der Floor fuer `lookup-userstory-core` ist begruendet oder entfernt.**
   Keine dritte Option.
5. **Der PO-Widerspruch ist unveraendert** und in beiden Richtungen sichtbar
   geblieben. Ein Test oder Gate-Befund, der ihn sichtbar haelt, ist zulaessig;
   eine Aufloesung ist es nicht.
6. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §SINGLE SOURCE OF TRUTH IST PFLICHT
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — doppelte Autoritaet ist das
  Modell, der Drift nur ihr Symptom
- `CLAUDE.md` §ZERO DEBT RULE — „Der Fehler vermehrt sich ueber Abhaengigkeiten"
