# AG3-225 — Bundles schicken Agenten nicht mehr über den Adapter des Menschen

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: [AG3-224]`
- **Quell-Entscheid:** `concept/_meta/decisions/2026-08-05-delegationsrichtung-und-kontextschonung.md`,
  Konsequenzen 1 und 2
- **Herkunft:** PO-Entscheid vom 2026-08-05

## Kontext

Produktiv bindbare Skill-Bundles weisen Agenten heute an, die AK3-CLI
aufzurufen — `{{AK3_WRAPPER}} run-phase` in `execute-userstory-core`
(FK-43 `:470-472`), `export-story-md` in `lookup-userstory-core`
(FK-43 `:477-481`, FK-21 `:829-839`).

Die CLI laeuft als lokaler Prozess unter den Zugangsdaten des **Operators**. Ein
Agent, der sie aufruft, handelt unter fremder Identitaet — genau die Trennung,
die AG3-214 („Ein Writer, ein Vertrag") gerade etabliert hat. Nach AG3-214
gehen mutierende CLI-Verben zwar ueber authentisiertes HTTPS an den Writer, das
Argument „der Agent umgeht die Control Plane" traegt also nicht mehr. **Das
Identitaetsargument traegt weiter.**

Der Weg, der fuer Agenten existiert, ist Project Edge — das Relais in beide
Richtungen.

## Die Inventur — Stand 2026-08-05, aus dem Review zu AG3-224

Der Bundle-Store enthaelt **64 Dateien** in **16 `SKILL.md`-Versionen**; der
Floor-Owner `src/agentkit/backend/skills/version_policy.py` benennt **fuenf**
Bundle-IDs. Von den derzeit floor-konformen Varianten tragen **drei**
CLI-/Wrapper-Bezuege:

| Bundle-Version | Betroffene Aufrufe |
|---|---|
| `create-userstory-core/4.2.0` | `concept validate`, `export-story-md` (`SKILL.md:790` ff.) — beides direkte Agentenanweisungen ueber `{{AK3_WRAPPER}}` |
| `execute-userstory-core/4.1.0` | `run-phase` |
| `lookup-userstory-core/4.1.0` | `export-story-md` |

**Die Zaehleinheit ist das Bundle/Kommando-Paar.** Es sind **drei
Kommandovertraege** (`run-phase`, `export-story-md`, `concept validate`) in
**vier Paaren** — `export-story-md` kommt in zwei Bundles vor und ist dort
je einzeln umzustellen und einzeln nachzuweisen.

**Diese Menge ist das eingefrorene Universum dieser Story.** Sie war vor
Arbeitsbeginn bestimmbar und ist bestimmt worden; sie waechst nicht waehrend
der Abarbeitung. Waechst sie doch, ist das ein Befund gegen die Inventur — und
loest eine Vorlage an den PO aus, keine stille Ausweitung.

## Der erwartete Stolperstein

Der Decision Record haelt in §7 ausdruecklich fest:

> Ob fuer **jede** heute im Bundle per CLI beauftragte Faehigkeit bereits ein
> Project-Edge-Aequivalent existiert, ist ungeprueft. Fehlt eines, ist es zu
> bauen (Konsequenz 2), **nicht zu umgehen**.

Das kann diese Story deutlich groesser machen als ihren Kern. Deshalb steht die
**Inventur am Anfang**, nicht am Ende: Erst wird die endliche Menge bestimmt,
dann wird umgestellt. Eine Story, deren Universum erst waehrend der Arbeit
entsteht, terminiert nicht — das ist die Lehre aus AG3-189.

**Ergibt die Inventur, dass wesentliche Aequivalente fehlen, ist das eine
Vorlage an den PO** ueber Umfang und Schnitt, keine stille Ausweitung.

## Scope

### In Scope

- **Inventur** aller produktiv bindbaren Skill-Bundles nach an den Agenten
  gerichteten CLI-Aufrufen. Ergebnis ist eine endliche, benannte Liste.
- **Umstellung** dieser Aufrufe auf den Project-Edge-Weg.
- **Kenntlichmachung** dort, wo ein Bundle bewusst den **menschlichen**
  Recovery-Pfad dokumentiert — solche Stellen bleiben, muessen aber als
  Menschenpfad erkennbar sein und duerfen nicht als Agentenanweisung lesbar
  sein.
- **Bundle-Unveraenderlichkeit respektieren**: Aenderungen laufen ueber neue
  Versionen plus Mindestversions-Floor beim Owner
  `src/agentkit/backend/skills/version_policy.py`, nie durch Aenderung
  veroeffentlichter Versionen.
- Fehlende Project-Edge-Aequivalente: **bauen** — fuer die drei
  Kommandovertraege des eingefrorenen Universums (`run-phase`,
  `export-story-md`, `concept validate`), nachgewiesen je Bundle/Kommando-Paar.
  Ergibt die Pruefung, dass fuer eines davon kein Aequivalent existiert und sein
  Bau eine eigene Fachentscheidung verlangt (neue Route, neues Datenmodell,
  neuer Vertrag), ist das eine **Vorlage an den PO** — und diese Story endet
  fuer dieses Verb dort. „Sofern der Umfang es zulaesst" ist keine Grenze und
  steht hier bewusst nicht mehr.

### Out of Scope

- Die Konzeptverankerung — das ist **AG3-224** und Voraussetzung.
- Hooks. Sie sind OS-Prozesse mit stdin/stdout-Pipes und bleiben unveraendert
  CLI-basiert (FK-45 `:348`, FK-30 §30.3.1).
- Operator-Pfade: `register-project`, `verify-project`, `reset-story`,
  `split-story`, `exit-story` und die uebrigen in FK-45 `:344-350` als
  unveraenderlich CLI-basiert ausgewiesenen Befehle. Sie sind Menschenpfade —
  die Frage ist nur, ob ein Bundle sie **einem Agenten** anweist.

## Akzeptanzkriterien

1. **Die Inventur liegt vor, bevor umgestellt wird.** Endliche Liste je
   produktiv bindbarem Bundle: welcher Aufruf, welche Zeile, an wen gerichtet
   (Agent oder Mensch), ob ein Project-Edge-Aequivalent existiert. Belegt mit
   Suchmethode, nicht als Zusammenfassung.
2. **Kein produktiv bindbares Bundle weist einen Agenten mehr zu einem
   CLI-Aufruf an.** Nachgewiesen durch einen deterministischen Check, der das
   feststellt — nicht durch Sichtpruefung. Der Check gehoert zum Lieferumfang.
3. **Menschliche Recovery-Pfade sind als solche kenntlich** und werden vom
   Check aus AC 2 nicht faelschlich beanstandet. Positivtest.
4. **Veroeffentlichte Bundle-Versionen sind byte-identisch geblieben.** Beleg:
   Digests vorher/nachher. Aenderungen liegen ausschliesslich in neuen
   Versionen; der Floor steht beim Owner `version_policy.py`.
5. **Jedes umgestellte Verb funktioniert ueber Project Edge.** Nachgewiesen je
   Verb, nicht pauschal. Ein belassener CLI-Aufruf heilt nichts.
   **Dieses Kriterium kennt keinen Erfuellungspfad ohne Funktionsaenderung**:
   Wird ein Verb aus dem Universum ausgenommen, weil sein Aequivalent eine
   eigene Fachentscheidung verlangt, ist AC 5 fuer dieses Verb **nicht
   erfuellt**, sondern **ausgesetzt** — mit PO-Vorlage, Locator und Datum. Der
   Unterschied ist wesentlich: Eine Vorlage an den PO ist ein Blocker-Ergebnis,
   kein Nachweis.
6. **Der Realitaetsnachweis**: Mindestens ein umgestelltes Verb laeuft
   nachweislich ueber den echten Project-Edge-Weg (`CLAUDE.md`
   §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — gruene Unit-Tests sind
   Voraussetzung, nie Nachweis).
7. Alle deterministischen Konzept-Gates gruen; `ruff` clean; `mypy --strict`
   fuer `win32`, `linux`, `darwin`; volle Suite gruen auf Jenkins.
8. Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1-8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FEHLENDES BESCHAFFEN STATT UMGEHEN — ein fehlendes
  Project-Edge-Aequivalent wird gebaut oder vorgelegt, nicht umgangen
- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 6
- `CLAUDE.md` §ZERO DEBT RULE
