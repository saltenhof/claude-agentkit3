# AG3-210 — Der Update-Pfad rollt aus, was er bestaetigt

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-51 (Upgrade/Migration), FK-10 (Installer/Deployment),
  FK-30 (Hook-Registrierung)
- **Herkunft:** Fremdinstallation `intima`, 2026-08-03. PO-Entscheid am selben
  Tag: eigener Schnitt, nicht in AG3-206 oder AG3-187 hineingezogen.

## Kontext

### Befund — belegt, mit Locatoren

Am 2026-08-03 war der ausgerollte Scaffold-Hook
`.agentkit/hooks/pre_tool_use.py` defekt: er importierte
`agentkit.governance.*`, ein Modul, das der Deployment-Unit-Umbau entfernt
hatte. Gemessen in **einer** Sitzung: **85 Fehlschlaege**, und fuer `Write`,
`Edit`, `Read`, `Grep` und `Glob` lief **kein einziger** AK3-Guard.

Der Fix landete am selben Tag in AK3. **Im installierten Projekt kam er nicht
an**, und der Weg dorthin fehlt:

| Pfad | Was er tut |
|---|---|
| `agentkit register-project` → CP 8 → `deploy_post_registration_artifacts()` (`installer/runner.py:1150`) | ruft `_deploy_static_resource_files` (`runner.py:581-596`): kopiert **jede** Nicht-Template-Datei aus `bundles/target_project` inhaltsgewacht ins Projekt |
| `agentkit upgrade-project` → `installer/upgrade/` | sechs Checkpoints — `detect_footprint`, `guard_binding`, `migrate_config`, `migrate_hooks`, `migrate_git_hook`, `cleanup`. **Keiner materialisiert eine Bundle-Datei.** |
| `agentkit update` | Kompatibilitaets-Handshake gegen den Kern (`GET /v1/compat`) — kein Datei-Update |

**Der eigentliche Defekt ist nicht das Fehlen, sondern die Bestaetigung.**
`up_04_migrate_hooks` registriert die Eintraege in `settings.json` neu und
besiegelt damit eine Bindung auf eine Datei, die es selbst nicht auffrischt.
Der Lauf meldet Erfolg ueber etwas, das er nicht geprueft hat.

### Warum das niemand gemerkt hat

Weil der Weg, der funktioniert, nicht so heisst. Ein Bediener — oder ein
kompetenter Agent, der den Code liest — sucht das Update und findet
`upgrade-project`. Dass ausgerechnet `register-project` der idempotente
Rollout-Pfad ist, steht nirgends; der Docstring von
`deploy_post_registration_artifacts` sagt es (*„Idempotent (every sub-step is
digest/content guarded)"*), aber nur dort.

## Scope

### In Scope

- Der Update-Pfad frischt die ausgelieferten Bundle-/Scaffold-Dateien auf —
  inhaltsgewacht und idempotent, ohne fremde Projektdateien anzufassen.
- **Keine Bindung wird bestaetigt, deren Ziel nicht auf dem ausgelieferten
  Stand ist.** Ein Checkpoint, der eine Registrierung erneuert, verantwortet
  den Zustand des Registrierten.
- Klare Verbsemantik: welches Verb welchen Zustand herstellt, und was ein
  Bediener aufruft, um eine bestehende Installation auf den aktuellen Stand zu
  bringen. Redundanz zwischen `register-project` und `upgrade-project` wird
  aufgeloest, nicht dokumentiert.
- Normative Nachfuehrung in FK-51 samt Decision Record.

### Out of Scope

- Der Erstinstallations-Golden-Path — **AG3-187**.
- Vollstaendigkeit der Abhaengigkeiten und Sichtbarkeit verschluckter
  Hook-Fehler — **AG3-206**.
- Installationsart und Interpreterbindung — **AG3-189**.
- Die Aufteilung in zwei Distributionen — **AG3-208/AG3-209**. Sie aendert,
  *welches* Bundle wohin gehoert; diese Story stellt sicher, dass es ueberhaupt
  ankommt.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/installer/upgrade/upgrade_flow.py` | geaendert | der Fluss bekommt den Rollout-Schritt |
| `src/agentkit/backend/installer/upgrade/hook_migration.py` | geaendert | bestaetigt keine Bindung auf einen veralteten Stand mehr |
| `src/agentkit/backend/installer/runner.py` | geaendert | `_deploy_static_resource_files` wird vom Update-Pfad mitbenutzt, nicht kopiert |
| `src/agentkit/backend/cli/installer_commands.py` | geaendert | Verbsemantik und Hilfetext |
| `concept/technical-design/51_*.md` | geaendert | Update-Pfad normativ: was ein Upgrade herstellt |
| `concept/_meta/decisions/2026-XX-XX-update-rollt-aus.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/integration/installer/` | neu | Rollout, Idempotenz, Fremddatei-Schutz |

## Akzeptanzkriterien

1. **Ein Upgrade bringt eine veraltete ausgelieferte Datei auf den aktuellen
   Stand.** Nachgewiesen an einem registrierten Projekt, in dem
   `.agentkit/hooks/pre_tool_use.py` durch eine aeltere Fassung ersetzt wurde:
   nach dem Upgrade ist sie byteweise identisch mit dem Bundle-Stand.
2. **Ein zweiter Lauf aendert nichts.** Byteweise identisch, und der Bericht
   weist null geaenderte Dateien aus — nicht „erfolgreich aktualisiert".
3. **Keine Bindung wird auf einen veralteten Stand besiegelt.** Steht eine
   Registrierung in `settings.json` auf eine Datei, die nicht dem
   ausgelieferten Stand entspricht, faellt der Checkpoint fail-closed, statt
   den Eintrag zu erneuern. Nachgewiesen mit genau diesem Aufbau.
4. **Fremde Dateien bleiben unberuehrt.** Eine projekteigene Datei im selben
   Verzeichnis, eine projekteigene `.gitignore`-Zeile und eine vom Bediener
   geaenderte `CLAUDE.md` ueberleben byteweise — inklusive Zeilenenden und
   Kodierung. (CP 11 schreibt die `CLAUDE.md` nur bei Abwesenheit;
   `cp11_to_12.py:28-91`. Das bleibt so.)
5. **Die Verbsemantik ist eindeutig.** Fuer „bestehende Installation auf den
   aktuellen Stand bringen" gibt es **genau einen** dokumentierten Aufruf.
   Existieren danach noch zwei Verben, die denselben Zustand herstellen, ist
   das eine Kompatibilitaetsschicht und damit ein Fehler.
6. **Der belegte Anlassfall ist reproduziert.** Ein Test stellt den Zustand vom
   2026-08-03 her — installiertes Projekt mit totem Scaffold-Hook — und weist
   nach, dass der Update-Pfad ihn behebt. Gegen den heutigen Stand ist dieser
   Test rot; per Mutation belegt.
7. **Zwei verwaiste 0-Byte-Vorlagen sind entschieden.**
   `bundles/target_project/templates/CLAUDE.md.j2` und
   `templates/story-pipeline.yaml.j2` werden von nichts gerendert (CP 11
   schreibt ein Inline-Skelett). Entweder sie bekommen einen Producer oder sie
   fliegen. Liegenlassen ist keine Option.
8. **Konzept nachgezogen** (FK-51) mit Decision Record und
   Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- **Realitaetsnachweis:** der Update-Pfad ist einmal gegen ein echtes, ausserhalb
  dieses Repos installiertes Projekt gelaufen — nicht nur gegen `tmp_path`.
- Volle Suite gruen, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
  `darwin`; Coverage haelt 85 %.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — eine Bindung auf einen unbekannten Stand ist ein
  Fehler, keine Toleranzlage.
- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN" — zwei Verben fuer denselben
  Zustand sind eine.
- `CLAUDE.md` „ZERO DEBT RULE" — die verwaisten Vorlagen werden entschieden,
  nicht markiert.
- `guardrails/testing-guardrails.md` — Negativpfade an Phasengrenzen.
