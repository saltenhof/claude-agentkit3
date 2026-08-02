# AgentKit 3
# Deterministische Orchestrierungsmaschine fuer KI-gestuetzte Story-Abarbeitung

## Project Context
Tech: Python 3.11+ (`pytest`, `pytest-cov`, `pytest-asyncio`, `mypy` strict, `ruff`), Pydantic v2, PyYAML, psutil, `weaviate-client`, `mcp` (>=1.2,<2) — die beiden letzten sind **Pflicht**-Basis-Dependencies, keine Extras (FK-13 §13.1, Beschluss 2026-07-21 Rand 1)

Repository: `T:/codebase/claude-agentkit3` — Python-Paket mit `src/`-Layout, Tests, Konzeptdokumenten und deploybaren Zielprojekt-Assets.

Key references:
- `PROJECT_STRUCTURE.md` — verbindliche Verzeichnisstruktur und Modulgrenzen
- `concept/domain-design/00-uebersicht.md` — fachliche Gesamtuebersicht
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` — Architekturprinzipien und Trust Boundaries
- `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md` — Zustaende, Artefakt-Ownership, Invarianten
- `concept/methodology/software-blutgruppen.md` — Klassifikation von Code nach A/R/T/0
- `concept/technical-design/72_frontend_architektur.md` — BC-aligned Frontend-Schnitt, App-Shell, BFF-Topologie
- `guardrails/architecture-guardrails.md` — architektonische Leitplanken
- `guardrails/testing-guardrails.md` — Pipeline- und Negativpfad-Testpflichten
- `pyproject.toml` — Paket-Metadaten sowie pytest/mypy/ruff/Coverage-Konfiguration

### Kernauftrag

AK3 gewährleistet ein hochqualitatives E2E-Ergebnis in der autonomen, agentischen AI-Software-Entwicklung und ermöglicht so eine stärkere Skalierbarkeit agentischer Entwicklungsprozesse. Seine Aufgabe erfüllt AK3, indem es autonome AI-Agents mit Methoden, Prozessen und Werkzeugen unterstützt, Aktivitäten überwacht und dabei Fehlverhalten aktiv unterbindet, eigenständig Qualitätssicherung betreibt. AK3 konzentriert sich auf die Phase der Implementierung und verbindet das mit Lösungen für vor- und nachgelagerte Phasen, um einen holistischen Gesamtansatz zu ermöglichen.

Dieser Kernauftrag ist die normative Grundlage. Alle Architekturentscheidungen, Komponentenschnitte und Werkzeugwahl müssen sich an ihm messen lassen. Story, Phase, Pipeline, Stage, Worker, Worktree und Verify-Layer sind die *Methoden*, mit denen AK3 diesen Kernauftrag operationalisiert — nicht der Auftrag selbst. Bei Konflikten zwischen Operationalisierung und Kernauftrag gilt der Kernauftrag.

### Was ist AgentKit 3?

AgentKit 3 ist die Neuausrichtung nach den Strukturproblemen von v2. Das System ist bewusst so gebaut, dass die zwei grossen v2-Fehler nicht wieder auftreten:

- **Kein operatives JSON-Flickwerk ohne Owner**: fachliche Verantwortung ist in Modulen, Domänenmodellen, Artefaktklassen und Producer-Registries klar zugeordnet.
- **Keine monolithische Workflow-Datei**: Workflows und Phasen sind entlang fachlicher Einheiten geschnitten (`pipeline/phases/`, `pipeline/workflow/`) statt als riesige imperative Steuerdatei.

AgentKit 3 ist kein Agent selbst. Es ist die Maschine, die Story-Ausfuehrung, Guardrails, QA, Telemetrie und Closure deterministisch orchestriert und nur dort LLMs einsetzt, wo kreative oder bewertende Arbeit wirklich noetig ist.

#### Die 4-Phasen-Pipeline

Jede Story durchlaeuft einen festen, fachlich definierten Ablauf:

| Phase | Typ | Zweck |
|---|---|---|
| **1 — Setup** | deterministisch | Kontext ableiten, Worktree vorbereiten, Guards aktivieren, Prompt-/Runtime-Kontext vorbereiten |
| **2 — Exploration** | LLM (optional) | Entwurfsartefakt fuer explorative Implementierungsstories; Exit-Gate ruft Capability `VerifySystem` |
| **3 — Implementation** | LLM + deterministischer QA-Subflow | Worker setzt Story um und liefert Handover-Artefakte. Enthaelt einen QA-Subflow analog zum Exit-Gate der Exploration: ruft die Capability `VerifySystem` (4-Schichten-QA, FK-27) inklusive Subflow-internem Remediation-Loop |
| **4 — Closure** | deterministisch | Integrity-Gate, Merge/Cleanup, Abschluss, Telemetrie/KPIs |

`verify-system` ist ein Capability-Bounded-Context, kein Phase-Owner. Eine eigenstaendige Top-Phase `verify` existiert nicht; Output-QA ist interner Subflow innerhalb der Implementation-Phase. Siehe `concept/_meta/bc-cut-decisions.md` "Verify als Capability (Variante Y)".

#### QA-Subflow — Schichten statt Ad-hoc-Pruefungen

- **Layer 1 — Structural**: deterministische Checks, Artefakt- und Build-/Test-Pruefung
- **Layer 2 — LLM-Evaluations**: QA-Review und Semantic/Guardrail-Review als Bewertungsfunktionen, nicht als frei handelnde Agents
- **Layer 3 — Adversarial**: gezielte Edge-Case-Pruefung fuer codeproduzierende Stories
- **Layer 4 — Policy Engine**: deterministische Aggregation entlang Trust-Klassen und Stage-Registry

#### Zustandsmodell in v3

v3 trennt bewusst:

- **StoryContext** fuer langlebige Story-Semantik
- **PhaseStateCore / PhasePayload / RuntimeMetadata** fuer Laufzeitstatus
- **QA-Artefakte mit Envelope + Producer** fuer verifizierbare Ergebnisse
- **Telemetrie zur Laufzeit in SQLite**, nicht als unkontrollierter JSON-Dateifaecher

JSON gibt es weiterhin fuer klar definierte Artefakte und Envelopes. Operative Wahrheit entsteht aber nicht aus einem ungeordneten Sammelsurium loser Dateien, sondern aus typisierten, ownership-klaren Modellen und deterministischen Laufzeitregeln.

## Guardrails

### ZERO DEBT RULE
Every deliverable must be fachlich vollstaendig im vereinbarten Scope. Keine stillen Restluecken, keine TODO-Verschiebungen, keine "spaeter sauber machen"-Strategie.

- Wenn etwas fehlt, blockiert oder ohne zusaetzlichen Kontext nicht sauber loesbar ist: explizit melden.
- Keine Attrappen fuer produktive Kernlogik.
- Keine halbfertigen Architekturuebergaenge, die alte und neue Modelle parallel herumtragen.

**Warum die Regel absolut ist.** Sie steht hier nicht als Anspruch an Sauberkeit,
sondern als Rechnung: **Keine Schuld ist billiger als ihre Beseitigung.** Sie
wird transitiv bezahlt — an anderer Stelle, zu einem spaeteren Zeitpunkt, von
jemand anderem, mit Zinsen und Zinseszins. Wer sie eingeht, bucht die Ersparnis
sofort und die Rechnung in ein fremdes Quartal.

Ohne diesen Satz ist die Regel wegrechenbar: Wer den heutigen Aufwand gegen den
heutigen Nutzen haelt, kommt bei Schuld fast immer auf „billiger" — weil die
Gegenbuchung noch nicht existiert. Genau dieser Vergleich ist der Fehler.

Der Zinseszins hat zwei Mechanismen, beide belegt:

- **Der Fehler vermehrt sich ueber Abhaengigkeiten.** Ein falscher Wert bleibt
  nicht einer. Er wird kopiert, referenziert und in Tests festgeschrieben; jede
  Kopie ist eine Zinszahlung, und der Hauptbetrag waechst, weil spaetere Arbeit
  auf dem falschen Stand aufsetzt.
- **Schuld, die wie ein Entwurf aussieht, kostet mehr als Schuld, die wie ein
  Fehler aussieht.** Ein Fehler wird gefunden. Ein Entwurf wird erweitert.

**Wer fremde Schuld mitigiert, uebernimmt sie.** Vorgefundene Schuld gehoert
dem, der sie erzeugt hat — solange sie sichtbar bleibt. Wer sie umdeutet,
umbiegt oder still verschwinden laesst, um mit ihr weiterarbeiten zu koennen,
traegt ihre Konsequenz fort und macht sie damit zu seiner eigenen. Das gilt in
beide Richtungen und ist an keiner davon harmlos:

- Ein Register, das den fehlenden Eigentuemer durch **eigene Autoritaet**
  ersetzt, behauptet etwas Falsches.
- Ein Register, das den heimatlosen Eintrag **stillschweigend weglaesst**, ist
  unvollstaendig — und erfuellt damit die Funktion nicht mehr, fuer die es
  existiert.

Beides traegt fort. Zulaessig ist nur, den fehlenden Eigentuemer **herzustellen**
— oder die Luecke unveraendert sichtbar zu lassen und entscheidungsreif zu
melden (siehe „FEHLENDES BESCHAFFEN STATT UMGEHEN"). Beruehren ist keine
Uebernahme; **mitigieren** ist es.

Belegte Anlassfaelle (2026-08-02, ein Tag, ein Repository): der Legacy-Port
`9080`, den niemand durch den Installer gezogen hatte — bezahlt mit einer
gescheiterten Fremdinstallation; der Mutex-Vertrag, den FK-78 seit jeher zusagte
und den der Code nie einloeste — bezahlt mit vier Reviewrunden und sieben
Defekten, darunter ein Safety-Defekt; eine Pooling-Strategie ohne Eigentuemer —
bezahlt mit sechs abgenommenen Storys auf falscher Bemessungsgrundlage; ein
Erstzugang, den nur Tests herstellten — bezahlt damit, dass AK3 nicht
installierbar war und es ein Dritter gemerkt hat. Keiner dieser Faelle hat bei
seiner Entstehung wehgetan.

### KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS (PO-Grundregel)

**Es gibt kein einziges produktives Projekt mit AK3.** Nichts ist im Einsatz,
niemand hat einen alten Stand, den es zu schonen gaebe. Jede Form von
Kompatibilitaet schuetzt damit **niemanden** — sie erzeugt nur Schuld und einen
zweiten Pfad, den ab sofort jeder mitlesen, mitpflegen und mitpruefen muss.

**Verboten ist nicht nur der Bau, sondern schon die Ueberlegung.** Wer anfaengt,
ueber Migrationspfade, sanfte Uebergaenge oder Rueckwaertsvertraeglichkeit
nachzudenken, ist bereits auf dem falschen Weg und hoert dort auf.

Konkret verboten — die Liste ist beispielhaft, nicht abschliessend:

- Deprecated-Aliase, Compat-Kommandos, „Legacy"-Flags und Uebergangs-Defaults
- Re-Export-Fassaden und Shims, die alte Import- oder Aufrufpfade am Leben halten
- doppeltes Lesen von altem UND neuem Format, Versionsweichen im Code
- alte Ports, Pfade, Feld- oder Schluesselnamen, die „noch funktionieren sollen"
- `# deprecated`, `# legacy`, `# kept for compatibility` als Begruendung, etwas
  stehen zu lassen

**Wer eine solche Stelle findet, entfernt sie** — mitsamt allem, was nur ihretwegen
existiert. Sie zu dokumentieren, zu markieren oder in eine Folgestory zu schieben
ist keine Erledigung. Umbenennen, verschieben, loeschen: der Schnitt wird an einer
Stelle gemacht, nicht an zweien nacheinander.

Belegter Anlassfall (2026-08-02): Der Compat-Alias `serve-control-plane` hielt den
Legacy-Port `9080` am Leben. Die Portmigration auf `9702` erreichte den Installer
nie — **jede frische Installation schrieb eine `control-plane.json`, die auf einen
Port zeigte, auf dem nichts lauscht.** Die Kompatibilitaetsschicht hat nichts
geschuetzt und genau den Fehler erzeugt, gegen den sie angeblich half.

### FIX THE MODEL, NOT THE SYMPTOM
Die v2-Erfahrung ist hier lehrreich: Fehler entstehen oft durch unklare Ownership, implizite Datenfluesse und versteckte Zustandskopien. Deshalb gilt:

- Keine zweite operative Wahrheit neben dem definierten State-/Artefaktmodell aufbauen.
- Keine "schnellen" Schattenfelder, Hilfsdateien oder Seitentabellen einfuehren, wenn dafuer bereits ein fachlicher Owner existiert.
- Keine neue Imperativsteuerung in einer Zentraldatei hochziehen, wenn Workflow, Stage oder Phase fachlich bereits modelliert ist.

### SINGLE SOURCE OF TRUTH IST PFLICHT

- Deployte Zielprojekt-Dateien existieren genau einmal unter `src/agentkit/bundles/target_project/`.
- Produktionscode liegt nur unter `src/agentkit/`.
- `src/agentkit/` ist Deployment-Unit-first: `backend/`, `frontend/`, `harness_client/`, `integration_clients/`, `bundles/`.
- `bundles/` enthaelt paketierte Skills, Prompts und Zielprojekt-Assets, aber keine Laufzeitdaten.
- `var/` ist ephemer und niemals fachliche Wahrheit.
- GitHub ist ausschliesslich Code-Backend (Branch/Worktree/Merge), keine Story-Verwaltung und keine Issue-Eingabe in das Setup. AK3 fuehrt die User-Story selbst (`StoryContext.story_id`); die operative Wahrheit ist der autoritative Snapshot/State des Runs.

### FAIL-CLOSED
Unklare oder unvollstaendige Zustaende werden nicht grosszuegig toleriert.

- Fehlende Artefakte, ungueltige Envelopes, unbekannte Stage-IDs oder inkonsistente Producer sind Fehler.
- Fehlende externe Systeme, kaputte Konfiguration oder verletzte Vorbedingungen werden nicht wegerklaert.
- Warnungen sind keine Dekoration. Root Cause analysieren und beheben.

### SEVERITY-SEMANTIK

Drei Stufen, klar abgegrenzt:

- **PASS** — fehlerfrei, kein Handlungsauftrag.
- **WARNING** — Handlungsauftrag mit aufschiebender Wirkung. Etwas muss
  gemacht werden, aber nicht sofort. Ein Warning darf **nicht** ignoriert
  oder weggeklickt werden. Wer einen Warning erzeugt oder erbt, hat die
  Pflicht, ihn aktiv an den Auftraggeber zu spiegeln mit der Frage „wie
  wollen wir hier vorgehen". Stilles Liegenlassen ist Verstoss gegen
  ZERO DEBT.
- **ERROR** — Handlungsauftrag ohne aufschiebende Wirkung. Sofort
  beheben. Keine Bypässe, keine Workarounds.

Nicht jeder Befund braucht einen Warning-Pfad. Wo aufschiebbares Handeln
in der Praxis nicht passiert (Erfahrung: Warnings gehen unter), ist
ERROR die richtige Wahl. Ein Befund, fuer den niemand spaeter Zeit
bekommt, ist im Effekt ein ignorierter Befund.

### NO ERROR BYPASSING

- Bei Test-, Build-, Lint-, Typ- oder Guard-Fehlern wird die Ursache behoben.
- Keine Umgehungspfade, die Validierung, Guards oder Stage-Pruefungen aushebeln.
- Keine heimlichen Fallbacks auf schlechtere Datenqualitaet oder weichere Regeln.

### MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL
Mocks und Stubs sind nur erlaubt, wenn

1. der User sie explizit verlangt oder
2. ein isolierter Unit-Test technisch sonst nicht moeglich ist.

Auch dann nur minimal und begruendet. Standardfall sind echte Komponenten, echte Artefakte, echte Integrationspfade.

### STRUKTURREGELN DES REPOS SIND VERBINDLICH

- Keine neuen Top-Level-Verzeichnisse ohne User-Consent.
- Keine Zielprojekt-Struktur im Repo-Root spiegeln.
- Keine losen Python-Dateien im Root.
- Keine zirkulaeren Abhaengigkeiten.
- Module entlang fachlicher Verantwortungen schneiden, nicht entlang kurzfristiger Implementierungsbequemlichkeit.

### WORKFLOW- UND STATE-DISZIPLIN

- Workflow-Logik gehoert in `pipeline/` und deren fachliche Untereinheiten, nicht in neue God-Services.
- Story-Typ-Routing, Stage-Geltung und Guard-/Gate-Regeln werden typisiert modelliert, nicht in String-/Flag-Kaskaden versteckt.
- Artefakte brauchen klaren Producer und klaren Owner.
- QA-Artefakte sind geschuetzt; Worker duerfen ihre eigenen QA-Ergebnisse nicht manipulieren.

## Work Modes

Drei exklusive Arbeitsmodi pro Aufgabe:

- **Worker**: selbst umsetzen, optional kleine Sub-Tasks delegieren
- **Orchestrator**: koordinieren, aber nicht nebenbei die Facharbeit selbst miterledigen
- **Council-Orchestrator** (nur Konzeptarbeit im Concept-Incubator, DK-16/FK-78):
  moderieren, Konvergenz bewerten, synthetisieren und promoten. Schreibt kein
  eigenes konkurrierendes Proposal und bezieht in Moderationsphasen keine
  inhaltliche Partei-Position; seine einzige Facharbeit ist Integrations-/
  Synthesearbeit nach vollstaendiger Claim-Inventur plus die mechanisch
  geprüfte Promotion.

Nicht mischen. Rollentrennung ist ein fachliches und technisches Prinzip von AgentKit 3.

### Sub-Agent Rules

- Erste Zeile jedes Sub-Agent-Auftrags: `Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.`
- Sub-Agents bekommen alle relevanten Referenzen, Pfade und Erfolgskriterien.
- Kein "done" ohne Beleg: Diff, Tests, Artefakte, Logs oder andere pruefbare Evidenz.
- Kleine, verifizierbare Aufgaben schneiden. Keine God-Tasks.
- Ergebnisse aktiv pruefen, nicht blind uebernehmen.

### DEFINITION OF DONE: CODEX-REVIEW BIS ZUM ABBRUCHKRITERIUM (PO-Grundregel)

Ein Arbeitsschritt ist **nicht** fertig, weil er funktioniert. Er ist fertig,
wenn ein unabhaengiges Codex-Review ihn freigegeben hat. Eigene Verifikation —
volle Suite, Lint, Typen, Gates, Lastnachweise — ist Voraussetzung, nicht
Ersatz. Sie belegt "es funktioniert", nie "es ist der richtige Schnitt".

Das Review laeuft in **Runden**, read-only, auf dem tatsaechlichen Stand:

1. Vorlegen mit benannten Pruefachsen (inklusive der eigenen Zweifel) und der
   ausdruecklichen Aufforderung, darueber hinauszugehen.
2. Befunde an der **Wurzel** beheben — kein Symptomfix, keine Unterdrueckung.
3. **Erneut vorlegen.** Behobene Findings sind kein Abschluss. Wer nach
   "5 Majors behoben" aufhoert, hat die Regel gebrochen.

**Abbruchkriterien — nur diese beiden:**

- Codex findet nichts Substanzielles mehr und sagt das explizit, nachdem es die
  Arbeit in jeder Dimension geprueft hat, **oder**
- die verbleibenden Befunde sind nachweislich formale Kleinigkeiten, deren
  erneute Vorlage keinen Erkenntnisgewinn mehr braechte. Diese Feststellung ist
  zu **begruenden**, nicht zu behaupten, und die Befunde sind zu benennen.

Erst dann darf `status: done` gesetzt, ein Abschlussbericht geschrieben oder
"fertig" gemeldet werden. Ein gruener CI-Lauf ist kein Abbruchkriterium.

Diese Regel ist eine PO-Grundregel und gilt fuer jeden Arbeitsschritt, nicht
nur fuer Storys. Sie steht hier, damit sie eine Kontext-Compaction ueberlebt.

## Arbeitsdisziplin

### Feasibility zuerst
Vor Codeaenderungen:

1. relevante Konzepte/Guardrails identifizieren
2. Ist-Zustand lesen
3. Delta zum Zielbild bestimmen
4. Design-Entscheidung treffen
5. erst dann implementieren

Wenn die notwendigen Informationen fehlen oder ein Konzeptkonflikt vorliegt: stoppen und explizit machen.

### Konzepttreue ist Pflicht
Alle Aenderungen muessen mit `concept/` und `PROJECT_STRUCTURE.md` vereinbar sein.

- Konflikt mit Fach- oder Technikkonzept: hart stoppen, Konflikt benennen, keine implizite Abweichung implementieren.
- Bestehenden Code, der dem Zielbild widerspricht, nicht durch neue Workarounds stabilisieren; stattdessen am Zielbild ausrichten.

### FEHLENDES BESCHAFFEN STATT UMGEHEN
Fehlt ein Werkzeug, ein Paket, ein Dienst oder eine Image-Anpassung, wird das **nicht** durch Eigenbau, schwaechere Tests oder einen verengten Entwurf umgangen. Es wird entscheidungsreif vorgelegt:

1. **Was** fehlt — Paket + exakter Version-Pin + Lizenz, bzw. Image/Dienst + konkrete Aenderung.
2. **Warum** es die richtige Wahl ist — was es bringt, was ohne es schlechter oder unmoeglich wird.
3. **Welche Nachteile** es ehrlich hat — Dependency-Oberflaeche, transitive Abhaengigkeiten, Wartung, Plattformrisiko. Gibt es keine nennenswerten, wird das klar gesagt und nicht kuenstlich ausbalanciert.
4. Die **explizite Frage**, ob geladen und integriert werden soll.

Der Auftraggeber hat Administratorrechte und die Docker-Images in der Hand; Beschaffung ist moeglich. Selbst installieren ohne Freigabe bleibt untersagt.

Kann ein Akzeptanzkriterium ohne die fehlende Sache **nicht ehrlich bewiesen** werden, ist das explizit zu melden. Ein schwaecherer, gruen aussehender Test ist ein Guardrail-Verstoss, kein Kompromiss.

### Anti-Loop
Nach zwei gescheiterten Versuchen mit derselben Methode:

- Methode wechseln
- Ursache bottom-up isolieren
- Invarianten, Unit-Tests und Phasengrenzen separat pruefen

Ratespiel ist hier kein akzeptabler Modus.

## Python Coding Rules

### Code Quality

- `from __future__ import annotations` in jedem Modul
- vollstaendige Type Hints
- `mypy` strict ohne unerklaerte `type: ignore`
- `ruff` ohne unerklaerte `noqa`
- Pydantic v2 fuer Konfigurationen, Artefaktmodelle und andere strukturierte Daten
- Google-Style-Docstrings fuer oeffentliche Klassen/Funktionen
- `snake_case` fuer Funktionen/Variablen/Module, `PascalCase` fuer Klassen
- **Englisch verbindlich (Guardrail ARCH-55, so verbindlich wie die Sonar-Regeln):** Quellcode, Bezeichner, Datenmodelle, Wire-/JSON-Keys, Schema-Felder, DB-Spalten, Event-/API-Contracts und Code-Kommentare ausnahmslos englisch. Verlangt ein Fachkonzept deutsche Keys/Feldnamen, ist das Fachkonzept englisch anzupassen, nicht der Code. Einzige Ausnahme: deutschsprachige UI-Label-Lokalisierung an der Oberflaeche + zugehoerige Resource-Bundles/Uebersetzungseintraege. Fach-/Konzept-Prosa darf weiter deutsch sein.

### Architektur

- Produktionscode nur in `src/agentkit/`
- Backend-Fachlogik unter `src/agentkit/backend/`
- Produktiver Frontend-Code unter `src/agentkit/frontend/app/`
- Harness-/ProjectEdge-Code unter `src/agentkit/harness_client/`
- Drittsystem-Clients unter `src/agentkit/integration_clients/`
- Fachlogik nicht in `integration_clients/` oder `utils/`
- `integration_clients/` bleiben duenne Adapter
- `bundles/` bleibt frei von Runtime-State und Backend-Fachlogik
- Orchestrierung und Geschaeftslogik trennen
- Seiteneffekte an die Raender, Kernlogik moeglichst rein
- Immutability und unidirektionaler Datenfluss als Default

### State und Artefakte

- Keine neuen ungetypten Zustandsdateien ohne klares Fachmodell
- Kein manueller Hidden-State ausserhalb der dafuer vorgesehenen Modelle/Artefakte
- Artefakt-Envelopes, Producer-Registry und Stage-Definitionen respektieren
- Telemetrie-/State-Formate nur aendern, wenn die Konzeptbasis und die Contract-/Golden-Tests mitgezogen werden

## Tests

### Pflichtregeln

- Neue Business-Logik braucht Unit-Tests.
- Bugfix braucht reproduzierenden Test.
- Pipeline-Schritte muessen Negativpfade an Phasengrenzen beweisen.
- Tests duerfen produktiven Pipeline-State nicht als Abkuerzung manuell zusammenfantasieren, wenn er im echten Lauf durch Vorgaengerphasen erzeugt wird.
- Gueltige und ungueltige Uebergaenge des Workflow-Graphs muessen verprobt werden.

### REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN (PO-Grundregel)

**Ein Fremdsystem-Vertrag gilt erst als abgenommen, wenn der zugehoerige
Checkpoint einmal gegen das laufende System gelaufen ist.** Gruene Unit-Tests
sind Voraussetzung, niemals Nachweis.

Der Grund ist strukturell, nicht organisatorisch: Eine Testsuite kann interne
Konsistenz und Durchsetzung beweisen. **Uebereinstimmung mit der Welt kann sie
nicht beweisen** — sie leitet Eingabe UND Erwartung aus derselben Annahme im
Repo ab. Ist die Annahme falsch, sind die Tests gruen und die Wirklichkeit ist
eine andere. Mehr Tests derselben Sorte aendern daran nichts.

Das gilt ausdruecklich auch fuer sorgfaeltig gebaute Negativpfade: Ein Test, der
einen abweichenden Fremdwert als Verletzung zurueckweist, ist gruendlich ueber
den **Mechanismus** und blind ueber den **Wert**. Er fragt nie, ob der gepinnte
Wert derjenige ist, den das reale Gegenueber fuehrt.

Daraus folgt fuer jede Story mit Fremdsystem-Vertrag — VektorDB, State-Backend,
Harness, CI, Konzept-Compiler, jedes Drittsystem:

- Der Live-Lauf des Checkpoints gegen das echte Gegenueber ist **Abnahme-
  kriterium**, nicht Opt-in. Ohne ihn ist die Story nicht fertig.
- Faellt der Live-Lauf aus (Dienst nicht verfuegbar, Umgebung im Umbau), ist das
  eine **benannte Luecke** mit Grund — nie „gruen", nie stillschweigend.
- Werte, die ein Fremdsystem mitbestimmt (Modelle, Schemata, Ports, Endpunkte,
  Versionen), brauchen einen benannten Eigentaemer im Konzept. Ein Wert, der nur
  im Code lebt, driftet — und niemand ist zustaendig, es zu merken.

Belegter Anlassfall (2026-08-02): Sechs VektorDB-Storys sind abgenommen worden,
ohne dass der Installer je gegen ein laufendes Weaviate lief. Die erste echte
Installation zeigte sofort eine falsch gepinnte Pooling-Strategie —
`masked_mean` statt `cls`, der Wert des Vorgaengermodells, seit dem Wechsel auf
bge-m3 veraltet. Jede Einbettung waere still falsch gerechnet worden. Die
Drift-Erkennung selbst funktionierte einwandfrei und war sogar negativ getestet;
sie setzte nur den falschen Wert durch. Kein Test der Welt haette das gefunden,
nur der Lauf gegen das reale System.

### Testebenen

- `tests/unit/` fuer reine Logik
- `tests/integration/` fuer szenariobasierte Zielprojekt- und Dateisystemablaeufe
- `tests/contract/` fuer Stabilitaet von Schemas, Snapshots, Prompts und Manifests
- `tests/e2e/` nur opt-in, nie Standard-CI

### Coverage

- Mindestgrenze: 85%
- Eine Aenderung, die die Gesamtabdeckung unter die Schwelle zieht, ist blockierend.

## Operations

### Standard nach Codeaenderungen

**WICHTIG: Alle Python-Befehle ausschliesslich ueber das Projekt-venv ausfuehren.**
AK3 und AK2 teilen denselben Package-Namen `agentkit`. Globale Installs ueberschreiben
AK2 und zerstoeren dessen Claude-Code-Hooks. Niemals `pip install` ohne venv-Prefix.

- `.venv\Scripts\python -m pip install -e ".[dev]"`
- `.venv\Scripts\python -m pytest`

Wenn oeffentliche Schnittstellen, Kernzustandsmodelle oder breit wirksame Pipeline-Logik geaendert wurden, ist nicht nur ein schmaler Ausschnitt zu pruefen.

### Weitere Qualitaetschecks

- `.venv\Scripts\python -m ruff check src tests`
- `.venv\Scripts\python -m mypy src`

### Temp- und Laufzeitdaten

- Ephemere Dateien nach `var/` oder Test-`tmp_path`
- Keine generierten Dateien in `tests/fixtures/`
- Keine temporären Hilfsartefakte im Repo herumliegen lassen

## Mindset

### Prioritaet
User instruction > konkrete Projektregeln in diesem Dokument > kanonische Konzepte/Strukturvorgaben > allgemeine Heuristiken.

### Zielbild
AgentKit 3 ist explizit der Gegenentwurf zu v2:

- klare fachliche Schnitte statt God-Files
- definierte State-Owner statt JSON-Wildwuchs
- deterministische Orchestrierung statt impliziter Ablaufmagie
- typisierte Artefakte und Stages statt loser String-Konventionen

Jede Aenderung muss dieses Zielbild verstaerken, nicht unterlaufen.

### Was gute Arbeit in diesem Repo bedeutet

- fachliche Verantwortung klarer machen, nicht diffuser
- Determinismus ausbauen, nicht durch agentische Sonderpfade erodieren
- Tests an echten Phasengrenzen fuehren, nicht an kuenstlich gebastelten Ersatz-Zustaenden
- bestehende Guardrails ernst nehmen und bei Konflikten nicht kreativ umgehen

Wenn unklar ist, wo etwas hingehoert, ist das ein Architekturproblem, kein Freibrief fuer ad-hoc Code.
