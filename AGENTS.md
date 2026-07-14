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

## LLM-Hub-Sparring

`llm_hub` ist kein Standard-Review-Schritt. Nutze Multi-LLM-Sparring nur,
wenn der konkrete Auftrag davon fachlich profitiert, z. B. bei
architektonisch folgenreichen Entscheidungen, Review von belastbaren
Konzept-/Code-Aenderungen, unklaren Trade-offs oder explizitem Wunsch des
Auftraggebers.

Nicht nutzen fuer normale UI-Prototyping-Schleifen, gemeinsame
Oberflaechenfindung, kleine Implementierungsarbeiten oder pauschales
"nochmal gegenlesen lassen". In diesen Faellen direkt mit dem
Auftraggeber iterieren.

## Pflicht-Gates vor "fertig"

- Jenkins gruen: `http://localhost:9900/job/claude-agentkit3/`
- Sonar gruen: `http://localhost:9901`
- Jenkins und Sonar laufen als lokale Docker-Container (`seu-jenkins`,
  `seu-sonarqube`). Alle Gate-Hosts sind maschinen-lokal ueber `localhost`
  zu adressieren; frueher genutzte LAN-IPs (z. B. `192.168.0.20`) sind
  rechner-spezifisch und nicht portabel.
- Sonar-Ziel ist strikt: `violations=0`, `critical_violations=0`,
  `security_hotspots=0` (Sonar-Metrik fuer offene Hotspots auf dieser
  Instanz; `open_hotspots` ist hier kein gueltiger Metric-Key)
- Jenkins-Build triggern: Der Job `claude-agentkit3` fuehrt den Repo-`Jenkinsfile`
  aus und ist **parametrisiert** (`agentkit_mode`, `sonar_project_key`,
  `sonar_branch`). Der CI-Loop startet mit
  `POST /job/claude-agentkit3/buildWithParameters?agentkit_mode=ci&sonar_project_key=claude-agentkit3&sonar_branch=main&delay=0sec`
  (plus CSRF-Crumb aus `/crumbIssuer/api/json`). Jenkins laeuft mit
  `SecurityRealm=None` + `AuthorizationStrategy=Unsecured`: kein Login, anonym
  hat Vollzugriff; ein Jenkins-Token wird nicht benoetigt (nur der Crumb fuer POST).
- Lokale Gate-Zugaenge liegen ausserhalb des Repos in
  `T:\seu\agentkit3-secrets.cmd` und werden von den Codex-Startern fuer
  CLI und App geladen. Die Datei setzt `SONAR_URL`, `SONAR_PROJECT_KEY`,
  `SONAR_USER`, `SONAR_PASSWORD`, `JENKINS_URL`, `JENKINS_USER`,
  `JENKINS_PASSWORD` und `JENKINS_API_TOKEN` (die JENKINS_*-User/Token
  sind bei `SecurityRealm=None` Platzhalter, damit Tooling mit
  Pflicht-Credentials nicht scheitert).
- Remote-Gates mit `scripts/ci/check_remote_gates.ps1` pruefen; das Script
  nutzt die geladenen Env-Vars und scheitert hart, wenn Jenkins oder Sonar
  nicht gruen sind.
- Konzept-Aenderungen werden gleich behandelt wie Code-Aenderungen:
  `scripts/ci/check_concept_frontmatter.py` und
  `scripts/ci/compile_formal_specs.py` muessen gruen sein. Der
  pre-commit Hook (`.githooks/pre-commit`) erzwingt das lokal, wenn
  `git config core.hookspath .githooks` gesetzt ist.
- Normative Konzept-Aenderungen brauchen entweder ein schema-konformes
  Record im selben Diff oder den Commit-Trailer
  `Concept-Decision: YYYY-MM-DD-<slug>` zu einem bestehenden Record.
  `Concept-Format-Only: <reason>` gilt nur fuer uneindeutige
  Tippfehler-/Format-Aenderungen und hebt normative Modalmarker nie auf.
- W4-Review-Checkliste: Impact-Sweep und Betroffenheitsmatrix im Record
  pruefen, danach Record-im-Diff oder gueltigen `Concept-Decision`-
  Trailer sowie den gruenen `check_concept_decision_record.py`-Lauf
  bestaetigen.
- Vor der Landung normativer Konzeptaenderungen W2 gegen die geaenderte
  Range ausfuehren (LLM-gestuetzt, daher bewusst kein blocking Push-Gate):
  `python scripts/ci/check_concept_authority_prose.py --mode pre-merge
  --base "${GIT_PREVIOUS_SUCCESSFUL_COMMIT:-HEAD~1}"`. Neue Befunde sind
  ERROR bis zum Fix oder einem konkret begruendeten Baseline-Eintrag.

Den Repo-Zustand niemals so lassen, dass Jenkins oder das
Sonar-Quality-Gate rot wird.
