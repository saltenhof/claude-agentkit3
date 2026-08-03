# AG3-199 — Die acht heimatlosen Werte bekommen Eigentuemer

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-179"]`
- **Quell-Konzept:** FK-93, FK-03 (Konfigurationsmodell), FK-42, FK-55, FK-78
- **Herkunft:** Befund vom 2026-08-02 (AG3-179 Runde 3, Befund R4). Ausgezogen
  aus AG3-184 nach unabhaengigem Codex-Review (Auflage ERROR-12). Am 2026-08-03
  hat diese Story die vormalige Entscheidungs-Story AG3-198 **aufgenommen**:
  die dort vorgelegte Frage ist keine, siehe unten.

## Kontext

### Befund — belegt, mit Locator

FK-93 (`concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`)
ist als **reine Wiedergabe** definiert: jede Zeile gibt einen Wert wieder,
dessen Norm anderswo lebt. In AG3-179 Runde 3 wurde jeder Katalogwert gegen
`concept/` geprueft. 12 von 14 Abschnitten sind echte Wiedergaben mit externem
Anker. **Acht Werte haben keinen:**

| Abschnitt | Werte | Zusatzbefund |
|---|---|---|
| **§93.5a** | `request_ttl_s`, `pause_ttl_s`, `lease_ttl`, External-Prompt-Grace, `max_open_requests_per_run` | die zugehoerigen `permissions.*`-Konfigurationspfade existieren **in keinem Konfigurationsmodell, nicht einmal in FK-03** |
| **§93.9a** | Mutex-/Klinken-TTL 600 s, Wartefrist, Wiederholungsfrist | FK-78 fuehrt die **Regeln**, nennt aber keine Sekundenzahl |

Der Umsetzer hat FK-93 daraufhin fuer diese acht selbst zur Normquelle erklaert
(Decision Record `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.10). Das
unabhaengige Review hat den Zug zurueckgewiesen.

### Warum es hier nichts mehr zu entscheiden gibt

Diese Story hiess bis zum 2026-08-03 „setzt die Entscheidung aus AG3-198 um".
Die Entscheidung existiert nicht — sie ist **ableitbar**, und der Product Owner
hat die Ableitung am 2026-08-02 gefuehrt:

Dass diese acht Werte keinen Eigentuemer haben, **ist eine Schuld**. Wer
anfaengt, das Register umzudeuten, umzubiegen oder still wegfallen zu lassen,
um mit der Schuld weiterarbeiten zu koennen, **macht sie zu seiner eigenen**.
Das gilt in beide Richtungen und ist an keiner harmlos: Der Katalog, der den
fehlenden Eigentuemer durch **eigene Autoritaet** ersetzt, behauptet etwas
Falsches. Der Katalog, der den heimatlosen Eintrag **stillschweigend weglaesst**,
ist unvollstaendig — und erfuellt damit die Funktion nicht mehr, fuer die er
existiert. Schulden sind nicht erlaubt. Damit bleibt genau ein zulaessiger Weg:
**den fehlenden Eigentuemer herstellen.**

Das ist nicht teurer. Jede Schuld wird transitiv bezahlt — an anderer Stelle,
zu einem spaeteren Zeitpunkt, von jemand anderem, mit Zinsen und Zinseszins.
Der Vergleich „heutiger Aufwand gegen heutigen Nutzen" ist genau der Fehler,
den `CLAUDE.md` §ZERO DEBT seit dem 2026-08-02 ausdruecklich benennt.

**Konsequenz fuer den Schnitt:** AG3-198 ist aufgeloest, ihr Inhalt liegt hier.
Es wird nicht auf eine PO-Entscheidung gewartet. Rand 2.10 des Records vom
2026-08-01 wird zurueckgezogen.

### Die zweite, echte Frage

Ob die drei Sekundenwerte aus §93.9a **konfigurierbar** werden sollen, ist
inhaltlich offen (Record vom 2026-08-01, Abschnitt 5 (c)) und hatte keinen
Owner. Sie bekommt hier einen. Sie ist **nicht** dieselbe Frage wie das
Eigentum: ein Wert kann einen Eigentuemer haben und trotzdem fest im Code
stehen. Der Default dieser Story ist **fest**, weil kein Anwendungsfall fuer
Konfigurierbarkeit vorliegt; wird das geaendert, ist es ein eigener Eintrag in
der Betroffenheitsmatrix mit benanntem Anlass.

## Scope

### In Scope

- Fuer **alle acht** Werte wird der Eigentuemer **hergestellt**: der Wert wird
  bei seinem besitzenden Fachkonzept normiert, FK-93 gibt ihn nur noch wieder,
  und die `defers_to`-Kante zeigt auf den tatsaechlichen Owner.
- Die drei §93.9a-Werte gehen nach **FK-78 §78.4** — der Owner existiert, nur
  die Zahl stand nie dort.
- Fuer die fuenf §93.5a-Werte ist der Owner zu **bestimmen** (Kandidaten:
  FK-03, FK-42, FK-55) und dort zu normieren.
- Ein **Konfigurationsmodell fuer die `permissions.*`-Pfade** — oder ihre
  Entfernung, falls sie erfunden sind.
- Der Rueckzug von Rand 2.10 des Records vom 2026-08-01.
- Eine Pruefung, die den Zustand haelt: jede Katalogzeile ohne aufloesbaren
  externen Anker macht das Gate rot.

### Out of Scope

- **Keine Aenderung der Zahlenwerte.** Diese Story klaert Eigentum und Ort,
  nicht Groesse. Aendert sich doch eine Zahl, ist das ein eigener, begruendeter
  Eintrag in der Betroffenheitsmatrix.
- Die Referenz-Baseline — **AG3-184**.
- `tools/` unter Lint/Typen — **AG3-197**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md` | geaendert | §93.0.1, §93.5a, §93.9a, Frontmatter-Kanten |
| `concept/technical-design/78_concept_incubation_process.md` §78.4 | geaendert | die drei Mutex-/Klinkenwerte werden hier normiert |
| `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md` | geaendert | `permissions.*`-Pfade im Konfigurationsmodell |
| `concept/technical-design/42_ccag_tool_governance_permission_runtime.md` | geaendert | Normierung der §93.5a-Werte, soweit dort ihr Owner liegt |
| `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md` | geaendert | dito |
| `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md` | geaendert | Rand 2.10 zurueckgezogen; Abschnitt 5 (c) geschlossen |
| `src/agentkit/backend/**` (Konfigurationsmodelle) | geaendert | Pydantic-Modell fuer `permissions.*` |
| `scripts/ci/` bzw. `tools/concept_governance/` | geaendert | Ankerpruefung je Katalogzeile |
| `concept/_meta/decisions/2026-XX-XX-fk93-eigentum-hergestellt.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/` | neu | Negativpfade (fehlender Anker, fehlendes Konfigurationsmodell) |

## Akzeptanzkriterien

1. **Alle acht Werte haben einen Eigentuemer — nicht die bequemen fuenf.** Der
   Story-Record fuehrt jeden namentlich mit Zielort und Fundstelle der neuen
   Norm.
2. **FK-93 ist wieder ausschliesslich Wiedergabe.** Keine Zeile traegt mehr
   katalog-eigene Autoritaet; Rand 2.10 des Records vom 2026-08-01 ist
   **zurueckgezogen**, nicht uminterpretiert.
3. **Der Zustand ist maschinell gehalten.** Eine Katalogzeile ohne aufloesbaren
   externen Wert-Anker macht ein Gate rot. Nachgewiesen an einer konstruierten
   ankerlosen Zeile, die rot macht und danach zurueckgenommen wird. Ohne diese
   Pruefung ist der Katalog beim naechsten heimatlosen Wert wieder da, wo er
   herkam.
4. **Die `permissions.*`-Pfade haben ein Konfigurationsmodell oder sind als
   nicht existent entfernt.** Ein Konfigurationspfad, den kein Modell kennt, ist
   entweder Schuld oder eine Erfindung — beides wird aufgeloest, nicht benannt
   und liegen gelassen. Ein Pfad, der weiterhin nur im Katalog steht, ist keine
   Erledigung.
5. **Die drei §93.9a-Werte stehen in FK-78 §78.4**, dort wo ihre Regeln schon
   stehen, und FK-93 verweist darauf.
6. **Die Konfigurierbarkeitsfrage ist geschlossen.** Bleibt es fest, sagt der
   Katalog das weiterhin so und Abschnitt 5 (c) ist geschlossen; wird sie
   geoeffnet, gibt es Modell, Standardwert und Eigentuemer.
7. **Kein Wert wandert stillschweigend.** Jede geaenderte Zahl ist ein eigener
   Eintrag in der Betroffenheitsmatrix mit Begruendung.
8. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; alle deterministischen Konzept-Gates gruen; Decision Record mit
   Betroffenheitsmatrix.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die Tabelle der acht Werte mit Zielort liegt im Story-Record.
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`
  §93.0, §93.0.1, §93.5a, §93.9a
- `concept/technical-design/78_concept_incubation_process.md` §78.4
- `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md`
- `concept/technical-design/42_ccag_tool_governance_permission_runtime.md`
- `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md`
- `concept/_meta/assertion-authority.md`
- `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md`
  Rand 2.10, Abschnitt 5 (c)

## Guardrail-Referenzen

- `CLAUDE.md` „ZERO DEBT RULE" inkl. Mitigationsklausel — die Herleitung, warum
  hier nichts zu entscheiden ist: Beruehren ist keine Uebernahme, mitigieren ist
  es. Zulaessig ist nur, den fehlenden Eigentuemer herzustellen.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — keine zweite operative Wahrheit
  neben dem definierten Modell.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT".
- `AGENTS.md` (Agentenmandat) — ein Agent darf normative Inhalte nur als
  Ausdetaillierung mit benennbarer Ankerstelle schaffen. Fuer die acht Werte
  fehlte die Ankerstelle; diese Story stellt sie her, statt sich selbst zur
  Autoritaet zu erklaeren.
