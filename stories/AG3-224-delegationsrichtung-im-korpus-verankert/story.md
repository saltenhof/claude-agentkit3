# AG3-224 — Der Korpus sagt überall dasselbe über die Delegationsrichtung

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []` — `unblocks: [AG3-225]`
- **Quell-Entscheid:** `concept/_meta/decisions/2026-08-05-delegationsrichtung-und-kontextschonung.md`
- **Herkunft:** PO-Entscheid vom 2026-08-05

## Kontext

Zwei normative Owner widersprachen sich darin, ob ein Agent die AK3-CLI
aufrufen darf: FK-45 `:352-355` verbietet es ausnahmslos, FK-43 `:470-472` und
FK-21 `:829-839` setzen genau solche Aufrufe in produktiven Skill-Bundles
voraus.

Der PO hat den Widerspruch **nicht durch Wahl einer Seite** aufgeloest, sondern
durch Korrektur einer Topologie-Annahme:

> Ein Agent ist **Harness + LLM**. Das LLM laeuft cloudseitig, der **Harness auf
> der Client-Maschine**. Das AK3-Backend ist **kein Agent** und hat **keine
> direkte Schnittstelle** zu den Harness-Installationen auf fremden Rechnern.
> **Project Edge ist das Relais** — in beide Richtungen.

Damit ist der Verstoss der Bundles kein Zugriffs-, sondern ein **Wegfehler**:
Der Agent wird ueber den Adapter des **Menschen** geschickt statt ueber den
Kanal, der fuer ihn existiert.

Der vollstaendige Entscheid mit Begruendung, Impact-Sweep und
Betroffenheitsmatrix steht im Decision Record. **Diese Story fuehrt ihn aus —
sie entscheidet nichts neu.**

## Scope

### In Scope

**Sechzehn** Dokumente. Die Betroffenheitsmatrix des Records ist maßgeblich —
sie wurde am 2026-08-05 korrigiert, nachdem der erste Impact-Sweep sich als
unvollständig erwies (er nannte sechs, es sind sechzehn, und FK-10 war
fälschlich als „nicht betroffen" geführt).

**FK-10 ist betroffen**: `:153-160` führt die Prozesslandschaft
`Orchestrator → Bash-Tool → CLI`, `:184-187` lässt Agenten CLI/Project-Edge
starten, und dem Diagramm `:118-169` fehlt die Rückdelegationskante.

**Sweep-Nachtrag, ebenfalls betroffen**: FK-02, FK-13, FK-15, FK-20, FK-26,
FK-28, FK-49, FK-68 sowie `concept/_meta/bc-cut-decisions.md` — jeweils
Aussagen zu Aufrufweg oder Kommandorichtung.

Die sechs ursprünglich benannten Dokumente mit ihrer jeweiligen Aussage:

| Dokument | Zu verankern |
|---|---|
| **FK-01** | §Kommandokanal: Qualifizierung nach Entscheid 2.6 — der Core initiiert nicht gegenueber einem *beliebigen* Rechner und hat weiterhin **keinen** Dateisystem-Zugriff, darf aber gegenueber einem durch vorherigen Pull **etablierten** Knoten initiieren, ausschliesslich ueber das Relais und nur fuer bewusst am Orchestrator vorbeigefuehrte Delegationen |
| **FK-45** | CLI-Regel `:352-355` bleibt **unveraendert gueltig**; ergaenzt wird die Gegenrichtung AK3 → Project Edge → Agent als vorgesehener Weg, samt Verhaeltnis zum Pull-Modell §45.1.1 |
| **FK-43** | Skill-Bundles weisen Agenten **nicht** zu Wrapper-Aufrufen an; wo ein Bundle den **menschlichen** Recovery-Pfad dokumentiert, ist das als solches kenntlich |
| **FK-21** | `export-story-md` analog |
| **FK-76** | Project Edge als Relais **beider** Richtungen |
| **FK-91** | Delegationsvertrag der Gegenrichtung |

Dazu:

- **Ein korpusweiter Sweep** ueber `concept/**` und `guardrails/**` nach
  weiteren Aussagen zu (a) Richtung des Kommandokanals, (b) Zulaessigkeit
  agentischer CLI-Aufrufe, (c) dem Weg, auf dem Arbeit den Harness erreicht.
  Die Matrix des Records ist **Stand der Erkenntnis, kein Beweis** — sie wurde
  schon einmal widerlegt. Findet der Sweep weitere Stellen, gehoeren sie dazu.
  **`concept/formal-spec/**` gehoert ausdruecklich zur Suchmenge**: Dort stehen
  Kommando-Signaturen, die einen Aufrufweg festschreiben, ohne den Akteur zu
  nennen — der erste Sweep hat genau diese Klasse uebersehen.
- **§2.4 des Entscheids — Kontextschonung als Zweck** — wird als Begruendung
  mitverankert, nicht nur die Regel. Ohne sie liest ein spaeterer Leser den
  Bypass als ueberfluessige zweite Kante und entfernt ihn.

### Out of Scope

- **Die Umstellung der Skill-Bundles** — das ist AG3-225.
- **Das Bauen fehlender Project-Edge-Aequivalente** — ebenfalls AG3-225, und
  dort erst nach Feststellung, welche fehlen.
- Jede inhaltliche Abweichung vom Decision Record. Erweist sich beim Verankern
  eine Entscheidung als undurchfuehrbar, ist das eine **Mandatsanfrage mit
  Beleg**, keine stille Anpassung.
- FK-30 (Hooks bleiben OS-Prozesse, unveraendert CLI-basiert) und FK-50
  (Operator-Pfad) — im Record als *nicht* betroffen ausgewiesen und von zwei
  unabhaengigen Reviews bestaetigt. Zeigt ein Sweep das Gegenteil, ist das ein
  Befund.

  **FK-10 stand hier urspruenglich ebenfalls und ist betroffen** (siehe In
  Scope). Die Fehleinordnung wurde am 2026-08-05 korrigiert; der Eintrag bleibt
  hier als Hinweis stehen, damit niemand die alte Aussage aus einer aelteren
  Fassung des Records uebernimmt.

## Akzeptanzkriterien

1. **Alle sechzehn in der Betroffenheitsmatrix ausgewiesenen Dokumente tragen
   die Aussage.** Beleg: Locator je Dokument, vorher/nachher. Die Zahl in der
   Matrix und die Zahl der belegten Dokumente muessen uebereinstimmen —
   stimmen sie nicht, ist die Matrix falsch und wird korrigiert, nicht der
   Nachweis geschoent.
2. **Der Korpus ist widerspruchsfrei.** Es existiert keine Stelle mehr, die
   agentische CLI-Aufrufe voraussetzt, und keine, die die Gegenrichtung
   ausschliesst. Nachgewiesen durch den Sweep **mit Methode** — Suchmuster,
   Dateimenge, Trefferzahl, Bewertung je Treffer. Eine Zusammenfassung ohne
   Methode zaehlt nicht.
3. **Der Sweep ist vollstaendig ueber `concept/**` und `guardrails/**`** und
   nennt ausdruecklich, welche Treffer **keine** Aenderung brauchten und warum.
4. **FK-01 verliert seine Schutzwirkung nicht.** Nach der Aenderung gilt
   weiterhin: kein Dateisystem-Zugriff auf den Entwicklerrechner, keine
   Initiative gegenueber einem nicht etablierten Knoten. Nachgewiesen durch die
   gegenuebergestellten Formulierungen.
5. **Die Begruendung ist mitverankert**, nicht nur die Regel — konkret der
   Zweck aus Entscheid §2.4 (Kontextschonung des Orchestrators).
6. **Jede Aussage hat genau einen Eigentuemer.** Kein Dokument wiederholt die
   normative Aussage eines anderen; Verweise statt Kopien. (Dies ist dieselbe
   Disziplin wie AG3-220 und verhindert genau den Drift, den diese Story
   gerade behebt.)
7. Alle deterministischen Konzept-Gates gruen: `check_concept_frontmatter`,
   `check_concept_reference_integrity`, `check_concept_code_contracts`,
   `check_concept_decision_record`, `compile_formal_specs`,
   `check_architecture_conformance`.
8. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-8 erfuellt, jedes mit benanntem Beleg (Locator, Kommando, Ausgabe).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md` — mit
  **ausdruecklicher Pruefung auf Vollstaendigkeit**: nicht nur „ist das
  Verankerte richtig", sondern „ist es **ueberall** verankert, wo es hingehoert".

## Guardrail-Referenzen

- `CLAUDE.md` §Konzepttreue ist Pflicht
- `CLAUDE.md` §SINGLE SOURCE OF TRUTH IST PFLICHT — AC 6
- `CLAUDE.md` §ZERO DEBT RULE — „Ein Fehler wird gefunden. Ein Entwurf wird
  erweitert." Ein halb verankerter Entscheid sieht aus wie Absicht.
