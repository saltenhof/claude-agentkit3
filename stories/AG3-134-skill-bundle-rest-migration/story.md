# AG3-134 — Skill-Bundle `execute-userstory-core` auf REST/BC-reconciled Orchestrierung migrieren

- **Typ:** implementation
- **Größe:** L
- **depends_on:** AG3-130
- **Quell-Konzept:** FK-10 §10.1.0 (I1–I6, zentraler Kern), FK-91 §91.1a
  (Phase-Mutation-Endpunkte), FK-72 §72.8.2 (kanonischer Mutationspfad),
  FK-45 (Phase-Runner-CLI), `concept/_meta/bc-cut-decisions.md`
  ("Verify als Capability, Variante Y")
- **WP-Zuordnung:** A (dev-seitige Umstellung auf zentralen Kern)

## Kontext

Bei der Landung von AG3-130 (Operator-CLI `run-phase`/`resume` → REST,
Commit 72a8889) wurde ein **systemischer, vorbestehender Drift** verifiziert:
Das einzige deployte Skill-Bundle `execute-userstory-core/4.0.0`
(`src/agentkit/bundles/skill_bundles/execute-userstory-core/4.0.0/SKILL.md`)
ist vollständig gegen das **alte, file-basierte In-Process-Modell** geschrieben
und trägt gegen die aktuelle CLI/REST-Orchestrierung nicht.

Dieser Drift ist **kein AG3-130-Defekt**: er bestand vor AG3-130. `run-phase`
verlangte `--run/--session/--principal` bereits auf `main`; die Ablehnung von
`verify` als Top-Phase stammt aus dem Bounded-Context-Schnitt. AG3-130 hat die
CLI nur konsequent Richtung REST-Zielbild gezogen und den Drift dadurch
sichtbar gemacht.

Belege (verifiziert, Stand Commit 72a8889):

| Befund | Evidenz | Problem |
|---|---|---|
| 11× `agentkit run-phase <phase> --story <ID>` liefert nur `--story` | `SKILL.md:125,195,236,447,517,540,547,553` | CLI verlangt `--run/--session/--principal/--worktree` → argparse-Fehler |
| ~4× `agentkit run-phase verify` | `SKILL.md:362,397,410,547` | CLI-`_VALID_PHASES`={setup,exploration,implementation,closure}; Fehlertext „'verify' is a capability, not a top-level phase" (`cli/main.py:1571,1949`) |
| Liest `_temp/qa/<ID>/phase-state.json` | `SKILL.md:130` | file-basiertes Alt-Statemodell statt REST-Antwort/Handshake |
| Kein REST-Bewusstsein | grep: kein `base-url`/`--session`/`projectedge`/`/v1/`/`control-plane` im Bundle | Bundle kennt das Control-Plane/REST-Modell nicht |

Zusätzlich (W2, kleiner): die CLI-Kurzform `agentkit resume --story <id>` steht
noch normativ/illustrativ in **6+ Konzeptdokumenten**
(`formal-spec/exploration/commands.md:47`, `formal-spec/escalation/commands.md:39`,
`formal-spec/story-reset/commands.md:41`, `technical-design/20_*:609-611`,
`technical-design/35_*:827,840`, `technical-design/45_phase_runner_cli.md:338`)
und divergiert von der präzisen REST-Signatur, die AG3-130 in
`formal-spec/story-workflow/commands.md` etabliert hat. Ein Einzel-Fix an nur
einer Stelle würde diese Datei von ihren Geschwistern abweichen lassen — daher
korpusweit und kohärent zu lösen.

## Scope

### In Scope

- **W1 — Bundle-Migration:** `execute-userstory-core/4.0.0` (bzw. eine neue
  Bundle-Version nach Versionierungsregel) auf den REST/BC-reconciled
  Orchestrierungs-Kontrakt umstellen:
  - Phasen-Progression über den kanonischen REST-Mutationspfad
    (`POST /v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/{start|complete|fail|resume}`)
    bzw. den dafür vorgesehenen dünnen CLI-/ProjectEdge-Requester — mit den
    real geforderten Parametern (`--run/--session/--principal/--worktree/--base-url`
    bzw. deren Herkunft aus gebundenem Kontext).
  - `run-phase verify` eliminieren; die Verify-QA korrekt als **in-process
    Capability-Subflow innerhalb der Implementation-Phase** abbilden
    (bc-cut "Variante Y"), nicht als Top-Phase.
  - Alt-Statemodell `_temp/qa/<ID>/phase-state.json` durch die autoritative
    REST-Antwort/den Run-State ersetzen (keine zweite operative Wahrheit).
  - Version-Handshake (`X-AK3-Skill-Bundle`) konsistent zur gebundenen
    Bundle-Version.
- **W2 — Signatur-Korpus:** die `agentkit resume --story`-Kurzform korpusweit
  gegen die präzise, in `story-workflow/commands.md` verankerte Form angleichen
  (bzw. einheitlich als klar gekennzeichnete Operator-Recovery-Kurzform
  definieren), sodass keine Doppelwahrheit zwischen den BC-Command-Sets bleibt.

### Out of Scope

- Änderungen am REST-/Control-Plane-Kern selbst (der ist durch AG3-129/130 gesetzt).
- Der Leased-Claim-TTL-/Fencing-Aspekt (Codex-R3-Fund 1) — das ist ein eigener,
  querschnittlicher Hardening-Punkt über **alle** Phasen-Mutationen (start_phase
  hat dasselbe Fenster) und gehört nicht in die Bundle-Migration.
- Neue fachliche Phasen-Semantik; nur der Transport/Instruktions-Dialekt wird
  migriert, nicht das Phasenmodell.

## Betroffene Dateien (Erwartung, in Setup zu verifizieren)

| Datei | Art |
|---|---|
| `src/agentkit/bundles/skill_bundles/execute-userstory-core/**/SKILL.md` | überarbeiten (REST-Dialekt) |
| ggf. neue Bundle-Version + Manifest | anlegen (Versionierungsregel) |
| `concept/formal-spec/{exploration,escalation,story-reset}/commands.md` | resume-Signatur angleichen |
| `concept/technical-design/20_*`, `35_*`, `45_phase_runner_cli.md` | resume-Kurzform vereinheitlichen |
| Bundle-Contract-/Golden-Tests | mitziehen |

## Akzeptanzkriterien

1. Kein Bundle-Aufruf verwendet mehr `run-phase verify`; die Verify-QA ist als
   in-process Capability-Subflow der Implementation-Phase beschrieben.
2. Alle Phasen-Progressionen im Bundle nennen die real geforderten Parameter
   bzw. deren gebundene Herkunft; kein Aufruf scheitert an argparse/`InvalidPhase`.
3. Keine Referenz mehr auf `_temp/qa/<ID>/phase-state.json` als operative
   Wahrheit; der Run-/Phasen-Status kommt aus der REST-Antwort/dem Run-State.
4. Der Version-Handshake (`X-AK3-Skill-Bundle`) ist konsistent zur gebundenen
   Bundle-Version.
5. Die `agentkit resume --story`-Kurzform ist korpusweit kohärent (keine
   Doppelwahrheit zwischen den BC-Command-Sets); die 4 Konzept-Gates bleiben grün.
6. Contract-/Golden-Tests für das Bundle sind aktualisiert und grün.
7. Standard-Validatoren grün: `pytest` (unit/integration/contract), `mypy src`
   (strict, inkl. `--platform linux`), `ruff check src tests`, Coverage ≥ 85 %.

## Definition of Done

- Akzeptanzkriterien 1–7 erfüllt.
- Konzept-Edits (falls normativ) dem PO vor Übernahme vorgelegt.
- Ein thematischer Commit (oder wenige kleine), auf `origin/main` gemerged.
- `status.yaml` → `completed`; README-Snapshot nachgezogen.

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM / SINGLE SOURCE OF TRUTH:** keine zweite
  operative Wahrheit (file-State neben REST-Run-State).
- **ZERO DEBT / NO ERROR BYPASSING:** deployter Instruktions-Content muss gegen
  den aktuellen Kontrakt tragen; keine Alt-Dialekt-Reste.
- **Konzepttreue:** `verify` bleibt Capability-Subflow (bc-cut Variante Y), keine
  Wiedereinführung als Top-Phase.
