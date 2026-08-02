# AG3-199 — FK-93-Eigentumsentscheidung umsetzen

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-198"]`
- **Quell-Konzept:** FK-93, FK-03 (Konfigurationsmodell), FK-42, FK-55, FK-78
- **Herkunft:** Befund vom 2026-08-02 (AG3-179 Runde 3, Befund R4). Ausgezogen
  aus AG3-184 am 2026-08-02 nach unabhaengigem Codex-Review (Auflage ERROR-12).

## Kontext

### Befund — belegt, mit Locator

FK-93 fuehrt acht Werte ohne externen Eigentuemer. In AG3-179 Runde 3 ist jeder
Katalogwert gegen `concept/` geprueft worden; 12 von 14 Abschnitten sind echte
Wiedergaben. Nicht verankert:

| Abschnitt | Werte | Zusatzbefund |
|---|---|---|
| **§93.5a** | `request_ttl_s`, `pause_ttl_s`, `lease_ttl`, External-Prompt-Grace, `max_open_requests_per_run` | die zugehoerigen `permissions.*`-Konfigurationspfade existieren **in keinem Konfigurationsmodell, nicht einmal in FK-03** |
| **§93.9a** | Mutex-/Klinken-TTL 600 s, Wartefrist, Wiederholungsfrist | FK-78 fuehrt die **Regeln**, nennt aber keine Sekundenzahl |

Der Decision Record `2026-08-01-run-mutex-intent-bounded-wait.md` haelt zum
zweiten Punkt ausdruecklich fest: „Die fehlenden `permissions.*`-Pfade in FK-03
sind als offene Schuld BEIM OWNER benannt, nicht hier umgewidmet."

### Was diese Story tut

Sie setzt die Entscheidung aus **AG3-198** um — und nur die. Welche der beiden
Richtungen gilt, entscheidet der PO dort; diese Story kennt beide Faelle und
liefert fuer beide ein pruefbares Ergebnis.

## Scope

### In Scope

- **Fall „Katalog darf Normquelle sein":** die Regel *wann* ist ausgeschrieben
  **und maschinell pruefbar** implementiert.
- **Fall „nein":** die acht Werte sind bei ihren besitzenden Dokumenten
  normiert, FK-93 gibt sie nur noch wieder, und die `defers_to`-Kanten zeigen
  auf die tatsaechlichen Owner.
- In **beiden** Faellen: ein Konfigurationsmodell fuer die
  `permissions.*`-Pfade — oder ihre Entfernung als nicht existent.
- In **beiden** Faellen: die Umsetzung der §93.9a-Konfigurierbarkeitsentscheidung.

### Out of Scope

- Die Entscheidung selbst — **AG3-198**.
- Die Referenz-Baseline — **AG3-184**.
- `tools/` unter Lint/Typen — **AG3-197**.
- Keine Aenderung an den Zahlenwerten selbst; diese Story klaert **Eigentum und
  Ort**, nicht die Groesse.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md` | geaendert | §93.0.1, §93.5a, §93.9a, Frontmatter-Kanten |
| `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md` | geaendert | `permissions.*`-Pfade im Konfigurationsmodell |
| `concept/technical-design/42_ccag_tool_governance_permission_runtime.md` | geaendert | Normierung der §93.5a-Werte, falls dort ihr Owner liegt |
| `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md` | geaendert | dito |
| `concept/technical-design/78_concept_incubation_process.md` §78.4 | geaendert | Normierung der §93.9a-Werte, falls dort ihr Owner liegt |
| `src/agentkit/backend/**` (Konfigurationsmodelle) | geaendert | Pydantic-Modell fuer `permissions.*`; Konfigurierbarkeit der §93.9a-Werte je Entscheidung |
| `scripts/ci/` bzw. `tools/concept_governance/` | geaendert | maschinelle Pruefung der „wann"-Regel, falls Fall „ja" |
| `concept/_meta/decisions/2026-XX-XX-fk93-eigentum-umgesetzt.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/` | neu | je Fall ein Negativpfad |

## Akzeptanzkriterien

1. **Die Entscheidung aus AG3-198 ist umgesetzt, und zwar vollstaendig fuer
   alle acht Werte** — nicht fuer die bequemen fuenf. Der Story-Record fuehrt
   jeden der acht namentlich mit seinem Zielzustand.
2. **Fall „Katalog darf Normquelle sein": die Regel *wann* ist maschinell
   pruefbar.** Nachgewiesen daran, dass ein neu eingefuegter katalog-eigener
   Wert **ohne** erfuellte Bedingung das Gate rot macht. Eine Regel, die nur in
   Prosa steht, erfuellt dieses Kriterium nicht — sie ist genau die Form, die
   `konzept-konsistenz-governance.md` als „wo eine Regel existierte, las sie
   kein Werkzeug" beschreibt.
3. **Fall „nein": die acht Werte sind bei ihren Eigentuemern normiert**, und
   FK-93 gibt sie nur noch wieder. Nachgewiesen durch eine Pruefung, die fuer
   **jede** Katalogzeile den externen Wert-Anker aufloest und bei fehlendem
   Anker rot wird.
4. **Die `permissions.*`-Pfade haben ein Konfigurationsmodell oder sind als
   nicht existent entfernt.** Ein Konfigurationspfad, den kein Modell kennt,
   ist entweder Schuld oder eine Erfindung — beides wird benannt und aufgeloest.
   Ein Pfad, der weiterhin nur im Katalog steht, ist keine Erledigung.
5. **Die §93.9a-Konfigurierbarkeit ist umgesetzt wie entschieden.** Werden die
   drei Sekundenwerte konfigurierbar, haben sie ein Konfigurationsmodell,
   Standardwerte und einen benannten Eigentuemer; bleiben sie fest, sagt der
   Katalog das weiterhin so, und der Punkt ist im Record vom 2026-08-01
   geschlossen.
6. **Kein Wert wandert dabei stillschweigend.** Aendert sich eine Zahl,
   ist das ein eigener, begruendeter Eintrag in der Betroffenheitsmatrix —
   diese Story klaert Eigentum, nicht Groesse.
7. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; alle deterministischen Konzept-Gates gruen; Decision Record mit
   Betroffenheitsmatrix.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die Tabelle der acht Werte mit Zielzustand liegt im Story-Record.
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md`
  §93.0, §93.0.1, §93.5a, §93.9a
- `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md`
- `concept/technical-design/42_ccag_tool_governance_permission_runtime.md`
- `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md`
- `concept/technical-design/78_concept_incubation_process.md` §78.4
- `concept/_meta/assertion-authority.md`

## Guardrail-Referenzen

- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — keine zweite operative
  Wahrheit.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT".
- `CLAUDE.md` „ZERO DEBT RULE" — AC 1 und AC 4: keine stillen Restluecken.
- `AGENTS.md` (Agentenmandat) — diese Story fuehrt eine PO-Entscheidung aus;
  sie trifft keine.
