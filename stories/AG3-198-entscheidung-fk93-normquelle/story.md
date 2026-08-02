# AG3-198 — Entscheidungs-Story: Darf ein Nachschlagekatalog Normquelle sein?

- **Typ:** concept (Entscheidungs-Story)
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: ["AG3-179"]`; entblockt AG3-199
- **Quell-Konzept:** FK-93 §93.0 / §93.0.1 / §93.5a / §93.9a,
  `concept/_meta/assertion-authority.md`
- **Herkunft:** Befund vom 2026-08-02. Ausgezogen aus AG3-184 am 2026-08-02
  nach unabhaengigem Codex-Review (Auflage ERROR-12 und der WARNING zur
  §93.9a-Konfigurierbarkeit).

> **Diese Story entscheidet nichts.** Sie legt zwei Fragen entscheidungsreif
> vor und haelt das Ergebnis normativ fest. Das Agentenmandat aus `AGENTS.md`
> untersagt ausdruecklich, eine fehlende Grundentscheidung durch eine gut
> formulierte Detailaussage zu ersetzen — und genau das ist an dieser Stelle
> schon einmal passiert.

## Kontext

### Befund — belegt, mit Locator

FK-93 (`concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`)
war als **reine Wiedergabe** definiert: jede Zeile gibt einen Wert wieder,
dessen Norm anderswo lebt. In AG3-179 Runde 3 (Befund R4) wurde jeder
Katalogwert gegen `concept/` geprueft. Ergebnis:

- **12 von 14 Abschnitten** sind echte Wiedergaben mit externem Wert-Anker.
- **Nicht verankert sind acht Werte**: fuenf in **§93.5a** (`request_ttl_s`,
  `pause_ttl_s`, `lease_ttl`, External-Prompt-Grace,
  `max_open_requests_per_run`) und drei in **§93.9a** (Mutex-/Klinken-TTL 600 s,
  Wartefrist, Wiederholungsfrist). Fuer die fuenf aus §93.5a existieren auch
  die zugehoerigen `permissions.*`-Konfigurationspfade **in keinem
  Konfigurationsmodell, nicht einmal in FK-03**.

Der Umsetzer hat FK-93 daraufhin fuer diese acht selbst zur Normquelle erklaert
(Decision Record `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.10:
„Der Wertekatalog darf Normquelle sein — aber nur benannt"). **Das unabhaengige
Review hat genau diesen Zug zurueckgewiesen**, weil er eine Grundentscheidung
ersetzt statt sie auszudetaillieren.

### Die Frage

**Darf ein Nachschlagekatalog jemals Quelle der Wahrheit sein?**

- Bei **„ja"** braucht es eine Regel *wann* — sonst wandert jeder heimatlose
  Wert dorthin, und der Katalog wird zur zweiten Wahrheit neben den
  Fachkonzepten. Genau das ist die Klasse Problem, gegen die AK3 als
  Gegenentwurf zu v2 gebaut ist.
- Bei **„nein"** muessen die acht Werte bei ihren besitzenden Dokumenten
  normiert werden — und das ist echte Arbeit an FK-03, FK-42, FK-55 und FK-78.

Beide Richtungen sind vertretbar. Was nicht vertretbar ist, ist die Frage
implizit im Vorbeigehen zu beantworten.

### Zweiter Gegenstand — die verwaiste Frage

Der Decision Record `2026-08-01-run-mutex-intent-bounded-wait.md` Abschnitt 5
(c) haelt fest:

> „Nur noch inhaltlich offen, nicht als Freigabe: ob die konkreten
> Sekundenwerte aus FK-93 §93.9a kuenftig konfigurierbar werden sollen — heute
> sind sie fest im Code, was der Katalog auch so ausweist."

Diese Frage hat seither **keinen Owner**. Sie gehoert hierher, weil sie
dieselbe Achse betrifft: was FK-93 fuehrt und in welcher Form. Bleibt sie
liegen, ist sie nach `CLAUDE.md` „SEVERITY-SEMANTIK" ein im Effekt ignorierter
Befund.

## Scope

### In Scope

- Beide Fragen entscheidungsreif aufbereiten: Kontext, Konsequenzen je
  Richtung, ehrliche Kosten, Empfehlung — als **offener Loesungsraum**.
- Das Einholen der PO-Entscheidung.
- Das Festhalten des Ergebnisses als Decision Record mit Betroffenheitsmatrix.

### Out of Scope

- **Die Umsetzung** — Normierung der acht Werte bei ihren Eigentuemern bzw. die
  maschinell pruefbare „wann"-Regel, sowie das `permissions.*`-Konfigurationsmodell:
  **AG3-199**.
- Die Referenz-Baseline — **AG3-184**.
- Keine Vorwegnahme des Ergebnisses in Detailtext.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/_meta/decisions/2026-XX-XX-katalog-als-normquelle.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md` §93.0/§93.0.1 | geaendert | nur soweit die Entscheidung reicht |
| `concept/_meta/assertion-authority.md` | geaendert | falls die Entscheidung die Autoritaetsordnung beruehrt |
| `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md` | geaendert | Abschnitt 5 (c) wird geschlossen oder auf die neue Entscheidung verwiesen |

## Akzeptanzkriterien

1. **Die Vorlage benennt den Konflikt woertlich**, mit Locatoren: FK-93 §93.0.1
   (Zeilenklassen „Wiedergabe" vs. „katalog-eigener Wert"), §93.5a und §93.9a
   als die acht betroffenen Werte, und Rand 2.10 des Decision Records vom
   2026-08-01 als die vom Review zurueckgewiesene Selbstermaechtigung.
2. **Beide Richtungen sind mit ehrlichen Kosten dargestellt.** Bei „ja" wird
   ausdruecklich die Gefahr benannt, dass der Katalog zur zweiten Wahrheit
   wird; bei „nein" der reale Aufwand bei FK-03/FK-42/FK-55/FK-78.
3. **Der Loesungsraum ist offen formuliert.** Genannte Varianten sind Beispiele
   im Raum, keine Auswahlliste.
4. **Die §93.9a-Konfigurierbarkeit ist als zweite Frage getrennt vorgelegt**,
   mit dem heutigen Zustand (fest im Code) und der Frage, wer die Werte dann
   besaesse.
5. **Die PO-Entscheidung liegt zu beiden Fragen vor** und ist mit Datum und
   Urheber im Decision Record festgehalten. Eine Entscheidung, die der Umsetzer
   selbst getroffen hat, erfuellt dieses Kriterium nicht — das ist der Fehler,
   der diese Story ausgeloest hat.
6. **Der normative Nachzug reicht genau so weit wie die Entscheidung.** Jede
   geaenderte normative Aussage steht in der Betroffenheitsmatrix. Die
   inhaltliche Umsetzung der Entscheidung bleibt AG3-199.
7. **Abschnitt 5 (c) des Records vom 2026-08-01 ist geschlossen oder
   nachvollziehbar auf diese Entscheidung verwiesen.** Er bleibt nicht als
   offener Punkt ohne Owner stehen.
8. **Alle deterministischen Konzept-Gates gruen**;
   `check_concept_decision_record.py` bestaetigt Record und Matrix.

## Definition of Done

- AC 1–8 erfuellt.
- AG3-179 ist `completed`, bevor diese Story startet (`depends_on`).
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`
  §93.0 (Aufnahmekriterium), §93.0.1 (Pflegeregel und Zeilenklassen),
  §93.5a, §93.9a
- `concept/_meta/assertion-authority.md` — Ownership- und Autoritaetsordnung
- `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md`
  Rand 2.10, Abschnitt 3, Abschnitt 5 (b)/(c)

## Guardrail-Referenzen

- `AGENTS.md` (Agentenmandat, PO-Ratifikation 2026-08-02) — Bedingung 1
  („benennbare Ankerstelle") ist fuer die acht Werte nachweislich nicht
  erfuellt; damit ist der PO zu holen.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — „Keine zweite operative
  Wahrheit neben dem definierten Modell aufbauen."
- `CLAUDE.md` „SEVERITY-SEMANTIK" — die §93.9a-Frage darf nicht liegen bleiben.
- `stories/README.md` §5 — Konzeptkonflikt: anhalten, melden, Entscheidung
  abwarten.
