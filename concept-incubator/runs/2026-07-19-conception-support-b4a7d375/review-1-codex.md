# Review 1 (Codex, job-75972bf3) — Findings-Fassung

Bootstrap-Sanitisierung: Das vollstaendige Werkzeug-Transkript wurde
entfernt (Datenklassen-Policy FK-78 §78.13); versioniert ist nur die
Findings-/Urteilsfassung. Declassification: Bootstrap-Receipt im
Decision Record 2026-07-19-concept-incubation-support (einmalig,
nicht praezedenzbildend).

## Findings

1. **P0 — Die ATOM-Adaption kann Verlust gerade nicht erkennen**

   **Beleg:** Das Design atomisiert ausschließlich die finale Synthese und bindet primär deren Digest ([DESIGN.md §4](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:220)). ATOM-01 verlangt dagegen Genealogie, direkte Endkanten, Source-/Normative-Coverage und Restkanten über alle Synthesestufen ([ATOM-01 §4](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:81), [§5](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:110), [§9.2](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:368)). Im realen Audit waren eigene Residual-Traceabilities nötig, weil Fable/v2 Inhalte aus Codex-, GLM- und Grok-Proposals verloren hatte ([Audit README](/P:/_private-img2img/var/pi-fachkonzept/proposal/codex/migration-audit/README.md:82), insbesondere Zeilen 102–107).

   **Begründung:** Was bereits vor der Atomisierung aus der Synthese gefallen ist, existiert für den Checker nicht mehr. Genau dadurch kann „die Hälfte vergessen“ werden, während Atomregister und Digests vollständig grün sind. Zusätzlich widersprechen sich „genau ein Autoritätsziel“ und `COVERED_SPLIT`, das mehrere Ziele benötigt.

   **Empfehlung:** Für große Promotionen müssen Briefing, alle Proposal-Fassungen, Synthesen, Dissenskarte und PO-Entscheidungen als eingefrorenes Source-Set inventarisiert werden. Notwendig sind Source Register, Genealogiekanten, Source Coverage und ein Claim-Ledger `source atom → synthesis disposition → normative targets`. Minderheits- und Zwischenclaims brauchen direkte Restkanten gegen Current; erst danach darf die finale Synthese als Promotionskandidat gelten.

2. **P0 — Es fehlt ein tragfähiger Assertion-/Projection-Authority-Vertrag**

   **Beleg:** Der aktuelle AK3-Meta-Contract sagt pauschal, bei maschinenprüfbarer Semantik gewinne Formal ([meta-contract §2](/T:/codebase/claude-agentkit3/concept/formal-spec/00_meta/meta-contract.md:24)). Intimas spätere Korrektur sagt ausdrücklich: Ein angenommener Entscheid setzt das Ziel, aber jede fehlende, stale oder widersprechende Projektion führt zu `blocked_projection`; weder Prosa noch Formal gewinnt still ([assertion-authority §4–5](/P:/_private-img2img/concept/_meta/assertion-authority.md:141)). Das Design übernimmt einige `required_*`-Listen, aber nicht `affected_scope_ids`, `required_concept_ids`, `required_support_paths`, Blocker, Äquivalenz-Receipts oder die Statussemantik ([DESIGN.md:236](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:236)).

   **Begründung:** Eine neue Decision könnte als promotet gelten, obwohl Formal noch Altsemantik trägt. Umgekehrt könnte stale Formal die frisch entschiedene Prosa formal „überstimmen“. Das ist genau der subtile Fehler, den der Intima-Vertrag geschlossen hat.

   **Empfehlung:** Vor FK-78 braucht AK3 einen eigenen Assertion-/Projection-Contract oder eine entsprechende Erweiterung des Formal-Meta-Contracts: stabile Assertion-/Scope-IDs, `equivalent|disagrees|stale|blocked_missing_target`, `blocked_projection`, vollständige `required_*`-Mengen und reviewgebundene Projection Receipts. „Formal wins“ muss durch „disagreement blocks“ ersetzt oder präzisiert werden.

3. **P0 — Die Zielprojekt-Closure verlangt Werkzeuge, die v1 ausdrücklich nicht ausliefert**

   **Beleg:** Die Promotion soll zusätzlich W1–W4 und den Formal-Compiler ausführen ([DESIGN.md:243](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:243)). Gleichzeitig liefert v1 nur Inkubator-Checker aus; der vollständige Konsistenz-Toolstack wird vertagt ([DESIGN.md §8](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:343)). W2 und W3 sind zudem LLM-/Hub-gestützt, nicht deterministische stdlib-Checks ([W2](/T:/codebase/claude-agentkit3/scripts/ci/check_concept_authority_prose.py:37), [W3](/T:/codebase/claude-agentkit3/scripts/ci/check_concept_scope_consistency.py:28)).

   **Begründung:** Im Zielprojekt kann `check promotion` seinen eigenen Closure-Vertrag nicht erfüllen. Ein `INCOMPLETE_CHECK_SET` wäre dann der Normalfall, nicht eine Ausnahme. Damit ist Q1 keine aufschiebbare Produktoption, sondern ein Designblocker.

   **Empfehlung:** v1 muss mindestens Frontmatter-/Authority-Graph, W1-Referenzintegrität, Formal-Compile, Decision-Record-Gate und Promotionsschema als deploybare Toolchain enthalten. W2/W3 sind als gesonderte semantische Review-Gates mit versionierten Receipts zu modellieren; fehlender Hub oder unvollständiger Sweep blockiert die betroffenen Scopes. Der Checker darf diese nicht als „deterministisch“ ausgeben.

4. **P0 — Das Rollenmodell verletzt die aktuelle AK3-Work-Mode-Norm**

   **Beleg:** AK3 definiert Worker und Orchestrator als exklusive Modi; der Orchestrator koordiniert und erledigt nicht gleichzeitig Facharbeit ([CLAUDE.md Work Modes](/T:/codebase/claude-agentkit3/CLAUDE.md:146)). Das Design weist demselben Orchestrator Moderation, inhaltliche Synthese und normative Promotion zu und behauptet dennoch, dies sei dieselbe Rollendisziplin ([DESIGN.md §3.3](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:160)).

   **Begründung:** Synthese und das Schreiben normativer Konzepte sind Facharbeit, nicht bloße Koordination. Der PO-Auftrag kann diese neue Rolle legitimieren, aber das Design löst den Normkonflikt nicht und plant auch keine entsprechende Änderung der Work-Mode-Regel.

   **Empfehlung:** Einen normativen `CouncilOrchestrator`-Modus einführen: keine unabhängige Proposal-Position, aber explizite Integrations-/Synthese-Ownership nach vollständigem Claim-Ledger. `CLAUDE.md`, Rollenformalismus und Governance müssen über den Decision Record angepasst werden. Alternativ müsste ein eigener Synthesizer-Worker schreiben; das wäre allerdings eine Abweichung von der PO-Rollenvorgabe.

5. **P1 — Lifecycle, Crash- und Resume-Semantik sind nicht total**

   **Beleg:** Das Design nennt nur eine lineare Zustandsfolge und erklärt `RUN.json + journal.md` gemeinsam zum Wiederaufnahme-Cursor ([DESIGN.md §3.4](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:170)). ATOM-01 fordert dagegen genau einen aktiven Cursor sowie persistierte Phase, nächste Aktion, Coverage, Findings und Drifts ([ATOM-01 §13](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:556)). Für Lifecycles verlangt es unter anderem Duplicate, Reorder, Timeout, Crash vor/nach Durable Commit, Resume und konkurrierende Commands ([ATOM-01 §10.2](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:414)).

   **Begründung:** Nicht definiert sind etwa: Crash nach Worker-Dispatch vor Receipt, teilweise fertige Runde, verlorene Hub-Lease, wiederholtes Resume, Timeout eines Teilnehmers, erneute Synthese nach PO-Änderung, Checkerfehler während Promotion oder Abbruch mitten im normativen Diff. Externe Session-IDs und Versand-/Empfangsstände fehlen vollständig.

   **Empfehlung:** `RUN.json` als einzigen autoritativen State definieren; Journal nur als Historie. State braucht Revision, Actor, Worker-/Session-Mapping, Prompt-/Input-Digests, Dispatch-/Receipt-Status je Teilnehmer und Runde, letzte abgeschlossene atomare Aktion und `next_action`. Formal zu modellieren sind auch `BLOCKED`, `RECHECK`, `PROMOTION_FAILED` und alle Abort-/Resume-Pfade.

6. **P1 — Parallelbetrieb, Mehrbenutzer und Drift sind ungeschützt**

   **Beleg:** Run-Identität ist lediglich `<date>-<slug>` ([DESIGN.md:141](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:141)); Locks, Writer-Leases, Revision/CAS, isolierte Worktrees und Base-Commit fehlen. ATOM-01 verlangt Hashdrift mit `RECHECK` und Adjudikation vor Abschluss ([ATOM-01 §14](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:576)). Das reale Promotionspaket verlangt isolierten Branch/Worktree und Hashprüfung vor jeder Welle ([PROMOTION-PACKAGE §2.1](/P:/_private-img2img/var/pi-fachkonzept/proposal/codex/migration-audit/PROMOTION-PACKAGE.md:26)).

   **Begründung:** Zwei User können denselben Slug wählen, zwei Orchestratoren denselben State überschreiben, und ein Lauf kann auf einer währenddessen veränderten Konzeptwelt promoten. Vor-/Nach-Digests erst am Ende reichen dafür nicht.

   **Empfehlung:** UUID-basierte Run-ID, `base_revision`, vollständige Baseline-Dateimenge, Writer-Lease mit Fencing-Token, monotone State-Revision und atomare Replace-Writes. Promotion in isoliertem Worktree; vor Review, vor Mutation und vor Merge Hash-/Set-Recheck. Merge nur, wenn der Zielbranch noch auf der erwarteten Authority-Baseline steht.

7. **P1 — Der Großmaßstab ist prozessual und adressseitig nicht gelöst**

   **Beleg:** Worker sollen lediglich „relevante Anker“ vollständig lesen ([DESIGN.md:178](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:178)); es gibt keine Corpus-Inventur, Scope-Partitionierung, Coverage-Matrix oder redundante Zuständigkeit. Zugleich exportiert das Design AK3s zweistellige `DK-XX`-/`FK-XX`-IDs, deren aktueller Vertrag maximal 100 IDs pro Präfix zulässt ([FK-00 §23](/T:/codebase/claude-agentkit3/concept/technical-design/00_index.md:239)). Das reale Intima-Audit benötigte 201 Baseline-Dateien, 82 Quellen und 107 normative Einzelreviews ([Audit README](/P:/_private-img2img/var/pi-fachkonzept/proposal/codex/migration-audit/README.md:32)).

   **Begründung:** „Relevanz“ ist bei 2000+1000 Seiten bereits ein eigenes, fehleranfälliges Ergebnis. Ohne mechanische Inventur können ganze Dokumentfamilien unbemerkt außerhalb aller Worker-Pakete bleiben. Das ID-Schema skaliert ebenfalls nicht auf größere Konzeptkorpora.

   **Empfehlung:** Baseline-Inventur und Coverage-Plan vor Staffing; Partitionierung nach Authority-Scope/BC mit redundanter Reviewabdeckung und einem Cross-Scope-Integrationslauf. Sharded Kontextindizes statt eines monolithischen Index. Zielprojekt-IDs müssen versioniert und erweiterbar sein, etwa namespaced und mindestens drei-/vierstellig oder stabil-opaque; AK3s lokales `NN`-Schema darf nicht ungeprüft Blueprint-Norm werden.

8. **P1 — Der vorgeschlagene Skill-Baum ist mit FK-43 und dem implementierten Binder nicht kompatibel**

   **Beleg:** Das Design plant `claude/SKILL.md` und `codex/SKILL.md` mit Harness-Varianten im Manifest ([DESIGN.md §7](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:306)). FK-43 verlangt derzeit, dass beide Harness-Links auf dasselbe Bundle-Verzeichnis und denselben Single-Source-Inhalt zeigen; harnessspezifische Varianten entstehen nur durch Materialisierung einer neutralen Repräsentation ([FK-43 §43.4.1](/T:/codebase/claude-agentkit3/concept/technical-design/43_skills_system_task_automation.md:251)). Die Implementierung verlinkt tatsächlich denselben `bundle_root` für beide Harnesses ([top.py](/T:/codebase/claude-agentkit3/src/agentkit/backend/skills/top.py:414)); `variants` bezeichnet heute `CORE`/`ARE`, nicht den Harness.

   **Begründung:** In der beschriebenen Verzeichnisform findet der Harness am Bundle-Root keine kanonische `SKILL.md`. Der Installer besitzt keine Harness-Variant-Achse.

   **Empfehlung:** Für v1 entweder eine gemeinsame Root-`SKILL.md` mit harnessspezifischen Referenzdateien verwenden oder FK-43, Formal-Spec, Manifest und Binder ausdrücklich um eine zweite, von `profile` getrennte `harness_variant`-Achse erweitern. Die Varianten müssen aus einem neutralen Core generiert werden; zwei manuell gepflegte Treiber sind keine ausreichende Single-Source-Garantie.

9. **P1 — Die „Schema-Checker“ sind noch keine implementierbare Schemaspezifikation**

   **Beleg:** Kapitel 3 normiert `RUN.yaml` und `promotion-manifest.yaml`; Kapitel 5 korrigiert dies beiläufig auf JSON ([DESIGN.md:135](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:135), [DESIGN.md:251](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:251)). Konkrete Feldkataloge, Schema-Versionen, unbekannte-Felder-Regel, ID-/Locator-Grammatik und Migration fehlen.

   **Begründung:** Aus den vier CLI-Beschreibungen lässt sich kein eindeutiger Checker implementieren. Außerdem kann Software „jede wesentlich neue normative Aussage“ nicht deterministisch aus freier Prosa erkennen. Digests beweisen Identität, nicht semantische Äquivalenz.

   **Empfehlung:** Kanonische versionierte Schemas für Run, Participant, Round, Atom, Finding und Promotion Receipt definieren. Unknown fields fail-closed, stabile ID-Grammatiken, Pfad-Containment und Set-Gleichheiten festlegen. Normative Zielpassagen brauchen explizite Atom-/Decision-Anker; semantische Äquivalenz braucht ein versioniertes Reviewreceipt. Der Checker prüft Closure des Receipts, nicht eigenmächtig Bedeutung.

10. **P1 — Worker-Isolation und Datenabfluss zu Fremdmodellen sind ungeregelt**

   **Beleg:** Worker dürfen laut Tabelle weder `concept/` noch Promotion verändern, aber dafür existiert nur eine Prompt-Regel ([DESIGN.md:162](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:162)). Alle Proposal-Verzeichnisse liegen im gemeinsamen Workspace, obwohl Runde 1 fremde Proposals nicht sichtbar machen soll. Gleichzeitig dürfen externe Hersteller die normative Welt lesen. Intimas ATOM-Policy verbietet externes Senden von Quellen und fordert geschützte Evidenzorte ([ATOM-01 §17](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:652)).

   **Begründung:** Ein Worker kann versehentlich fremde Runde-1-Proposals lesen oder normative Dateien verändern. Für sensible/IP-behaftete Zielprojekte fehlt Egress-Klassifikation, Redaction und Zustimmung pro Modell.

   **Empfehlung:** Worker-spezifische isolierte Eingabe-/Ausgabe-Sandboxes und Writer-Ownership; Proposal-Dateien werden erst nach Round-Seal für Cross-Read freigegeben. Harness-Guards müssen Worker-Schreibzugriffe auf `concept/`, fremde Proposals und `promotion/` blockieren. Staffing muss neben dem Modell eine explizite Datenfreigabe, zulässige Quellenklassen und Egress-Policy abfragen. Fremde Proposals sind beim Cross-Read als untrusted data, nicht als Instruktionen zu behandeln.

11. **P1 — Der BC-Scope überlappt unzulässig mit `exploration-and-design`**

   **Beleg:** Das Design erklärt den Inkubator zum einzigen legitimen Ort jeder nichttrivialen Konzeptarbeit und will den bisherigen `_temp`-Pfad ersetzen ([DESIGN.md §3.1](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:125)). Zugleich soll die bestehende Pipeline unverändert bleiben ([DESIGN.md §8](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:343)). Der bestehende BC `exploration-and-design` besitzt bereits storybezogene Konzeptarbeit, `FineDesign` und `DesignFreeze` ([bounded-contexts.yaml](/T:/codebase/claude-agentkit3/concept/technical-design/_meta/bounded-contexts.yaml:34)).

   **Begründung:** Als BC ist `concept-incubation` grundsätzlich plausibel, aber nur für die Evolution des normativen Konzeptkorpus. Als Owner sämtlicher Konzeptarbeit würde er den bestehenden BC verdrängen und die behauptete Pipeline-Abgrenzung brechen.

   **Empfehlung:** Verantwortung scharf formulieren: `concept-incubation` besitzt corpusweite, vor-storyliche oder normative Konzept-Evolution und Promotion. `exploration-and-design` behält storylokales Fine Design. FK-78 braucht `defers_to`-/Excluded-Beziehungen zu exploration, agent-skills, harness-integration, governance und installation.

12. **P1 — `DEFERRED_BACKLOG` und `OPEN_MISSING` sind mit „CLOSED/promotet“ nicht sauber vereinbar**

   **Beleg:** Das Design erlaubt beide Dispositionen mit sichtbarem Anker, erklärt den Lauf aber nach grünem Closure-Check als promotet ([DESIGN.md:232](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:232)). Intimas Authority-Vertrag verlangt bei fehlenden Pflichtprojektionen `blocked_projection` ([assertion-authority §5](/P:/_private-img2img/concept/_meta/assertion-authority.md:159)). P6 verlangt zudem Rücksichtbarkeit aktiver Werkstattartefakte aus Normwelt oder Backlog ([Intima-Governance P6](/P:/_private-img2img/concept/_meta/konzept-konsistenz-governance.md:53)).

   **Begründung:** Administrative Run-Closure und fachlich vollständige Promotion werden vermischt. Ein Backlog-Link macht fehlende Semantik sichtbar, aber nicht promotiert.

   **Empfehlung:** Zwei Achsen modellieren: `run_status` und `projection_status`. Ein Lauf darf administrativ geschlossen werden, während betroffene Scopes `blocked_projection` bleiben. `PROMOTED` ist nur bei vollständiger Accepted-Atom-/Required-Set-Closure erlaubt. Backlog-Deferrals brauchen Owner, Termin/Trigger, Scope und geprüften Reverse-Link.

13. **P1 — „Inkubator standardmäßig versioniert“ ist als Sicherheitsdefault falsch**

   **Beleg:** Das Design empfiehlt Versionierung mit Opt-out für sensible Korpora ([DESIGN.md:119](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:119)). Die Herkunftsmethodik hält gerade Rohinterviews, private Profile und Evidenz aus der Versionsverwaltung heraus ([ATOM-01 §17](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:652)); Intimas Werkstatt-Manifest enthält zahlreiche sensible Rohmaterialklassen ([INDEX.md](/P:/_private-img2img/var/pi-fachkonzept/INDEX.md:13)).

   **Begründung:** Ein vergessener Opt-out ist irreversibel, sobald Inhalte in Git-Historie oder Remote gelangen. Das Verfahren soll für beliebige Zielprojekte sicher sein.

   **Empfehlung:** Geteilte Policy: Schemas, Templates, sanitized Briefings, Entscheidungen und Receipts dürfen standardmäßig versioniert sein; Rohquellen, Interviews, Modelltranskripte und sensible Proposals sind standardmäßig lokal/ignored. FRAMING muss eine Datenklasse festlegen; unklassifizierte Inhalte fail-closed nicht committen.

14. **P2 — Checker-Platzierung ist richtig, die stdlib-Begründung aber faktisch falsch**

   **Beleg:** `bundles/target_project/tools/agentkit/` ist laut Strukturvertrag der korrekte SSOT-Ort für deploytes Zielprojekt-Tooling ([PROJECT_STRUCTURE.md](/T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md:261)). Das angeführte `projectedge.py` ist jedoch nicht stdlib-only; es importiert Pydantic und zahlreiche AgentKit-Module ([projectedge.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/projectedge.py:18)).

   **Begründung:** Die Platzierungsentscheidung bleibt gut. Nur das Präzedenzargument trägt nicht. Ein handgeschriebener stdlib-Schemavalidator kann zudem selbst zur zweiten Schemawahrheit werden.

   **Empfehlung:** stdlib-only als bewussten Standalone-Vertrag begründen und über gemeinsame kanonische Schemafixtures testen. Alternativ eine kleine, explizit mitdeployerbare Validator-Abhängigkeit verwenden. Keine Behauptung, `projectedge.py` belege Abhängigkeitsfreiheit.

15. **P2 — Für kleine normative Änderungen ist das Verfahren überdimensioniert**

   **Beleg:** Jeder normative Gehalt soll mindestens einen Lauf samt Atomregister erhalten ([DESIGN.md §3.6](/T:/codebase/claude-agentkit3/var/concept-incubator/conception-support/DESIGN.md:212)). ATOM-01 begrenzt das Vollverfahren dagegen auf große, mehrschichtige, ersetzende oder explizit erschöpfende Änderungen ([ATOM-01 §1](/P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:29)).

   **Begründung:** Das Design ist gleichzeitig zu schwach für Großmigrationen und zu schwer für einen kleinen, single-scope normativen Satz. Das lädt zu Scheinerfüllung durch Minimalruns ein.

   **Empfehlung:** Drei Profile definieren:

   - `DIRECT_GOVERNED_CHANGE`: kleiner, eindeutiger Scope; W4/Impact-Sweep, kein Council.
   - `LIGHT_INCUBATION`: echte Unsicherheit, begrenzter Scope; ein bis zwei Worker und Claim-Ledger.
   - `FULL_ATOM`: alle ATOM-Trigger, vollständige Baseline/Genealogie/Coverage/Drift-Closure.

## Gesamturteil

**Rework nötig.** Das Design ist noch nicht „tragfähig mit Auflagen“, weil vier Punkte den Kernvertrag verletzen: Verlustfreiheit ist nicht beweisbar, Authority-/Projection-Semantik fehlt, die Zielprojekt-Gates sind nicht ausführbar und das Rollenmodell widerspricht der aktuellen AK3-Norm.

Die offenen PO-Fragen würde ich so beantworten:

- **Q1:** Nein, Inkubator-Checker allein reichen für v1 nicht. Der deterministische Konzept-Toolstack muss mitgeliefert werden; W2/W3 brauchen separat auditierte semantische Receipts.
- **Q2:** Kein pauschales „versioniert“. Prozessmetadaten ja, sensible Inhalte default lokal.
- **Q3:** Ja, voller formaler Kontext. Lifecycle, Concurrency, Crash und Promotion sind klar formalisierungspflichtig.
- **Q4:** Ein logischer Skill mit Rollen-Gate ist tragfähig. Die Harness-Varianten müssen aber aus einem neutralen Core materialisiert oder durch eine neue Binder-Achse unterstützt werden.

## Explizite Zustimmung

Diesen Punkten stimme ich ausdrücklich zu:

- `concept-incubator/` als kanonischer Top-Level-Name und klare Trennung von `concept/`.
- Der normative Layer ist nicht der Arbeitsordner.
- Unabhängige Proposal-Runde 1, danach Cross-Read und Folgerunden.
- Keine Zwangskonvergenz; `Stabil-Kontrovers` und `Spannungsfeld` bleiben sichtbar.
- User entscheidet über die Modellbesetzung; kein stiller Default.
- Orchestrator schreibt kein eigenes konkurrierendes Proposal.
- Ein eigener BC `concept-incubation` ist richtig, sofern er auf normative Corpus-Evolution begrenzt wird.
- Voller formaler Kontext für Run, Atom, Promotion und Lifecycle.
- Checker unter `bundles/target_project/tools/agentkit/`.
- JSON/TSV, read-only Checker, fail-closed und ERROR-only.
- Digest-Bindung, Reverse Trace und zusätzliche bestehende Konzept-Gates als Grundrichtung.
- Shared Process Core und dünne harnessspezifische Treiber als Single-Source-Zielbild.
- Kein Backend-/Control-Plane-Ausbau für v1; Skills, Dateisystem und Checker sind ein sinnvoller erster Produktschnitt.

Es wurden im Read-only-Review keine Dateien verändert und keine Jenkins-/Sonar-Läufe ausgelöst.
_turn completed: completed_
_lifecycle: state-changed_
_lifecycle: finalized_

