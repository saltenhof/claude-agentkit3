# AG3-235 — Sieben Tests belegen etwas anderes als ihre Zusage

- **Typ:** bugfix
- **Groesse:** M
- **Abhaengigkeiten:** keine
- **Herkunft:** beauftragte Suche in AG3-214, 2026-08-06

## Anlass

Die drei Restbefunde von AG3-214 hatten alle dieselbe Form: **Ein Test steht
neben dem Fenster, das er absichern soll.** Die Anschlussfrage lautete, ob es
dabei bleibt.

Es bleibt nicht. **Sieben weitere Fundstellen**, alle am Locator nachgeprueft.

Die Klasse ist an einem einzigen Tag **achtmal** aufgetreten — dreimal in
AG3-214 selbst, einmal in AG3-229 (eine Fixture, die den Writer *imitierte*
statt ihn auszufuehren, und dabei behauptete, denselben Vertrag abzubilden),
und diese sieben.

## Der schwerste: ein Widerspruch im Testbestand

**#5 — `tests/unit/cli/test_main.py:557`** (`test_register_project_command`,
ueber die autouse-Fixture bei `:61`).

Der Docstring behauptet „REAL code, no monkeypatch crutch". Tatsaechlich ersetzt
die Fixture `_wire_register_config_to_writer` durch lokale
`StateBackend*Repository(root)`-Konstruktionen und assertiert dann **gegen
diese**.

Das ist **exakt der lokale Repository-Pfad, den AG3-214 entfernt hat** — und den
`tests/unit/concept_toolchain/test_ag3_214_single_writer_contract.py:164-173`
als **nicht existent** assertiert.

> Ein Testbestand, in dem ein Test die Abwesenheit eines Pfades beweist und ein
> anderer denselben Pfad benutzt, traegt keine der beiden Aussagen.

## Die uebrigen sechs

| # | Locator | Was behauptet wird / was gemessen wird |
|---|---|---|
| 1 | `tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py:75` | „parallel same op_id" — belegt durch **zwei sequenzielle Aufrufe in einem Thread**. Dieselbe Luecke wie AG3-214 B2, eine Schicht tiefer. |
| 2 | `…test_inflight_idempotency_guard_postgres.py:262` | Docstring verspricht, eine „domain-looking payload" koenne einen Orphan nicht terminalisieren — **eine solche Payload wird nie konstruiert**. Woertliches Duplikat von `:240`. |
| 3 | `tests/integration/control_plane_http/test_admin_cli_writer_routes.py:1977` | „parallel same op_id is rejected in flight" — der In-Flight-Zustand wird **von Hand als Vorbedingung gesetzt**, dann **ein** Request gesendet, gegen den In-Memory-Guard. |
| 4 | `tests/integration/control_plane/test_startup_reconcile_pg.py:208` | Docstring: Finalisierung passiere **vor dem Binden des Sockets**. `serve_control_plane` wird nie aufgerufen, keine Reihenfolge assertiert, und die App wird mit `writer_lease_required=False` gebaut. Dieselbe Form wie AG3-214 B1. |
| 6 | `tests/unit/cli/test_lifecycle_cli.py:450` | Will `control-plane.json` und den Serve-Bind-Port „zusammenbinden". `run_checkpoint_install` ist ein Spy, nichts wird geschrieben, die Serve-Seite bleibt unberuehrt — **die Assertion vergleicht `CORE_PROJECT_API_PORT` mit sich selbst**. |
| 7 | `tests/unit/control_plane/test_hook_mediation_services.py:145` | Die Exactly-once-Eigenschaft wird **im Fake nachgebaut** (eigener Kommentar: „Atomic in the real adapter; here counter + key move together") und dann **am Fake** assertiert. |

## Drei Notizen mit geringerer Sicherheit

Zitierfaehig, aber nur teilweise an ihrer Zusage vorbei — **erst bewerten, dann
entscheiden**:

- `test_ag3_214_single_writer_contract.py:151` — Delegation ueber
  Substring-Pruefungen auf Quelltext. Fuer eine Quelltext-Vertragsdatei
  moeglicherweise beabsichtigt.
- `test_admin_cli_writer_routes.py:1125` (`…migrates_hooks_through_real_writer`)
  — die Writer-Haelfte ist echt, aber `run_checkpoint_upgrade` ist gestubbt,
  also laeuft kein produktives `up_04_migrate_hooks`.
- `test_main.py:254` (`…without_mutation`) — die Nicht-Mutations-Haelfte wird
  nie assertiert.

## Scope

### In Scope

- **#5 zuerst**, weil er einen Widerspruch erzeugt und den Pfad wiederbelebt,
  den AG3-214 entfernt hat.
- Die uebrigen sechs: Jeder Test belegt danach **seine eigene Zusage** — oder
  seine Zusage wird auf das zurueckgenommen, was er tatsaechlich prueft. Beides
  ist zulaessig; **stillschweigend stehenlassen ist es nicht.**
- Die drei Notizen werden **bewertet**: Zusage praezisieren, Test korrigieren
  oder als beabsichtigt begruenden.

### Out of Scope

- Produktionsverhalten. Diese Story fuehrt Beweise, sie aendert keine Fachlogik.
  Faellt dabei ein echter Produktionsdefekt auf, ist das ein Befund mit
  Vorlage — kein Anlass, ihn nebenbei zu beheben.

## Akzeptanzkriterien

1. **Je Fundstelle: Der Test betritt das Fenster**, das er absichert — belegt
   durch **Revert-Red**: Die Zusage wird probeweise gebrochen, der Test wird
   rot, die Aenderung wird zurueckgebaut. Ohne diesen Beleg ist „behoben" eine
   Behauptung.
2. **#5 loest den Widerspruch auf.** Danach benutzt kein Test mehr den lokalen
   Repository-Pfad, dessen Abwesenheit
   `test_ag3_214_single_writer_contract.py:164-173` assertiert — oder jene
   Assertion ist als falsch belegt und wird korrigiert. **Beides gleichzeitig
   stehen zu lassen ist ausgeschlossen.**
3. **Wo Nebenlaeufigkeit behauptet wird, ist sie echt** (#1, #3) — zwei
   gleichzeitig lebende Aufrufe, deren Ueberlapp beobachtet und nicht
   angenommen wird. Vorbild: der in AG3-214 gebaute Barrier-/Park-Nachweis.
4. **Wo eine Reihenfolge behauptet wird, wird sie assertiert** (#4).
5. **Kein Beweis am Fake** (#7): Eine Eigenschaft, die der echte Adapter traegt,
   wird nicht im Double nachgebaut und dort geprueft.
6. **Duplikate verschwinden** (#2): Ein Test, der woertlich einen anderen
   wiederholt, wird entweder zu dem Fall, den sein Name verspricht, oder
   entfernt.
7. **Kein neuer Fundort.** Die Suche wird auf dem geaenderten Stand wiederholt;
   kommt eine achte Stelle dazu, wird sie gemeldet, nicht stillschweigend
   mitgenommen.
8. `ruff` clean bis auf den AG3-218-`C901`; `mypy --strict` fuer `win32`,
   `linux`, `darwin`; alle deterministischen Gates gruen; volle Suite gruen auf
   Jenkins.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §Tests — „Tests duerfen produktiven Pipeline-State nicht als
  Abkuerzung manuell zusammenfantasieren"
- `CLAUDE.md` §MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL — AC 5
- `CLAUDE.md` §FAIL-CLOSED — ein Test, der seine Zusage nicht prueft, meldet
  gruen ohne Aussage
