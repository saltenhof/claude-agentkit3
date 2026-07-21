# Abschlussakte — Gruendungslauf Konzeptions-Support

Run-ID: `2026-07-19-conception-support-b4a7d375` · Council-Orchestrator:
Fable 5 (Claude Code) · Unabhaengiger Reviewer: Codex
(`openai.codex.review-agent`, persistente Session, elf Runden).

## 1. Auftrag und Ergebnis

AK3 unterstuetzte die der Story-Welt vorgelagerte Konzeptionsphase nicht.
Dieser Lauf hat sie eingefuehrt: als normativ definierten Prozess (DK-16,
FK-78, formaler Kontext `concept-incubation`), als deploybare
deterministische Toolchain und als harness-optimierten Skill — nicht als
Backend-Funktion.

## 2. Lieferumfang

### Konzeptwelt (normativ)

| Artefakt | Inhalt |
|---|---|
| `concept/domain-design/16-konzeption-und-konzeptinkubation.md` | DK-16: neue Saeule Konzeption; Drei-Welten-Modell, Rollen, Verlustfreiheitsanspruch, Proportionalitaet |
| `concept/technical-design/78_concept_incubation_process.md` | FK-78: Blueprint-Topologie, Inkubator-Layout, Artefakt-Schemata, Lauf-Lifecycle, Principals/Guards, Claim-Verfahren, Promotion-Closure, Projektionsmanifest, Datenklassen, Toolchain, Skill-Auslieferung |
| `concept/formal-spec/concept-incubation/*` (7 Dateien) | Entities, State-Machine, Commands, Events, Invarianten, Szenarien, README |
| `concept/_meta/assertion-authority.md` | Assertion-/Projektions-Vertrag: "accepted setzt das Ziel, nur eine aktive aequivalente Projektion ist ausfuehrbar, Widerspruch blockiert" |
| `concept/_meta/projection-manifest.json` | Korpusweiter Traeger von `assertion_status`/`equivalence_status` |
| `concept/_meta/concept-governance.json` | Projektlokale Toolchain-Konfiguration |
| `concept/_meta/decisions/2026-07-19-concept-incubation-support.md` | Decision Record mit Impact-Sweep und Betroffenheitsmatrix (27 Stellen) |
| Angepasst | DK-00 (Saeule 4.10), FK-00 (§20a), Meta-Contract §2/§10, Syntax-Contract, 4 Registries, Referenz-Baseline, CLAUDE.md (dritter Work-Mode), PROJECT_STRUCTURE.md |

### Software

- `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/`
  — 18 Module + 13 JSON-Schemas, stdlib-only, deploybar; `check.py`
  (read-only) und `semantic_gate.py` (mutierend, identitaetsgebunden).
- `src/agentkit/bundles/skill_bundles/concept-incubation-core/4.0.0/`
  — Root-`SKILL.md` mit Rollen-Gate und Harness-Selbsterkennung,
  4 Referenzen, 12 Templates, Manifest.
- Tests: 387 in `tests/unit/concept_toolchain`, `tests/contract/skills`,
  `tests/integration/prompts_and_skills` — inkl. E2E-Mini-Lauf,
  Zwei-Prozess-Nebenlaeufigkeitstests und Adversarial-Faellen.

## 3. Reviewkette (Codex, adversarial)

| Runde | Job | Urteil |
|---|---|---|
| R1 | job-75972bf3 | Rework (4 P0) — Verlustfreiheit, Authority-Vertrag, Rollenmodell, Lifecycle |
| R2 | job-5de6acf6 | 9 Auflagen — Zweiphasen-Claims, Statusmodell, Locks, Receipts |
| R3 | job-9f8b7259 | Rework (1 P0) — Source-Units statt Quell-Claims |
| R4 | job-9ca613d8 | freigegeben mit Auflagen |
| R5 | job-c2f5b2c7 | Rework (7 P1) — Manifest, Freeze, Formal-Totalitaet, Single-Assertion |
| R6 | job-8ccab04b | Rework (2 P0) — Set-Closure, Receipt-Bindung |
| R7 | job-67a3b63d | Rework (4 P0) + 20 Receipt-Verdicts (12 equivalent / 8 disagrees) |
| R8 | job-ed46c634 | Rework (4 P0) — TargetSpec, Projection-Closure, Intake, Mutex |
| R9 | job-83cb121e | Rework (2 P0) — TOCTOU, Intake-Freeze |
| R10 | job-4f2b0fdc | Rework (1 P0) — Mutex-Interleaving durch zwei Intents |
| R11 | job-8fce8e42 | Schlussverdict: 1 P0 (Stale-Intent-Reclamation) + 1 redaktioneller Widerspruch |

Belege: `review-{1,4,5,6,7,8,9,10,11}-codex.md`.

Jede Runde hat reale Befunde produziert, und die Schwere ist monoton
gefallen (4 P0 → 2 → 1). Praktisch jeder P0 war eine Stelle, an der
die Maschinerie ein **falsches Gruen** haette liefern koennen —
ausgelassene Quellen, gefaelschte Belege, umgehbare Gates,
Nebenlaeufigkeitsfenster. Keiner davon waere bei gruenen Tests in einer
Selbstpruefung aufgefallen; das ist der empirische Beleg fuer die
Grundthese dieses Vorhabens.

## 4. Reviewer-Verdicts (Endstand R11)

19 von 20 Zielprojektionen tragen `equivalent`. Offen bleibt
`concept_toolchain/` (`disagrees`) wegen der nicht-atomaren
Stale-Intent-Bereinigung (§6 Nr. 3). Ausdruecklich akzeptiert hat der
Reviewer: den `blocked_projection`-Endstand als richtig, die
SSOT-Scope-Entscheidung als offen angenommene Uebergangsschuld, die
dokumentierte VCS-Vertrauensgrenze der Intake-Pins und die
Zeitordnungs-Haertung (R10-2 materiell geschlossen).

## 5. Warum die Scopes blockiert bleiben

Die drei Scopes stehen auf `blocked_projection`, weil dieser Lauf ein
**Bootstrap-Lauf ohne schema-konforme Register** ist — er hat das
Verfahren erst eingefuehrt. Receipt-Dateien in ihm waeren nach FK-78
§78.11/§78.12 kein Closure-Beleg, und rueckwirkend erzeugte Register
waeren genau die Schein-Evidenz, die das Verfahren verhindern soll. Die
Toolchain bestaetigt das selbst: `check.py all` endet mit Exit 2 und
weist den Lauf als Nicht-Promotions-Lauf aus.

**Aufloesung:** ein eigener, schema-konformer Projection-Audit-Lauf mit
der fertigen Toolchain. Owner: Council-Orchestrator. Sichtbar via
`concept/_meta/projection-manifest.json` und `README.md`.

## 6. Benannte Restpunkte (vom Reviewer fuer den Bericht verlangt)

1. **Projection-Audit-Lauf** — hebt die drei Scopes auf `active`.
2. **SSOT-Wrapper-Migration** der `scripts/ci`-Gates auf die gebundelte
   Engine (Decision Record §2 Nr. 4: Owner, Trigger, Closure-Nachweis,
   benanntes Interimsrisiko).
3. **Nicht-atomare Stale-Intent-Bereinigung** (einziger offener
   P0-Befund, R11): Bleibt ein Coordination-Intent nach einem
   Prozessabsturz liegen, ist seine automatische Bereinigung
   Read-then-Unlink; zwei gleichzeitige Aufraeumer koennen sich
   gegenseitig das Intent entziehen. Der normale
   Einzelschreiber-Betrieb ist nicht betroffen. Aufloesung: OS-Advisory-
   Lock (`fcntl.flock`/`msvcrt.locking`) oder fail-closed manuelle
   Recovery. Normiert als benannte Grenze in FK-78 §78.4.
4. **VCS-Vertrauensgrenze der Intake-Pins** — die Pins liegen in
   `RUN.json`; wer diese Datei mit umschreibt, macht jede Kette lokal
   konsistent. Anker ist die versionierte Datei in der Historie.
5. **Restfenster beim atomaren Dateiaustausch** — ein einzelner
   `os.replace` nach der letzten Eigentumspruefung.
6. **Compiler-Folgearbeit** — schrittgenaue Command-Transition-Bindung und
   Reject-Traces (heute erreichbarkeitsbasiert).
7. Harness-Variant-Achse im Skill-Binder, Hub-Batch-Komfort fuer W2/W3,
   KPI-/Telemetrie- und Backend-Sicht.

## 7. Verifikationsstand

Toolchain-, Bundle- und Integrationstests: 387 passed. Repo-weit
9888 passed / 14 skipped; ruff clean; mypy 965 Dateien clean. Alle vier
AK3-Konzept-Gates PASS (frontmatter 90 Docs; formal 192 Docs / 149
Szenarien; references 0 Errors bei 57 baselined Reports;
decision-record PASS). Gebundelte Engine: frontmatter, references,
formal, projection PASS; `all` Exit 2 (siehe §5).

Nach einem unterbrechenden Rechner-Neustart am 2026-07-20 wurde der
gesamte Stand erneut verifiziert: Arbeitsbaum vollstaendig (117
Aenderungen staged, 18 Toolchain-Module, 13 Schemas), alle Gates und
Tests unveraendert gruen.
