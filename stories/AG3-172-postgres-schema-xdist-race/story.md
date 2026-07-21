# AG3-172 — Bug: Postgres-Schema-/Katalog-Race unter xdist macht die Pflichtsuite nicht-deterministisch

- **Typ:** implementation
- **Groesse:** M
- **depends_on:** []
- **unblocks:** [AG3-164] — solange die Pflichtsuite nicht deterministisch
  ist, darf keine Story landen.
- **Quell-Konzept:** FK-21 (State-Backend, Schema-Verifikation) ·
  `guardrails/testing-guardrails.md`
- **Herkunft:** Aufgedeckt waehrend der Abnahme von AG3-164; diagnostiziert
  vom unabhaengigen Reviewer in
  `stories/AG3-164-are-mcp-phantom-registration/review-5-codex.md`
  (Vorrangbefund P0-1).

## Kontext / Problem

Bei der Abnahme von AG3-164 ergaben drei aufeinanderfolgende Laeufe von
`pytest tests/unit/installer tests/integration/installer` bei
**identischem Arbeitsbaum** drei verschiedene Ergebnisse:

| Lauf | Ergebnis |
|---|---|
| 1 | `1 failed, 505 passed` |
| 2 | `503 passed, 3 errors` |
| 3 | `506 passed` |

Der jeweils rote Test besteht isoliert. Die Vermutung, der neue
Prozessbaum-Teardown aus AG3-164 terminiere fremde Prozesse, hat sich
**nicht** bestaetigt.

**Diagnose (Reviewer, Seed `3250338151`):** Der Fehler entsteht in
`_verify_evidence_command_kind_present()` beim Aufruf von
`pg_get_constraintdef(c.oid)`:

```text
psycopg.errors.InternalError_: could not open relation with OID ...
```

Zwischen der Katalogabfrage, die die Constraint-OID ermittelt, und ihrer
Aufloesung verschwindet das Objekt — weil parallel ein anderer Test
Schemaobjekte im selben Katalog erzeugt oder verwirft. Das ist eine
klassische Katalog-Race: Eine OID ist kein stabiler Handle ueber
Anweisungsgrenzen hinweg.

**Reproduktion:**

```powershell
.venv\Scripts\python -m pytest -n 2 --dist loadfile `
  --randomly-seed=3250338151 `
  tests/integration/installer/test_third_party_backend_mediation.py `
  tests/integration/installer/test_upgrade_entry.py
```

Vier von acht identischen Wiederholungen scheitern. Ein serieller Lauf
mit zehn festen Seeds bleibt gruen.

**Warum das blockierend ist:** Eine Pflichtsuite, deren Ergebnis von der
Ausfuehrungsreihenfolge abhaengt, kann keine Aussage mehr treffen. Sie
erzeugt Rauschen, in dem echte Regressionen untergehen — und sie erzieht
dazu, rote Laeufe zu wiederholen statt zu untersuchen. Beides ist unter
FAIL-CLOSED und ZERO DEBT unzulaessig. Der Defekt ist Vorbestand; er wird
hier behoben, weil er aufgefallen ist, nicht weil AG3-164 ihn verursacht
haette.

## Scope

### In Scope

1. **Ursache beheben, nicht das Symptom.** Die Schemaverifikation darf
   nicht auf einer zwischen Anweisungen gehaltenen OID beruhen. Zulaessige
   Richtungen (die Wahl ist Teil der Umsetzung und zu begruenden):
   - Constraint-Definition und -Identitaet in **einer** Anweisung
     ermitteln, statt OID und Aufloesung zu trennen;
   - Katalogzugriffe in eine Transaktion mit geeigneter Isolation legen;
   - auf katalogstabile Sichten bzw. Namensaufloesung statt OIDs stuetzen.
2. **Testisolation pruefen:** Teilen sich parallele Worker eine Datenbank,
   ein Schema oder einen Suchpfad, obwohl sie es nicht duerften? Falls ja,
   ist die Isolation herzustellen — pro Worker ein eigenes Schema bzw. eine
   eigene Datenbank.
3. **Determinismus beweisen:** Der oben genannte Reproduktionsbefehl muss
   in mindestens **zwanzig** aufeinanderfolgenden Wiederholungen gruen
   sein, ebenso die vollstaendige Installer-Suite in mindestens **fuenf**
   Laeufen mit unterschiedlichen Seeds.
4. **Regressionstest:** Ein Test, der die Race gezielt provoziert
   (paralleler Katalogwechsel waehrend der Verifikation) und ohne den Fix
   rot ist.

### Out of Scope

- Aenderungen an AG3-164 (`mcp_conformance`, CP10) — der Defekt ist
  unabhaengig.
- Umbau der Teststrategie oder Abschalten der Parallelisierung.
  **Ausdruecklich unzulaessig:** `-p no:randomly`, Serialisierung der
  betroffenen Dateien oder ein Retry-Mechanismus als "Loesung". Das waere
  Symptomunterdrueckung.
- Funktionale Aenderungen am State-Backend ausserhalb der
  Schemaverifikation.

## Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/state_backend/postgres_store/_schema.py` | aendern — Katalogzugriff race-frei (Zeilen um :273-288, :330-404, :664-678) |
| `tests/fixtures/postgres_backend.py` | aendern — Worker-Isolation (Zeilen um :603-665) |
| `tests/integration/` | Regressionstest ergaenzen |

## Akzeptanzkriterien

1. Der Reproduktionsbefehl ist in zwanzig aufeinanderfolgenden
   Wiederholungen gruen.
2. Die vollstaendige Installer-Suite ist in fuenf Laeufen mit
   unterschiedlichen Seeds gruen — ohne Wiederholung roter Laeufe.
3. Ein Regressionstest provoziert die Race gezielt und ist ohne den Fix
   nachweislich rot.
4. Die Schemaverifikation haelt keine OID mehr ueber Anweisungsgrenzen
   hinweg; die gewaehlte Loesungsrichtung ist im Story-Bericht begruendet.
5. Parallele Worker teilen sich keinen Katalogzustand, den sie
   gegenseitig veraendern koennen — oder es ist begruendet, warum das
   unschaedlich ist.
6. Keine Unterdrueckung: keine Serialisierung, keine
   Retry-Mechanik, keine Deaktivierung der Zufallsreihenfolge.

## Definition of Done

- Alle Akzeptanzkriterien erfuellt.
- Voller `pytest` gruen, Coverage haelt 85 %; `mypy src` und
  `ruff check src tests` sauber.
- Story-Bericht dokumentiert Ursache, gewaehlte Loesungsrichtung und die
  Determinismus-Belege (Anzahl Laeufe, Seeds).

## Konzept-Referenzen

FK-21 (State-Backend, Schemaverifikation)

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM** — der Kern dieser Story. Ein
  Retry oder eine Serialisierung waere die Symptomvariante.
- **FAIL-CLOSED** — eine reihenfolgeabhaengige Pflichtsuite trifft keine
  Aussage mehr.
- **NO ERROR BYPASSING** · **ZERO DEBT** · **ARCH-55**
