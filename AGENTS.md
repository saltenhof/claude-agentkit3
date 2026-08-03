# Local Agent Instructions

## Lies zuerst CLAUDE.md — diese Datei ist nicht die ganze Ordnung

`CLAUDE.md` im Repo-Root ist die **normative** Verhaltens- und Codeordnung
dieses Projekts. Diese Datei hier ergaenzt sie und ersetzt sie nicht. Wer nur
`AGENTS.md` liest, kennt unter anderem folgende bindenden Regeln **nicht**:

- ZERO DEBT und die Begruendung, warum Schuld nie billiger ist als ihre
  Beseitigung
- **KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS**, inklusive des Verbots,
  ueber Migrationspfade auch nur nachzudenken
- FAIL-CLOSED, NO ERROR BYPASSING, MOCKS/STUBS nur im engen Ausnahmefall
- **ARCH-55**: Quellcode, Bezeichner, Wire-Keys, DB-Spalten und Kommentare
  ausnahmslos englisch
- die Struktur- und Deployment-Unit-Regeln
- **REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN**: gruene Unit-Tests sind
  Voraussetzung, nie Nachweis
- die Zugaenge zu den lokalen Diensten (Postgres, Sonar, Jenkins) — sie sind
  vorhanden und **nicht** beim Auftraggeber zu erfragen

Bei Konflikt zwischen dieser Datei und `CLAUDE.md` gewinnt `CLAUDE.md`.

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
- **Die W2/W3-Pre-Merge-Pflicht ist seit 2026-08-02 ausgesetzt (PO-Entscheidung).**
  Die Konzeptpruefung wird umgestellt: weg von LLM-Hub-Gates, an die
  Konzeptanteile geschickt werden in der Hoffnung auf saubere
  Modellantworten, hin zu nativen KI-Agenten ueber die Harness-Bridge,
  denen von aussen nur Leitplanken, Ziele und Nachweispflichten
  vorgegeben werden und die ihre Strategie selbst waehlen. Bis das neue
  Verfahren normiert ist, gilt:
  - `check_concept_authority_prose.py` (W2) und
    `check_concept_scope_consistency.py` (W3) sind **kein
    Abnahmekriterium** mehr. Ein nicht gefahrener, abgebrochener oder
    unvollstaendiger Sweep blockiert die Landung nicht.
  - **Ein Lauf bleibt erlaubt, und ein inhaltlicher Befund bleibt
    verbindlich.** Wer W2/W3 faehrt und einen Befund erhaelt, behebt ihn
    an der Wurzel oder traegt ihn begruendet in die Baseline ein.
    Ausgesetzt ist die Pflicht zum Lauf, nicht der Umgang mit dem
    Ergebnis.
  - **Ein nicht durchgelaufener Sweep wird niemals als "gruen"
    berichtet.** "Konzept-Gates gruen" bezeichnet ausschliesslich die
    statischen Gates. Wer beides zusammenzieht, wiederholt die
    Ueberbehauptung aus AG3-179 Runde 1.
  - **Der Grund ist Erfuellbarkeit, nicht Bequemlichkeit.** Eine Regel,
    die im Repo steht und nicht erfuellbar ist, erzieht dazu, sie still
    zu uebergehen oder "Gates gruen" zu behaupten — beides ist bereits
    passiert. Belegt in
    `stories/AG3-179-run-mutex-intent-liveness/report.md`: ein
    reproduzierbarer `HUB_UNREACHABLE` an einer Partition von 35666
    Zeichen im qwen-Adapter, und ein fehlender Retry in
    `collect_scope_findings`, der einen kompletten Sweep an einem
    einzigen nicht-woertlichen Modellzitat beendet.
- **Unveraendert verbindlich und blockierend bleiben alle
  deterministischen Konzept-Gates:** `check_concept_frontmatter.py`,
  `compile_formal_specs.py`, `check_concept_reference_integrity.py` (W1),
  `check_concept_code_contracts.py`, `check_architecture_conformance.py`
  sowie `check_concept_decision_record.py` (W4) samt Record- und
  Betroffenheitsmatrix-Pflicht. Die Aussetzung betrifft **ausschliesslich**
  die beiden LLM-gestuetzten Sweeps. Es gibt weiterhin keinen gate-freien
  Pfad in die normative Welt.
- **Was bis zur Normierung des neuen Verfahrens an ihre Stelle tritt:**
  Eine normative Konzeptaenderung wird vor der Landung einem
  **unabhaengigen Agenten** vorgelegt — anderer Principal, andere
  Session als der Verfasser — mit drei benannten Pruefachsen:
  (1) zeigen die Aenderungen auf die richtigen normativen Zielstellen und
  auf Dokumente, die den Scope besitzen duerfen, (2) ist die Aenderung in
  sich und gegen den beruehrten Bestand widerspruchsfrei, (3) trifft sie
  den Problemraum und ist sie ohne eigene Annahmen umsetzbar. Befunde
  werden an der Wurzel behoben; "konnte nicht geprueft werden" ist ein
  zulaessiges Ergebnis und niemals PASS. Das ist die bereits geltende
  Codex-Review-Grundregel aus `CLAUDE.md`, angewandt auf
  Konzeptaenderungen — sie braucht keine neue Mechanik.
- **Leitplanken und Ziel sind nicht Gegenstand der Agentenstrategie**
  (PO-Ratifikation 2026-08-02). Der Agent ist frei in seiner Strategie
  und frei in seinem Handeln. Er ist **nicht** frei im Ziel und nicht in
  den Leitplanken: er muss das Ziel erfuellen und dabei die Leitplanken
  beruecksichtigen.

  **Er hat dabei ausdruecklich das Mandat, neue normative Inhalte zu
  schaffen** — also Aussagen darueber, was gilt. Das Mandat ist an drei
  Bedingungen gebunden, die zusammen gelten muessen:
  1. Die neue Aussage ist die **Ausdetaillierung** eines Konzeptinhalts,
     der an anderer Stelle bereits groeber definiert ist. Es gibt eine
     benennbare Ankerstelle, gegen die sie sich ausweist.
  2. Sie **widerspricht keinem vorhandenen Konzept**.
  3. Sie **eroeffnet keine neue Konzeptdomaene**.

  Fehlt der Anker, waere die Domaene neu, oder entstuende ein
  Widerspruch, **holt der Agent zuerst den Product Owner**. Er legt
  offen, welcher Pfosten fehlt, und laesst sich die groben Pfosten auf
  **Meta-Konzeptebene** setzen — nicht die Ausformulierung, sondern den
  Rahmen. Danach ist die Arbeit wieder Ausdetaillierung entlang eines
  Ankers, und er schreibt weiter. Ohne diesen Schritt schreibt er nicht
  weiter: eine fehlende Grundentscheidung wird nicht durch eine gut
  formulierte Detailaussage ersetzt.

  Damit steht die freie Strategiewahl nicht im Widerspruch zu `CLAUDE.md`
  und FK-78 section 78.14 ("LLM nur als Bewertungsfunktion, kein
  Werkzeug entscheidet frei"): frei sind **Ermittlung und
  Ausdetaillierung entlang eines Ankers**; nicht frei ist das Setzen
  neuer Grundentscheidungen. Verboten ist Erfindung, nicht Ableitung.

Den Repo-Zustand niemals so lassen, dass Jenkins oder das
Sonar-Quality-Gate rot wird.
