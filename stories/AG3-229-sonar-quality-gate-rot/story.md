# AG3-229 — Der Quality Gate ist die letzte rote Stufe

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** keine
- **Herkunft:** Jenkins #1246 gegen `41c78975`, 2026-08-06

## Lage

Der Build ist `FAILURE` bei **null Testfehlschlaegen**:

```
11.637 Tests, 0 failed, 61 skipped
Coverage 90,69 %  (Schwelle 85)
alle sechs deterministischen Konzept-Gates gruen
Referenzintegritaet 0 errors
                                          -> und trotzdem FAILURE
sonar quality gate status: ERROR
```

Beide Teststufen sind zum ersten Mal seit dem 5. August vollstaendig
durchgelaufen. Es scheitert ausschliesslich der Quality Gate, an zwei
Bedingungen:

| Bedingung | Stand | Schwelle |
|---|---|---|
| `new_critical_violations` | **18** | 0 |
| `new_violations` | **28** | 0 |
| `new_coverage` | 89,8 % | ≥ 80 — OK |
| `new_duplicated_lines_density` | 0,34 % | ≤ 3 — OK |
| `new_security_hotspots_reviewed` | 100 % | 100 — OK |

## Das vollstaendige Universum — 28 Befunde

### Blocker (1)

| Datei:Zeile | Regel | Befund |
|---|---|---|
| `backend/cli/auth_commands.py:274` | `S3516` | Methode liefert immer denselben Wert |

### Kritisch (18)

| Datei:Zeile | Regel | Befund |
|---|---|---|
| `backend/installer/mcp_registration.py:624` | `S3776` | Cognitive Complexity **32** → 15 |
| `backend/installer/upgrade/engine.py:356` | `S3776` | Cognitive Complexity 24 → 15 |
| `backend/control_plane_http/app.py:1686` | `S3776` | Cognitive Complexity 19 → 15 |
| `backend/installer/mcp_conformance/process.py:80` | `S3776` | Cognitive Complexity 19 → 15 |
| `backend/control_plane/startup_reconcile.py:141` | `S3776` | Cognitive Complexity 18 → 15 |
| `harness_client/harness_adapters/codex_config_toml.py:756` | `S3776` | Cognitive Complexity 18 → 15 |
| `backend/auth/middleware.py:93` | `S3776` | Cognitive Complexity 17 → 15 |
| `backend/story_exit/service.py:491` | `S3776` | Cognitive Complexity 17 → 15 |
| `backend/installer/runner.py:1520` | `S3776` | Cognitive Complexity 16 → 15 |
| `backend/control_plane_http/app.py` | `PY_FILE_MAX_LOC_1200` | **1383 LOC**, max 1200 |
| `backend/state_backend/postgres_store/_control_plane_rows.py` | `PY_FILE_MAX_LOC_1200` | **1230 LOC**, max 1200 |
| `backend/cli/story_commands.py:69,75,77,78,272` | `S1192` | 5× dupliziertes Literal (je 3×) |
| `backend/control_plane_http/installer_writer_routes.py:309` | `S1192` | `"type[_RouteRequest]"` 6× |
| `__init__.py:21` | `S1192` | `"__init__.py"` 3× |

### Major (8) und Minor (1)

| Datei:Zeile | Regel | Befund |
|---|---|---|
| `backend/control_plane_http/app.py:1` | `PY_MODULE_TOP_LEVEL_MAX_LOC_100` | 124 LOC Modulebene |
| `backend/control_plane/repository.py:1` | `PY_MODULE_TOP_LEVEL_MAX_LOC_100` | 105 LOC Modulebene |
| `backend/installer/upgrade/engine.py:484` | `S3358` | verschachtelter Bedingungsausdruck |
| `backend/installer/mutation_idempotency.py:40` | `S6796` | generischer Typparameter statt `TypeVar` |
| `backend/failure_corpus/mutation_idempotency.py:52` | `S6796` | dito |
| `backend/auth/http/routes.py:392` | `S1110` | ueberfluessige Klammern |
| `backend/cli/auth_commands.py:291` | `S1110` | ueberfluessige Klammern |
| `backend/installer/bootstrap_checkpoints/cp10_mcp_registration.py:394` | `S1110` | ueberfluessige Klammern |
| `__init__.py:48` | `S5713` | redundante Exception-Klasse in `except` |

## Warum das eine eigene Story ist

Die Befunde stammen ueberwiegend aus dem Sammelcommit `3fd866e2`, der den seit
AG3-179 ungeteilt gewachsenen Arbeitsbaum auf einmal gelandet hat — 366
Dateien. Sie liegen damit quer ueber die Arbeit von AG3-189, 214, 218, 219, 224
und 226 und gehoeren keiner davon allein.

**Das Universum ist vor Arbeitsbeginn vollstaendig aufgezaehlt.** Das ist der
ausdrueckliche Unterschied zu AG3-189, wo eine nie aufgezaehlte Menge 22
Reviewrunden gekostet hat. Kommt waehrend der Arbeit ein 29. Befund dazu, wird
er **gemeldet**, nicht stillschweigend mitgenommen.

## Scope

### In Scope

- Alle 28 Befunde an der Wurzel behoben.
- Die beiden `PY_FILE_MAX_LOC_1200`-Faelle verlangen einen **Schnitt entlang
  fachlicher Grenzen**, nicht entlang der Zeilenzahl. Ein Modul auf 1199 Zeilen
  zu druecken, indem man einen beliebigen Block auslagert, erfuellt die Regel
  und verfehlt ihren Zweck.

### Out of Scope

- Regeln abschalten, Schwellen anheben, `# NOSONAR` setzen, Befunde als
  „Won't fix" markieren. `CLAUDE.md` §NO ERROR BYPASSING: Bei Lint-, Typ- oder
  Guard-Fehlern wird die Ursache behoben.
- Verhaltensaenderungen. Dies ist eine Struktur-, keine Fachaenderung.
- Der bekannte `C901` in `scripts/ci/check_concept_frontmatter.py:566` — er
  gehoert **AG3-218**.

## Akzeptanzkriterien

1. **Der Quality Gate ist gruen**, nachgewiesen an einem Jenkins-Lauf gegen
   einen echten Kandidaten-SHA. Nicht an einer lokalen Sonar-Abfrage.
2. **Kein Befund wurde unterdrueckt.** Weder `# NOSONAR`, noch geaenderte
   Schwellen, noch „Won't fix"/„False positive" ohne fachliche Begruendung. Wo
   ein Befund tatsaechlich falsch positiv ist, wird das **begruendet** und der
   Grund im Code sichtbar gemacht.
3. **Keine Verhaltensaenderung.** Die volle Suite bleibt gruen (Jenkins), und je
   refaktorierter Funktion ist zu sagen, warum die Zerlegung dasselbe tut.
   Besondere Vorsicht bei `mcp_registration.py:624` (Komplexitaet 32) — das ist
   der Eigentums-/Registrierungspfad, den AG3-189 ueber 23 Runden abgesichert
   hat. **Die vier Zusagen dort duerfen nicht schwaecher werden:** fremder
   Interpreter, fehlender Snapshot-Owner, Symlink-Vorfahr und Junction
   bekommen keine Loeschautoritaet.
4. **Die beiden Dateischnitte folgen fachlichen Grenzen** und respektieren den
   BC-Schnitt sowie `check_architecture_conformance.py`. Der Schnitt ist zu
   begruenden, nicht nur vorzunehmen.
5. Coverage haelt die 85-%-Schwelle; `new_coverage` bleibt ueber 80 %.
6. `ruff` clean bis auf den AG3-218-`C901`; `mypy --strict` fuer `win32`,
   `linux`, `darwin`; alle sechs deterministischen Konzept-Gates gruen;
   `check_interpreter_entrypoints.py` OK.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg.
- Ein 29. Befund, falls er auftaucht, ist gemeldet und nicht stillschweigend
  mitgenommen.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §NO ERROR BYPASSING — AC 2
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — AC 4
- `CLAUDE.md` §ZERO DEBT RULE — keine Restlueckenz
