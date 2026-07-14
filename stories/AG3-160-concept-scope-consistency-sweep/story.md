# AG3-160 — Konzept-Scope-Konsistenz-Sweep (W3): LLM-Sweep pro authority_over-Scope — alle Aussagen-Chunks eines Scopes als geschlossenes Set auf Widersprüche prüfen (nightly, Baseline wie W2)

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-159] — **TECHNISCHE Kante** (META §5/W3 + §7
  Punkt 4): W3 setzt die W2-Infrastruktur voraus — die
  **Chunk-Klassifikation** (welche Chunks enthalten normative Aussagen,
  über welche Scopes) liefert die Aussagen-Mengen je Scope, die
  **Baseline-Mechanik** (begründete Einträge, idempotente
  Befund-Referenzen, Prompt-/Modell-Versionierung) wird
  wiederverwendet. Ohne W2 degeneriert die Widerspruchssuche zu O(n²)
  über den Gesamtkorpus (META §5/W3 wörtlich: „Setzt W2/P1 voraus, um
  klein zu bleiben").
- **unblocks:** [] — W3 ist der letzte Baustein des §7-Fahrplans.
- **Quell-Konzept:** META-CONCEPT-CONSISTENCY
  (`concept/_meta/konzept-konsistenz-governance.md`) §5/W3
  (Spezifikation), §5-Vorspann (LLM nur als Bewertungsfunktion,
  Entscheidung deterministisch), §3/P4 (Widersprüche sind
  Formalisierungs-Signale), §4 (Severity: semantischer Widerspruch
  innerhalb desselben Scopes = ERROR), §6 (Betriebsmodell: nightly;
  Baseline wie W2), §7 (Fahrplan Punkt 4)
- **Herkunft:** Konzept-Konsistenz-Governance (META-Dokument, aktiv);
  PO-Freigabe 2026-07-02. Kein GAP-Nenner-Bezug — eigener Strang.

## Kontext / Problem

Die META-§1-Fehlerklasse — vier Dokumente normieren denselben Mechanismus
aus verschiedenen Blickwinkeln, eine Entscheidung ändert sich, nur das
Heimat-Dokument wird aktualisiert — ist mit W1/W2 detektierbar gemacht,
aber noch nicht als **Widerspruch** gefunden: W2 erkennt die
unzuständige Behauptung, nicht den semantischen Konflikt zwischen zwei
für sich genommen zuständig platzierten (oder gebaselineten) Aussagen.
W3 schließt diese Lücke, kollabiert auf kleine Mengen (§5/W3): Pro
`authority_over`-Scope werden **alle Aussagen-Chunks des Scopes** als
geschlossenes Set geprüft („lies diese ~20 Aussagen zu Lock-Lifecycle —
widersprechen sich welche?"). Ist-Zustand (verifiziert 2026-07-02):

- **W3 existiert nicht**; die einzige Widerspruchs-Vorsorge des Bestands
  sind die deterministischen Struktur-Lints (u. a. L5
  Authority-Disjunktheit, L20 Fremd-Term-Leakage in
  `scripts/ci/check_concept_frontmatter.py`) — keine semantische
  Widerspruchssuche.
- **Konzept-Index-Anbindung (recherchiert — was liegt im Repo, was ist
  extern):** Im Repo liegen die **Chunking-/Projektions-Werkzeuge**:
  `tools/concept_ingester/discovery.py` (H2-Chunking `_H2_RE` :42,
  `ConceptChunk` :56-66, Registry-Projektion in jeden Chunk :303,
  `discover()` :353) und der MCP-Server-Code `tools/concept_mcp/server.py`.
  **Extern** sind die Weaviate-Instanz und der ingestete Index selbst
  (Default `127.0.0.1:9903`, Collection `Ak3ConceptChunk`;
  `tools/concept_ingester/config.py:36-40`) sowie der laufende
  MCP-Dienst (`agentkit3-concepts`). **Festlegung für diese Story
  (kein Hidden-State; deterministische Quelle bevorzugt):** W3 stützt
  sich ausschließlich auf die repo-lokale, deterministische
  Discovery-Quelle und die W2-Klassifikationsergebnisse; der externe
  Index/MCP-Dienst ist für Recherche-Komfort da, nie Prüf-Grundlage —
  ein Nightly-Lauf darf nicht von der Erreichbarkeit oder dem
  Ingestions-Stand eines externen Dienstes abhängen.
- **Scope-Vokabular:** `authority_over`-Scopes leben in der Frontmatter
  der Korpus-Dokumente (z. B. FK-47 :9-11); zusammen mit den
  W2-Chunk-Klassifikationen ergibt sich je Scope ein geschlossenes,
  kleines Aussagen-Set.

## Scope

### In Scope

1. **W3-Werkzeug `concept-scope-consistency`** nach dem Muster „LLM nur
   als Bewertungsfunktion, Entscheidung deterministisch":
   - **Set-Bildung deterministisch:** Pro `authority_over`-Scope werden
     die Aussagen-Chunks des Scopes aus der W2-Klassifikation gesammelt
     (Chunk-Identität = deterministische Discovery-Quelle aus AG3-159);
     die Set-Bildung ist reproduzierbar und ohne LLM.
   - **LLM-Sweep pro Scope-Set:** Das geschlossene Set wird als Ganzes
     auf Widersprüche geprüft (strukturiertes Antwortformat:
     Widerspruchs-Paare/-Gruppen mit Aussagetext-Zitaten); große Sets
     werden deterministisch partitioniert statt still gekürzt.
   - **Deterministische Policy:** Gemeldete Widersprüche werden gegen
     die Baseline ausgewertet; neue Befunde sind ERROR bis zur Triage
     (§4: semantischer Widerspruch desselben Scopes = ERROR); die
     Entscheidung trifft nie das LLM.
2. **Baseline wie W2 (§6):** Wiederverwendung der W2-Baseline-Mechanik
   aus AG3-159 (begründete Einträge, idempotente Referenzen: Dokument,
   Anker, Aussagetext, Prompt-/Modell-Version) — **kein zweites
   Baseline-Format** (SINGLE SOURCE OF TRUTH der Governance-Befunde;
   getrennte Befund-Arten W2/W3, eine Mechanik).
3. **P4-Anschluss:** Jeder triagierte W3-Widerspruch erzeugt die
   dokumentierte Prüfpflicht „Gehört dieser Scope in den Formal-Layer?"
   (META §3/P4) — als Pflichtfeld der Triage (Ergebnis: Fix /
   begründeter Baseline-Eintrag / Formalisierungs-Kandidat benannt),
   nicht als bloße Empfehlung.
4. **Betrieb nightly:** Verdrahtung analog dem W2-Nightly-Lauf
   (AG3-159); zusätzlich vor der Landung normativer Konzeptänderungen
   für die betroffenen Scopes aufrufbar (scope-gefilterter Lauf —
   Detail-Design dieser Story). W3 ist kein blocking Pflichtgate der
   regulären CI-Stufe (§6).
5. **Fail-closed-Betrieb:** Hub nicht erreichbar, nicht parsebare
   Antwort, unvollständiger Sweep (nicht alle Sets geprüft) → benannter
   Lauf-Befund; keine Teil-Baseline-Mutation, kein „leerer PASS".

### Out of Scope (mit Owner)

- **W2-Infrastruktur** (Chunk-Klassifikation, Baseline-Mechanik,
  Prompt-/Modell-Versionierung, Hub-Anbindung): **AG3-159** — hier nur
  Wiederverwendung; Änderungen an der W2-Mechanik, die W3 braucht,
  werden dort nachgezogen, nicht hier gedoppelt.
- **W1/W4**: **AG3-157**/**AG3-158**.
- **Auflösung gefundener Widersprüche:** läuft je Fund über den
  regulären Prozess (P3-Decision-Record, zuständiges
  Authority-Dokument) — nicht Teil des Werkzeugs; die Erst-Triage der
  Bestands-Funde gehört zur Einführung (Fix oder begründete Baseline),
  die inhaltliche Sanierung großer Funde ist eigener Konzept-Strang.
- **Formalisierung widerspruchsanfälliger Scopes** (P4-Konsequenz,
  State-Machines/Invarianten im Formal-Layer): eigener Strang je Scope;
  W3 liefert nur den benannten Kandidaten.
- **Erweiterung des externen Index/MCP-Dienstes**: nicht Teil dieser
  Story.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `scripts/ci/check_concept_scope_consistency.py` | neu | Einstiegspunkt (nightly; scope-gefilterter Vor-Merge-Aufruf): Lauf-Orchestrierung, Exit-Code-/Befund-Vertrag |
| W2-Werkzeug-Modul aus AG3-159 (`tools/concept_governance/` o. ä. — derselbe Baum, Festlegung folgt AG3-159) | ändern/erweitern | Scope-Set-Bildung aus der W2-Klassifikation; Sweep-Partitionierung; W3-Befund-Art in der bestehenden Baseline-Mechanik |
| Prompt-Asset (versioniert, Ablage beim Werkzeug analog W2) | neu | Sweep-Prompt v1 (geschlossenes Aussagen-Set → strukturierte Widerspruchs-Meldungen) |
| `concept/_meta/…` (W3-Befund-Einträge in der bestehenden Baseline-Datei/-Struktur aus AG3-159) | ändern | Begründete Erst-Baseline der Bestands-Funde (keine stillen Einträge) |
| `Jenkinsfile` (bzw. Nightly-Job-Definition aus AG3-159) | ändern | W3-Nightly-Lauf neben dem W2-Lauf |
| `tests/unit/tools/**` + Fixtures | neu | Set-Bildungs-/Partitionierungs-/Policy-Tests mit fixierten LLM-Antworten; Negativtests (neuer Widerspruch = ERROR, unbegründete Baseline, unvollständiger Sweep, Hub-Ausfall) |

## Akzeptanzkriterien

1. **Set-Bildung deterministisch und geschlossen:** Für einen
   Fixture-Korpus mit bekannten Scope-Klassifikationen entsteht je
   `authority_over`-Scope genau das erwartete Aussagen-Set (alle
   klassifizierten Chunks des Scopes, keine fremden); zwei Läufe liefern
   identische Sets und Set-Partitionen (Chunk-IDs stabil).
2. **Widerspruch wird gefunden und deterministisch entschieden:**
   Fixture-Fall mit zwei sich widersprechenden Aussagen desselben Scopes
   (Muster der META-§1-Klasse: „kein stiller Rückfall, Mensch bindet
   neu" vs. „automatische Freigabe via TTL") → bei fixierter
   LLM-Meldung entsteht ein ERROR-Befund mit beiden Fundstellen
   (Dokument, Anker, Aussagetext); die PASS-/ERROR-Entscheidung fällt in
   der Policy, nie im LLM (Policy-Tests ohne LLM, Ports/Fakes).
3. **O(n²)-Vermeidung belegt:** Der Sweep prüft ausschließlich
   Scope-Sets (nie Chunk-Paare über Scope-Grenzen hinweg); Beleg über
   Aufruf-Zählung im Test (Anzahl LLM-Aufrufe = Anzahl
   Scope-Sets/Partitionen, nicht quadratisch in der Chunk-Zahl).
4. **Baseline wie W2, fail-closed:** W3-Befunde laufen über die
   AG3-159-Baseline-Mechanik (eine Mechanik, eigene Befund-Art);
   unbegründete Einträge lassen den Lauf fehlschlagen; neue Befunde sind
   ERROR bis zur Triage; jeder triagierte Fund trägt das
   P4-Pflichtfeld (Formalisierungs-Prüfung: ja/nein + Begründung).
5. **Kein externer Dienst als Prüf-Grundlage:** Der Lauf funktioniert
   nachweislich ohne erreichbaren Weaviate-/MCP-Dienst (Negativtest);
   einzige externe Abhängigkeit ist der LLM-Hub — dessen Ausfall ist ein
   benannter Lauf-Befund (kein PASS, keine Baseline-Mutation).
6. **Vollständigkeit des Sweeps fail-closed:** Bleibt ein Scope-Set
   ungeprüft (Partition fehlgeschlagen, Timeout), ist der Lauf als
   unvollständig benannt (Exit-Code ≠ 0) — kein stilles Auslassen.
7. **Reale End-to-End-Verifikation per Smoke-Test (kein Vollkorpus-Sweep als Gate):**
   Das Werkzeug wird gegen den echten Hub an einer **Handvoll** Scope-Sets
   nachgewiesen (Set-Bildung → Sweep → Parsing → Policy end-to-end,
   verfügbare Backends). Iterierbar bei Bedarf. Es wird **kein** Sweep über
   *alle* Scopes als Abnahme-Gate verlangt. **Baseline startet leer** (ehrlicher
   Startzustand, W2-Mechanik). Die Triage des Bestands erfolgt **inkrementell**
   (nightly / vor Landung normativer Änderungen für die betroffenen Scopes;
   META §6/§7 „kein Big-Bang") — ein separater Betriebsvorgang, nicht Teil der
   Abnahme dieser Werkzeug-Story. Nightly-Verdrahtung steht.
8. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
   Befund-Codes, Baseline-/Triage-Feldnamen).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, Konzept-Gates inkl. W1-/W4-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** W3 (concept/_meta/konzept-konsistenz-governance.md §5/§6/§7; kein GAP-Nenner-Bezug — eigener Strang).

## Konzept-Referenzen

- META-CONCEPT-CONSISTENCY (`concept/_meta/konzept-konsistenz-governance.md`):
  §5/W3 (Widerspruchssuche kollabiert auf kleine Mengen; pro
  `authority_over`-Scope alle Aussagen-Chunks als geschlossenes Set;
  „Setzt W2/P1 voraus, um klein zu bleiben; ohne sie degeneriert die
  Prüfung zu O(n²) über den Gesamtkorpus"; Betrieb nightly, Baseline wie
  W2),
  §5-Vorspann (LLM nur als Bewertungsfunktion, Entscheidung
  deterministisch; Befunde reproduzierbar referenziert),
  §3/P4 (Widersprüche sind Formalisierungs-Signale — Prüfpflicht je
  Fund), §4 (Severity: „Semantischer Widerspruch zwischen Aussagen
  desselben Scopes → ERROR"; „Widerspruchsanfälliger Scope ohne
  Formalisierungs-Prüfung → WARNING" mit Spiegelpflicht),
  §6 (W2/W3 nightly + vor Landung normativer Änderungen; neue Befunde
  ERROR bis Triage; Baselines nur begründet; Prompts/Modelle
  versioniert), §7 (Fahrplan Punkt 4: „setzt W2-Infrastruktur voraus
  (Chunk-Klassifikation, Baseline-Mechanik)")
- FK-27 (Verify-Layer-2-Analogie des §5-Vorspanns; Code-Präzedenz
  `verify_system/llm_evaluator/structured_evaluator.py:173`)
- Chunk-/Index-Landschaft: `tools/concept_ingester/discovery.py`
  (deterministische H2-Chunk-Quelle, Registry-Projektion),
  `tools/concept_ingester/config.py:36-40` (externer Weaviate,
  Collection `Ak3ConceptChunk`), `tools/concept_mcp/server.py`
  (externer MCP-Dienst) — Abgrenzung Repo vs. extern siehe Kontext
- W2-Infrastruktur: `stories/AG3-159-concept-authority-prose-check/story.md`
  (Chunk-Klassifikation, Baseline-Mechanik, Hub-Anbindung)

## Guardrail-Referenzen

- **P1–P5/§4-Severity (META, Guardrail-Grundlage dieses Strangs):** W3
  findet die Scope-internen Widersprüche (ERROR) und speist P4
  (Formalisierungs-Signale); die Severity-Zuordnung ist bindend,
  WARNINGs werden aktiv gespiegelt.
- **FAIL-CLOSED:** Unvollständige Sweeps, Hub-Ausfälle und unbegründete
  Baselines brechen den Lauf benannt; kein Teil-PASS.
- **SINGLE SOURCE OF TRUTH / kein Hidden-State:** Eine Baseline-Mechanik
  für W2+W3; Prüf-Grundlage ist ausschließlich die deterministische
  repo-lokale Chunk-Quelle — nie der Ingestions-Stand eines externen
  Dienstes.
- **FIX THE MODEL, NOT THE SYMPTOM:** Wiederkehrend widersprüchliche
  Scopes werden als Formalisierungs-Kandidaten benannt (P4) — statt
  Fund für Fund kosmetisch zu flicken.
- **MOCKS/STUBS-Regel:** Fixierte LLM-Antworten nur als Testeingaben der
  deterministischen Policy; kein Mock produktiver Kernlogik.
- **Determinismus-Zielbild (CLAUDE.md):** LLM ausschließlich für die
  bewertende Widerspruchs-Erkennung; Set-Bildung, Partitionierung und
  Entscheidung deterministisch.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Nicht einschlägig — Repo-Governance-Werkzeug ohne
  Schema-/State-Backend-Bezug (explizit geprüft; Baseline als
  versionierte Repo-Datei).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Set-Bildung,
  Partitionierungs- und Policy-Regeln, Befund-/Triage-Modell = **A**
  (AT-frei); LLM-Antwort-Parsing/Befund-Serialisierung = **R**;
  Hub-Transport und Datei-/CI-Mechanik = **T**.
- **Bundle-Assets:** Keine betroffen (verifiziert: reines
  Repo-Governance-Werkzeug ohne Bundle-Bezug).
- **ARCH-55:** Bezeichner, Befund-Codes, Baseline-/Triage-Feldnamen
  englisch.
