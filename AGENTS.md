# Local Agent Instructions

## Severity-Semantik

Drei Stufen, klar abgegrenzt:

- **PASS** — fehlerfrei, kein Handlungsauftrag.
- **WARNING** — Handlungsauftrag mit aufschiebender Wirkung. Muss
  gemacht werden, aber nicht sofort. Darf **nicht** ignoriert werden;
  aktiv an den Auftraggeber spiegeln mit der Frage "wie wollen wir hier
  vorgehen". Stilles Liegenlassen ist Verstoss gegen ZERO DEBT.
- **ERROR** — Handlungsauftrag ohne aufschiebende Wirkung. Sofort
  beheben.

Nicht jeder Befund braucht einen Warning-Pfad. Wo aufschiebbares Handeln
erfahrungsgemaess nicht passiert, ist ERROR die richtige Wahl.

## Pflicht-Gates vor "fertig"

- Jenkins gruen: `http://localhost:9900/job/claude-agentkit3/`
- Sonar gruen: `http://192.168.0.20:9901`
- Sonar-Ziel ist strikt: `violations=0`, `critical_violations=0`,
  `open_hotspots=0`
- Sonar-Zugang fuer dieses Workspace: `admin` / `meinSonarCube2026!`
- Konzept-Aenderungen werden gleich behandelt wie Code-Aenderungen:
  `scripts/ci/check_concept_frontmatter.py` und
  `scripts/ci/compile_formal_specs.py` muessen gruen sein. Der
  pre-commit Hook (`.githooks/pre-commit`) erzwingt das lokal, wenn
  `git config core.hookspath .githooks` gesetzt ist.

Den Repo-Zustand niemals so lassen, dass Jenkins oder das
Sonar-Quality-Gate rot wird.
