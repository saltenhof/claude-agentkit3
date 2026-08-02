# AG3-192 — Restliche produktive Aliase und Compat-Pfade entfernen

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-193
- **Quell-Konzept:** FK-11 (Multi-LLM-Hub), FK-30 (Governance/Disown), FK-13
  (VectorDB-Pflicht), FK-44 (Prompt-Runtime)
- **Herkunft:** PO-Grundregel vom 2026-08-02 (`CLAUDE.md`). Neu geschnitten am
  2026-08-02 nach unabhaengigem Codex-Review (Auflage ERROR-9): das Inventar
  war unvollstaendig und die Erledigungsform zu weich.

## Kontext

### Befund — belegt, mit Locator

Nach Commit `01a27de1` verbleiben produktive Konstrukte, die einen zweiten Weg
zum selben Ziel offenhalten. Der Schnitt vom 2026-08-02 nannte davon nur einen
Teil; **namentlich gefehlt haben mindestens die ersten beiden Zeilen dieser
Tabelle:**

| Locator | Was | Wortlaut / Wirkung |
|---|---|---|
| `backend/prompt_runtime/selectors.py:33-34` | `mode` als Parameter von `select_template_name` | „Legacy alias for `execution_route`; kept for compatibility." |
| `integration_clients/multi_llm_hub/client.py:426` | Fallback auf den alten Hub-Fehlervertrag | „Backward-compatible: unknown/missing `error_code` falls back to …" |
| `backend/governance/runner.py:461` | Legacy-Tombstone-Dualwrite | „Legacy backend-local tombstone (non-worktree consumers, backward compat)." — zweite Schreibwahrheit neben dem Edge-Bundle |
| `backend/governance/runner.py:366` | `_purge_edge_bundles`-Compat-Pfad | haengt am `DeactivationResult`-Kontrakt |
| `backend/verify_system/llm_evaluator/llm_client.py:269` | `set_eval_deadline` | einziger produktiver Konsument ist die Testsuite (`tests/unit/verify_system/llm_evaluator/test_ag3065_remediation_2.py:389-408`) |
| `backend/installer/checkpoint_engine/reasons.py:43-46` | „deprecated migration flag" fuer VectorDB | die Pflicht-Infrastruktur laesst sich per Altschluessel abschalten |
| `backend/installer/runner.py:393` | derselbe Altschluessel im Runner | „VectorDB is mandatory and absence of its deprecated migration key means …" |

Der Hub-Fehlervertrag-Fallback ist die gefaehrlichste Zeile der Liste: ein
unbekannter oder fehlender `error_code` faellt auf die alte Zuordnung zurueck.
Aendert der Hub sein Vokabular, wird die Aenderung nicht als Fehler sichtbar —
sie wird still in die alte Kategorie einsortiert. Das ist exakt die Bauart, die
`CLAUDE.md` unter „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" beschreibt.

### Warum eine reine Wortsuche nicht genuegt

Eine repo-weite Suche nach `deprecated`, `legacy`, `compat` trifft heute
mehrere Dutzend Stellen, von denen viele **Prosa** sind — etwa
`weaviate_adapter.py:1111-1237`, wo „LEGACY surface" die Bezeichnung einer
**fremden** Client-API ist und nicht ein AK3-eigener Altpfad. Die Zahl der
Treffer sagt nichts; die Bewertung jeder einzelnen Stelle ist das Ergebnis.

## Scope

### In Scope

- Erledigung **jeder** Zeile der Tabelle oben.
- Eine vollstaendige, bewertete Inventur aller uebrigen Treffer in `src/`.
- Konzeptnachzug, wo ein entfernter Name normativ erwaehnt war.

### Out of Scope

- Das Flow-/Node-Vokabular — **AG3-182**.
- Die QA-/Policy-Fallbacks im `verify_system` — **AG3-191**.
- Das Gate gegen den Rueckfall — **AG3-193**.
- **Keine Umbenennung aus Geschmacksgruenden.** Ein schlecht gewaehlter, aber
  **einziger** Name ist kein Fall fuer diese Story.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/prompt_runtime/selectors.py` | geaendert | `mode`-Alias entfernen; Aufrufer auf `execution_route` |
| `src/agentkit/integration_clients/multi_llm_hub/client.py` | geaendert | unbekannter `error_code` ist fail-closed, kein Rueckfall |
| `src/agentkit/backend/governance/runner.py` | geaendert | Tombstone-Dualwrite und `_purge_edge_bundles`-Compat-Pfad |
| `src/agentkit/backend/verify_system/llm_evaluator/llm_client.py` | geaendert | `set_eval_deadline` entfernen |
| `src/agentkit/backend/installer/checkpoint_engine/reasons.py` | geaendert | deprecated Migrations-Key |
| `src/agentkit/backend/installer/runner.py` | geaendert | derselbe Key im Runner |
| `tests/**` | geaendert | Tests, die einen Altpfad festschreiben, werden korrigiert oder entfernt |
| `concept/**` | geaendert | Konzeptnachzug, wo ein entfernter Name normativ erwaehnt war |
| `concept/_meta/decisions/2026-XX-XX-restliche-compat-pfade.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Jede Zeile der Tabelle oben ist erledigt** — entfernt, oder mit einer
   **fachlichen** Begruendung als *kein* Kompatibilitaetskonstrukt ausgewiesen.
   „Zu aufwaendig" ist keine Begruendung. Stellen, deren eigener Docstring sie
   „legacy alias", „deprecated" oder „backward compatible" nennt, sind nur durch
   **Entfernung oder Verhaltensaenderung** erledigt, nie durch eine Notiz, die
   den Docstring stehen laesst.
2. **Der Hub-Fehlervertrag ist fail-closed.** Ein unbekannter oder fehlender
   `error_code` erzeugt einen benannten Fehler, keine Einsortierung in die alte
   Kategorie. Nachgewiesen durch einen Negativpfad-Test mit einem
   Fantasie-`error_code`.
3. **Die VectorDB-Pflicht laesst sich nicht mehr per Altschluessel abschalten.**
   Ein Projekt, das den deprecated Migrations-Key setzt, wird abgewiesen; die
   Meldung nennt den Grund. Der Key ist danach kein akzeptierter Eingabewert
   mehr.
4. **Eine repo-weite Suche nach `deprecated`, `compat alias`,
   `backward-compat`, `legacy` in `src/` weist am Ende JEDEN verbleibenden
   Treffer namentlich aus**, mit Begruendung, warum er kein
   Kompatibilitaetskonstrukt ist. Die Liste liegt im Story-Record — sie ist das
   Ergebnis, nicht die Zahl. Fuer jeden Treffer steht dabei, ob er (a) AK3-eigene
   Altlast, (b) Bezeichnung einer **fremden** API oder (c) reine Prosa ist.
5. **Kein `NOSONAR`, kein Rule-Exclude, kein unerklaertes `noqa`/`type: ignore`
   bleibt zurueck**, das eine Kompatibilitaetsschicht verdeckt. Am 2026-08-02
   fanden sich zwei `NOSONAR`, die genau das taten.
6. **Tests, die einen Altpfad festschreiben, sind korrigiert oder entfernt** —
   nicht ergaenzt. Insbesondere die `set_eval_deadline`-Tests: ein Konstrukt,
   dessen einzige Konsumenten Tests sind, wird mit ihnen entfernt.
7. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`, alle deterministischen Konzept-Gates gruen. Konzept nachgezogen,
   wo ein entfernter Name normativ erwaehnt war.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die Inventurliste aus AC 4 liegt vollstaendig im Story-Record.
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.1 —
  VektorDB ist Pflicht-Basis, kein Extra
- `concept/technical-design/44_prompt_bundles_materialization_audit.md` —
  Prompt-Runtime und Template-Auswahl
- `concept/technical-design/30_hook_adapter_guard_enforcement.md` §30.6.0 —
  Tombstone-Vertrag, `tombstone_worktree_roots`
- `concept/technical-design/11_llm_provider_browser_pools_prompt_execution.md`
  §11.6.1 — Hub-Fehlervertrag

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS".
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 2.
- `CLAUDE.md` „FAIL-CLOSED" — AC 2 und AC 3.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 5.
