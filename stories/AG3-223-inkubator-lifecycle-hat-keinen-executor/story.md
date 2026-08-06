# AG3-223 — Ein Verfahren, das geprüft, aber nicht gefahren werden kann

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-78 §78.4 (Lauf-Lifecycle, `RUN.json`,
  Schreibprotokoll), §78.6 (Runden-Mechanik), §78.14 (deploybare
  Concept-Toolchain), `formal.concept-incubation.state-machine`,
  `formal.concept-incubation.commands`
- **Herkunft:** erster Versuch, einen Council-Lauf zu fahren, 2026-08-05

## Befund — belegt, mit Locator

Beim Versuch, Runde 1 des Laufs
`2026-08-05-review-vertrag-terminierung-085702c0` zu versiegeln und Runde 2 zu
beauftragen, hielt der beauftragte Agent an — korrekt, nach Eskalationsweg,
statt die Uebergaenge von Hand nachzubauen.

| Stelle | Aussage |
|---|---|
| `formal-spec/concept-incubation/commands.md:15` | Alle mutierenden Commands verlangen Lease und CAS-Schreibprotokoll |
| `commands.md:51`, `:59` | `dispatch-round` und `seal-round` sind solche Commands, zulaessig nur in `PROPOSING` |
| `.../concept_toolchain/semantic_gate.py:195` | Die mutierende Toolchain bietet ausschliesslich `units`, `prepare`, `import` |

**Es existiert kein `dispatch_round`, kein `seal_round` und kein allgemeiner
CAS-gesicherter `RUN.json`-Uebergang.** Der Inkubator ist pruefbar
(`incubator_check.py`), aber nicht fahrbar: Der Checker validiert einen
Zustand, den nichts herstellen kann.

### Der bestaetigende Nebenbefund

Die beiden aelteren Laeufe unter `concept-incubator/runs/` besitzen
**ueberhaupt keine `RUN.json`**. Sie stammen aus der Zeit vor dem Schema — der
Gruendungslauf hat das Schema ja erst hervorgebracht.

Daraus folgt die eigentliche Feststellung: **Kein Lauf ist je durch diese
Zustandsmaschine gegangen.** Das Verfahren ist vollstaendig beschrieben,
formal spezifiziert, mit Gate-Mapping und Schreibprotokoll versehen — und nie
ausgefuehrt worden.

## Warum das die schwerste Auspraegung eines bekannten Musters ist

FK-78 §78.14 sagt eine **deploybare Concept-Toolchain** zu. Gebaut ist die
pruefende Haelfte. Die ausfuehrende fehlt.

Das ist dasselbe Muster, das am 2026-08-05 in mehreren Storys auftrat — die
Zusage ist gebaut, ein realer Weg laeuft daran vorbei — hier aber auf der
Verfahrensebene: **Das Werkzeug, mit dem AK3 seine eigenen
Konzeptentscheidungen trifft, kann seinen eigenen Vertrag nicht einhalten.**

Die Folgen sind konkret und heute eingetreten:

- Ein Council-Lauf bleibt in `STAFFING` stehen, obwohl beide Proposals
  vorliegen; `current_round` bleibt `0`, waehrend Runde 1 faktisch gelaufen ist.
- Runde 2 kann nicht beauftragt werden, ohne Runde 1 zu zerstoeren: Der Vertrag
  kennt genau einen Schreibort je Worker (`outbox/proposal.md`), und die
  Versiegelung nach `rounds/r1/`, die ihn freigeben wuerde, ist der fehlende
  Command.
- Wer den Lauf trotzdem weiterfuehren will, muss **wissentlich von FK-78
  abweichen**. Genau das ist am 2026-08-05 geschehen und im Journal des Laufs
  vermerkt.

## Scope

### In Scope

- Ein **Executor fuer den Lauf-Lifecycle**: die in
  `formal.concept-incubation.commands` normierten mutierenden Commands,
  mindestens `dispatch-round` und `seal-round`, sowie der allgemeine
  CAS-gesicherte `RUN.json`-Uebergang nach FK-78 §78.4 (Mutations-Mutex mit
  `O_CREAT|O_EXCL`, Lease- und Fencing-Token-Verifikation innerhalb des Mutex,
  atomarer Replace-Write mit `state_revision + 1`).
- Durchsetzung der Zustandsmaschine: ein Command, der in seinem Zustand nicht
  zulaessig ist, wird abgewiesen — nicht ausgefuehrt.
- Die Uebergaenge, die der heutige Lauf braucht: `STAFFING → PROPOSING`,
  `PROPOSING → CONVERGING`, `CONVERGING → PROPOSING`.

### Out of Scope

- Aenderungen an der Norm, um sie der Implementierung anzupassen. Wo FK-78
  etwas verlangt, das sich als undurchfuehrbar erweist, ist das eine
  **Mandatsanfrage mit Beleg**, keine stille Absenkung.
- `incubator_check.py` — der prueft korrekt; ihm fehlt nichts.
- Der LIGHT-Baseline-Vertrag — das ist **AG3-222**, unabhaengig behebbar.
- Der Inhalt laufender Council-Laeufe.

## Akzeptanzkriterien

1. **Der real existierende Lauf `2026-08-05-review-vertrag-terminierung-085702c0`
   laesst sich durch die Zustandsmaschine fahren** — Runde 1 versiegeln, Runde 2
   beauftragen — ohne manuelle Dateimanipulation. Beleg: echte Kommandoausgabe
   und der resultierende `RUN.json`-Verlauf. Nicht an einem Testlauf, sondern an
   diesem.
2. **Byte-Treue der Versiegelung.** Die versiegelten Proposals sind identisch
   mit den Originalen. Bekannte Digests zur Verifikation:
   `worker-a` = `d9d6664b2b47d50996d84f1f2f4b926181abad06ecf42b634c03d4521f65734f`,
   `worker-b` = `05d0ff754878e0a7bdfd1af8f5efae28f3244402c36d8a3f32c90c4c8600efc8`.
3. **Unzulaessige Uebergaenge werden abgewiesen.** Negativtest je Fall: Command
   im falschen Zustand, fehlende Lease, veraltetes Fencing-Token, veraltete
   `state_revision`.
4. **Das Schreibprotokoll ist echt.** Nachgewiesen durch einen Test, der zwei
   konkurrierende Schreiber ansetzt und beweist, dass genau einer durchkommt und
   der andere abbricht — nicht durch Inspektion des Codes.
5. **`incubator_check.py` bleibt gruen** fuer den gefahrenen Lauf (abgesehen vom
   bekannten AG3-222-`INCOMPLETE`, solange jene Story offen ist).
6. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — „Keine halbfertigen Architekturuebergaenge"
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM
- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 1 verlangt
  ausdruecklich den realen Lauf, nicht einen konstruierten
