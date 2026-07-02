# AG3-159 — Konzept-Authority-Prosa-Prüfung (W2): LLM-Bewertung + deterministische Policy — normative Aussagen je Chunk klassifizieren, Scope-Abgleich gegen Authority/defers_to, nightly + vor Konzept-Merges

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-158] — **SEQUENZ-Kante** nach META §7-Fahrplan
  (Punkt 2: W4 vor Punkt 3: W2), **keine technische Abhängigkeit**: W2
  braucht weder das W4-Gate noch das W1-Gate; die Kante ordnet nur die
  Umsetzungsreihenfolge des Strangs.
- **unblocks:** [AG3-160] — hier zusätzlich **technisch begründet**: W3
  setzt die W2-Infrastruktur voraus (Chunk-Klassifikation,
  Baseline-Mechanik; META §5/W3 und §7 Punkt 4).
- **Quell-Konzept:** META-CONCEPT-CONSISTENCY
  (`concept/_meta/konzept-konsistenz-governance.md`) §5/W2
  (Spezifikation), §5-Vorspann („LLM nur als Bewertungsfunktion,
  Entscheidung deterministisch", analog Verify-Layer 2/FK-27), §3/P1+P2
  (Single-Assertion, Authority-Bindung von Prosa), §4
  (Severity-Zuordnung), §6 (Betriebsmodell: nightly + vor Konzept-Merges;
  Baselines nur begründet; Prompts/Modelle versioniert, Befunde
  idempotent), §7 (Fahrplan Punkt 3)
- **Herkunft:** Konzept-Konsistenz-Governance (META-Dokument, aktiv);
  PO-Freigabe 2026-07-02. Kein GAP-Nenner-Bezug — eigener Strang.

## Kontext / Problem

P2 (META §3) bindet Prosa an die Frontmatter-Zuständigkeiten: Ein
Dokument darf keine normativen Aussagen über Scopes treffen, über die es
keine `authority_over`-Authority und keine `defers_to`-Kante hat —
„nebenbei normieren" ist ein Verstoß, unabhängig von der inhaltlichen
Richtigkeit. W2 ist der Detektor für „ich weiß nicht, wonach ich suche":
Er findet die **unzuständige Behauptung**, ohne dass der Widerspruch
selbst semantisch gefunden werden muss (§5/W2). Ist-Zustand (verifiziert
2026-07-02):

- **Es existiert keine Prosa-Authority-Prüfung.** Die einzige
  einschlägige Bestandsmechanik ist der deterministische Lint L20
  (`scripts/ci/check_concept_frontmatter.py:652-698`): er erkennt
  normative Erwähnungen **glossierter interner Fremd-Terme** über einen
  Modalmarker-Regex (`NORMATIVE_MODAL_RE` :49-54) — nur für Terme, die in
  Glossaren stehen, nicht für beliebige normative Aussagen über Scopes.
  Chunks ohne Glossar-Term bleiben unsichtbar (genau die
  META-§1-Fehlerklasse: Tabellen-Halbsätze, Nebenbemerkungen).
- **Chunking existiert deterministisch im Repo:**
  `tools/concept_ingester/discovery.py` chunked den Korpus auf H2-Ebene
  (`_H2_RE` :42, `ConceptChunk` :56-66, `discover()` :353) und projiziert
  Registry-Metadaten in jeden Chunk (Modul-Docstring :1-11,
  `_load_domain_projection` :303). **Diese Quelle ist repo-lokal und
  deterministisch** — sie funktioniert ohne den externen Index.
- **Der semantische Konzept-Index ist ein externer Dienst:** Die
  Weaviate-Instanz (Default `127.0.0.1:9903`, Collection
  `Ak3ConceptChunk`; `tools/concept_ingester/config.py:36-40`) und der
  MCP-Server (`tools/concept_mcp/server.py`) sind Laufzeit-Services
  außerhalb des CI-Determinismus. **Festlegung für diese Story:** W2
  stützt sich auf die deterministische Chunk-Quelle
  (`concept_ingester.discovery` direkt über den Working-Tree), nicht auf
  den externen Index — kein Hidden-State, reproduzierbare Chunk-IDs.
- **Zuständigkeits-Quelle (verifiziert):** `authority_over`-Scopes und
  scope-qualifizierte `defers_to`-Kanten leben in der Frontmatter der
  Dokumente (z. B. FK-47 :9-30); die BC-Projektion in
  `concept/technical-design/_meta/domain-registry.yaml` (nur
  `contract_docs`/`member_docs`). Beides zusammen ist die maßgebliche
  Registry-Fläche (META §2).
- **LLM-Aufrufpfad-Ist (recherchiert und belegt):** Im Repo existiert ein
  nutzbarer LLM-Client: `integration_clients/multi_llm_hub/client.py` —
  `HubClient`, synchroner REST-Client (urllib) gegen den externen
  Multi-LLM Hub (FK-75, `75_multi_llm_hub.md`; Konfiguration
  `LLM_HUB_URL_ENV`/`DEFAULT_LLM_HUB_URL`, `multi_llm_hub/config.py`).
  Das Muster „LLM als Bewertungsfunktion" hat Code-Präzedenz im
  Verify-Layer 2: `verify_system/llm_evaluator/structured_evaluator.py`
  (`StructuredEvaluator` :173, typisierte Response-Modelle :119-133).
  `integration_clients/llm_pools/` ist ein leeres Paket (nur
  `__init__.py`) — kein Client dort. **Kein bestehender CI-/
  Nightly-Pfad ruft heute ein LLM auf** (die `scripts/ci/`-Gates sind
  vollständig deterministisch); der Nightly-/Merge-Betriebspfad inkl.
  Hub-Erreichbarkeits-Fehlerbild ist Design dieser Story (fail-closed:
  Hub nicht erreichbar → benannter Betriebs-Befund, kein stilles
  Überspringen des Laufs).

## Scope

### In Scope

1. **W2-Werkzeug `concept-authority-prose`** nach dem AK3-Muster „LLM nur
   als Bewertungsfunktion, Entscheidung deterministisch" (META
   §5-Vorspann; analog Verify-Layer 2/FK-27, Code-Präzedenz
   `StructuredEvaluator`):
   - **Chunk-Erhebung deterministisch:** H2-Chunks über den Korpus aus
     der repo-lokalen `concept_ingester.discovery`-Quelle (wie der
     Konzept-Index chunked; identische Chunk-Identität) — nicht über den
     externen Weaviate-/MCP-Dienst.
   - **LLM-Bewertung pro Chunk** (zwei Fragen, strukturiert):
     *Enthält der Abschnitt normative Aussagen?* *Über welche Scopes?*
     Antwort als typisiertes, geparstes Ergebnis (Scope-Vokabular =
     `authority_over`-Scopes des Korpus; unbekannte Scope-Nennungen sind
     ein eigenes, benanntes Ergebnis — kein stilles Verwerfen).
   - **Deterministischer Registry-Abgleich:** normative Aussage über
     Scope X in einem Dokument ohne `authority_over`-Authority über X
     und ohne `defers_to`-Kante für X → **ERROR** („unzuständige
     Behauptung", §4-Zeile P2). Der Widerspruch selbst muss nicht
     gefunden werden.
2. **Befund-Idempotenz + Baseline-Mechanik (§6):** Befunde sind
   reproduzierbar referenziert (Dokument, Chunk-/Abschnitts-Anker,
   Aussagetext) und über Läufe stabil; die Baseline enthält
   ausschließlich **begründete** Einträge (stille Baselines unzulässig —
   ein unbegründeter Eintrag lässt den Lauf selbst fehlschlagen). Neue
   Befunde sind ERROR bis zur Triage; Triage-Ergebnis ist Fix oder
   begründeter Baseline-Eintrag.
3. **Prompt-/Modell-Versionierung (§6):** Der Bewertungs-Prompt und die
   Modell-/Backend-Kennung sind versioniert und Teil der
   Befund-Referenz; ein Prompt-/Modellwechsel ist ein sichtbares Ereignis
   (Baseline-Neubewertung), nie ein stiller Drift.
4. **Betrieb nightly + vor Konzept-Merges:** Einstiegspunkt nach
   `scripts/ci/`-Muster; Verdrahtung als Nightly-Lauf und als
   Vor-Merge-Schritt für normative Konzeptänderungen (Betriebsform:
   Jenkins-Nightly-Job + dokumentierter Vor-Merge-Aufruf; Detail-Design
   dieser Story). W2 ist **kein** blocking Pflichtgate der regulären
   CI-Stufe (das ist W1, §6) — aber neue, untriagierte Befunde sind
   ERROR-Handlungsaufträge.
5. **LLM-Transport:** Anbindung über den bestehenden
   `multi_llm_hub.HubClient` (FK-75-Adapter bleibt dünn;
   Bewertungs-/Policy-Logik liegt im Werkzeug, nicht im
   `integration_clients/`-Adapter). Fail-closed-Fehlerbild: Hub nicht
   erreichbar/Antwort nicht parsebar → benannter Lauf-Befund
   (kein PASS, keine Teil-Baseline-Mutation).

### Out of Scope (mit Owner)

- **W3 Scope-Konsistenz-Sweep** (Widerspruchssuche innerhalb eines
  Scopes): **AG3-160** — konsumiert die hier gebaute
  Chunk-Klassifikation und Baseline-Mechanik.
- **W1 Referenz-Integrität**: **AG3-157**; **W4 Decision-Record-Gate**:
  **AG3-158**.
- **Sanierung der Bestands-Verstöße gegen P1/P2:** META §7 (flankierend):
  Bestandsverstöße werden durch W2-Befunde sichtbar gemacht und beim
  nächsten fachlichen Anfassen mitbereinigt — kein Big-Bang in dieser
  Story; die Erst-Baseline dokumentiert den Bestand mit Begründungen.
- **Erweiterung des externen Index/MCP-Servers** (`tools/concept_mcp/`,
  Weaviate-Schema): nicht Teil dieser Story; W2 liest die
  deterministische Quelle.
- **Ein produktiver Backend-Serviceweg** (z. B. Verify-System-Stage) für
  W2: bewusst nicht — W2 ist Repo-Governance-Werkzeug, kein
  Pipeline-Bestandteil des Zielprojekt-Laufs.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `scripts/ci/check_concept_authority_prose.py` | neu | Einstiegspunkt (nightly + vor Konzept-Merges): Lauf-Orchestrierung, Exit-Code-/Befund-Vertrag |
| `tools/concept_governance/` (neues Modul unter bestehendem `tools/`-Baum) bzw. Erweiterung eines bestehenden `tools/`-Pakets — Festlegung im Design, kein neues Top-Level-Verzeichnis | neu | Chunk-Klassifikations-Pipeline (deterministische Chunk-Quelle → LLM-Bewertung → Policy-Abgleich), Baseline-Modell + Idempotenz-Referenzen, Prompt-/Modell-Versionierung |
| `tools/concept_ingester/discovery.py` | ändern (minimal, nur falls nötig) | Wiederverwendbare Chunk-Identität für den Governance-Konsumenten (keine Verhaltensänderung für Ingestion) |
| Prompt-Asset (versioniert, Ablage beim Werkzeug — Design dieser Story) | neu | Bewertungs-Prompt v1 (zwei Fragen, strukturiertes Antwortformat) |
| `concept/_meta/…` (W2-Baseline-Datei, Format-Design dieser Story) | neu | Begründete Erst-Baseline der Bestands-Befunde |
| `Jenkinsfile` (bzw. Nightly-Job-Definition) | ändern | Nightly-Lauf + dokumentierter Vor-Merge-Aufruf |
| `tests/unit/tools/**` + Fixtures | neu | Parsing-/Policy-/Baseline-Tests mit fixierten LLM-Antworten (deterministische Fakes für die Policy-Seite); Negativtests (unzuständige Behauptung, unbegründete Baseline, Hub nicht erreichbar, nicht parsebare Antwort) |

## Akzeptanzkriterien

1. **Muster eingehalten — LLM entscheidet nie:** Die
   ERROR-/PASS-Entscheidung fällt ausschließlich in der deterministischen
   Policy (Registry-Abgleich); die LLM-Antwort ist reine
   Klassifikations-Eingabe. Beweis: Policy-Unit-Tests laufen vollständig
   mit fixierten Bewertungs-Ergebnissen ohne LLM (Ports/Fakes im Sinne
   der MOCKS-Regel: Testeingaben für reine Logik, kein Mock produktiver
   Kernlogik).
2. **Unzuständige Behauptung wird gefunden:** Fixture-Fall — ein Chunk
   mit normativer Aussage über Scope X in einem Dokument ohne Authority
   über X und ohne defers_to-Kante für X → ERROR mit Referenz (Dokument,
   Anker, Aussagetext); Gegenprobe: dasselbe Dokument mit
   `defers_to`-Kante für X → kein Befund.
3. **Chunk-Quelle deterministisch:** Die Chunk-Erhebung läuft über die
   repo-lokale `concept_ingester.discovery`-Quelle (H2-Ebene); zwei
   Läufe auf identischem Stand liefern identische Chunk-IDs und (bei
   fixierten Bewertungen) identische Befundlisten; es existiert kein
   Codepfad, der den externen Weaviate-/MCP-Dienst für die Prüfung
   benötigt (Negativtest: Lauf ohne erreichbaren Index-Dienst).
4. **Baseline fail-closed:** Ein Baseline-Eintrag ohne Begründung lässt
   den Lauf fehlschlagen; ein neuer, nicht gebaselineter Befund ist
   ERROR; ein gebaselineter Befund bleibt sichtbar gelistet (kein
   stilles Verschwinden); Baseline-Einträge referenzieren Befunde über
   die idempotente Referenz (Dokument, Anker, Aussagetext,
   Prompt-/Modell-Version).
5. **Prompt-/Modell-Versionierung:** Befunde tragen Prompt- und
   Modell-Version; ein Versionswechsel invalidiert die Baseline nicht
   still, sondern erzeugt einen benannten Neubewertungs-Zustand
   (Contract-Pin des Befund-/Baseline-Formats).
6. **Fail-closed-Betrieb:** Hub nicht erreichbar, Timeout oder nicht
   parsebare LLM-Antwort → benannter Lauf-Befund mit Exit-Code ≠ 0; kein
   Teil-Ergebnis mutiert die Baseline; kein „leerer PASS".
7. **Erst-Baseline begründet:** Der Erstlauf auf `main` ist triagiert:
   jeder Bestands-Befund ist entweder behoben oder mit Begründung
   gebaselinet (ZERO DEBT: keine unbegründeten Restposten).
8. **Betriebsverdrahtung:** Nightly-Lauf und Vor-Merge-Aufruf sind
   verdrahtet und dokumentiert; die reguläre blocking CI-Stufe bleibt
   unverändert (W1/W4 sind dort; W2 ist nightly + vor Konzept-Merges,
   §6).
9. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
   Befund-Codes, Baseline-/Prompt-Metadaten-Schlüssel; die
   Bewertungs-Prompts selbst folgen der Prompt-Sprachpraxis des Repos).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, Konzept-Gates inkl. W1-/W4-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (technische
  Vorbedingung für AG3-160); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** W2 (concept/_meta/konzept-konsistenz-governance.md §5/§6/§7; kein GAP-Nenner-Bezug — eigener Strang).

## Konzept-Referenzen

- META-CONCEPT-CONSISTENCY (`concept/_meta/konzept-konsistenz-governance.md`):
  §3/P1 (Single-Assertion; Paraphrasen = künftige Widersprüche),
  §3/P2 (Authority-Bindung von Prosa; „nebenbei normieren" ist Verstoß),
  §4 (Severity: P2-Verstoß = ERROR; P1-Paraphrase = WARNING mit
  Umbau-Pflicht; Spiegelpflicht),
  §5-Vorspann (LLM nur als Bewertungsfunktion, Entscheidung
  deterministisch; reproduzierbar referenzierte Befunde),
  §5/W2 (chunk-weise H2-Ebene „wie der Konzept-Index"; zwei Fragen pro
  Chunk; deterministischer Registry-Abgleich; „unzuständige Behauptung"),
  §6 (nightly + vor Konzept-Merges; neue Befunde ERROR bis Triage;
  Baselines nur begründet; Prompts/Modelle versioniert, Befunde
  idempotent), §7 (Fahrplan Punkt 3: „braucht Zugriff auf
  Registry-Projektion + Chunking (vorhanden via Konzept-Index) und einen
  LLM-Aufrufpfad im CI-/Nightly-Kontext")
- FK-27 (Verify-Layer-2-Muster: LLM-Evaluationen als
  Bewertungsfunktionen, nicht frei handelnde Agents) — Analogie-Anker
  des §5-Vorspanns; Code-Präzedenz
  `verify_system/llm_evaluator/structured_evaluator.py:173`
- FK-75 (`75_multi_llm_hub.md`) — Hub-REST-Adapter;
  Code: `integration_clients/multi_llm_hub/client.py` (`HubClient`)
- Zuständigkeits-Quellen: Frontmatter `authority_over`/`defers_to`
  (scope-qualifiziert) + `concept/technical-design/_meta/domain-registry.yaml`
  (BC-Projektion) — META §2
- Chunk-Quelle: `tools/concept_ingester/discovery.py` (H2-Chunking
  `_H2_RE` :42, `ConceptChunk` :56-66, Registry-Projektion :303,
  `discover()` :353)

## Guardrail-Referenzen

- **P1–P5/§4-Severity (META, Guardrail-Grundlage dieses Strangs):** W2
  operationalisiert P2 (und macht P1-Paraphrasen sichtbar); §4-Severity
  ist bindend, WARNINGs unterliegen der Spiegelpflicht.
- **FAIL-CLOSED:** Hub-Ausfall, Parse-Fehler, unbegründete Baselines und
  unbekannte Scope-Nennungen sind benannte Befunde — nie stilles
  Weiterlaufen.
- **SINGLE SOURCE OF TRUTH / kein Hidden-State:** Chunk-Quelle ist der
  Working-Tree über die eine deterministische Discovery; der externe
  Index ist Konsument derselben Quelle, nie Prüf-Grundlage; die Baseline
  ist die eine, begründete Befund-Wahrheit.
- **MOCKS/STUBS-Regel:** LLM-Fakes nur für die Policy-Unit-Tests
  (fixierte Bewertungs-Eingaben); der Transport-Pfad wird gegen den
  echten Hub-Client-Vertrag contract-getestet.
- **Determinismus-Zielbild (CLAUDE.md):** LLM ausschließlich dort, wo
  bewertende Arbeit nötig ist; jede Entscheidung deterministisch.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Nicht einschlägig — Repo-Governance-Werkzeug ohne
  Schema-/State-Backend-Bezug (explizit geprüft; Baseline lebt als
  versionierte Datei im Repo, nicht als Laufzeit-State).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Policy-/Abgleichs-
  Logik, Befund-/Baseline-Modell und Scope-Vokabular = **A** (AT-frei);
  LLM-Antwort-Parsing und Befund-Serialisierung = **R**; Hub-Transport
  (`multi_llm_hub`-Aufruf) und Datei-/CI-Mechanik = **T**.
- **Bundle-Assets:** Keine betroffen (verifiziert: reines
  Repo-Governance-Werkzeug; kein Bundle-Asset liest oder deployt
  W2-Artefakte).
- **ARCH-55:** Bezeichner, Befund-Codes, Baseline-Schlüssel,
  Prompt-Metadaten englisch.
