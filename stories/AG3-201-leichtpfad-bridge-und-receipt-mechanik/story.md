# AG3-201 — Leichtpfad, Harness-Bridge-Adapter und Receipt-Mechanik

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-185"]`; entblockt AG3-202
- **Quell-Konzept:** FK-78 §78.14 (Request-Pack, Receipt, `spawn_mode`),
  §78.10/§78.11 (Projection-Receipts, Promotion-Closure)
- **Herkunft:** Ausgezogen aus AG3-185 am 2026-08-02 nach unabhaengigem
  Codex-Review (Auflage ERROR-15).

## Kontext

### Befund

Die Norm aus AG3-185 beschreibt ein Verfahren, das heute keine Mechanik hat:

- **Der Leichtpfad fehlt.** Die Migrationstreue-Pruefung ist normiert (DK-16
  §6, FK-78 §78.10/§78.11) und implementiert (`promotion_check.py` mit
  `_check_atom_closure`, `_check_receipt_independence`, `_check_reverse_trace`,
  `_check_targets`) — aber sie haengt am **Atom-Register**, das nur ein
  `FULL_ATOM`-Lauf erzeugt. Fuer den vom PO geforderten sofort anwendbaren Pfad
  („ein Opus-Agent schreibt, ein Codex prueft direkt danach") existiert sie
  nicht. Es gibt **keine leichte Freigabebasis** — nichts, wogegen „genau das
  Freigegebene" ausserhalb eines Vollverfahrens gemessen werden koennte.
- **Der Bridge-Adapter fehlt.** Der Hub-spezifische Betrieb der Skripte
  `check_concept_authority_prose.py` (W2) und `check_concept_scope_consistency.py`
  (W3) und die dort verbaute Partitionierung sind an den LLM-Hub gebunden.
- **Der Auftragsvertrag hat keinen Traeger.** FK-78 kennt heute nur den
  Reviewer eines einzelnen Projektions-Receipts, nicht den pruefenden Agenten.

### Was diesen Umbau klein haelt

C-9 des Werkstattberichts: Der Request-Pack-/Receipt-Vertrag aus FK-78 §78.14
ist **ausfuehrerneutral**. `prepare` erzeugt ein Request-Pack
(`{gate, scope_id, base_revision, template_id, template_digest, chunks[],
request_digest}`), irgendjemand fuehrt aus, `import` validiert ein
Semantik-Receipt mit vollstaendiger Chunk-Digest-Rueckbindung, und
`check.py semantic-status` verrechnet. `participants[].spawn_mode` kennt
`harness-bridge` bereits.

**Der Wechsel ist ein Adaptertausch, kein Verfahrenswechsel.** Wer daneben eine
neue Mechanik baut, macht die Arbeit zweimal und erzeugt eine zweite Wahrheit.

## Scope

### In Scope

- Der Harness-Bridge-Adapter **auf dem vorhandenen** Request-Pack-/Receipt-Vertrag.
- Der Rueckbau des Hub-spezifischen Betriebs samt Partitionierung.
- Die leichte Freigabebasis (Form entscheidet AG3-185/E3) und ihre Bindung an
  `promotion_check.py`.
- Der Auftragsvertrag des pruefenden Agenten als ausfuehrbares Artefakt.
- Die in AG3-185 uebernommenen Bausteine, soweit sie Code brauchen
  (`gap_class`-Feld, kalter Implementierbarkeitstest, Provider-Claim-Kante,
  Freigabekriterien).

### Out of Scope

- **Keine Entscheidung.** Was gilt, steht nach AG3-185 fest; weicht die
  Umsetzung davon ab, ist das ein Fehler und keine Auslegung.
- **Kein Retry-Vertrag fuer W2/W3** — das Verfahren wird ersetzt, nicht
  repariert (PO-Entscheidung 2026-08-02).
- Der erste vollstaendige Durchlauf samt Migrationstreue-Pruefung — **AG3-202**.
- Die Komponenten-/Schnittstellenschicht — **AG3-186**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `tools/concept_governance/` (Adapter, Transport, Prompt-Assets) | geaendert | Bridge statt Hub; Partitionierung entfaellt |
| `scripts/ci/check_concept_authority_prose.py`, `..._scope_consistency.py` | geaendert/entfernt | Hub-spezifischer Betrieb faellt |
| `tools/concept_toolchain/promotion_check.py` | geaendert | Bindung an die leichte Freigabebasis |
| `src/agentkit/integration_clients/mcp/` bzw. der Bridge-Zugang | geaendert | Ausfuehrungsweg des Agenten |
| `src/agentkit/bundles/skill_bundles/concept-incubation-core/` | geaendert | Auftragsvertrag und Aufrufuebersicht |
| `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/` | geaendert | deploybare Toolchain zieht mit |
| `tests/` | neu | Receipt-Validierung, Freigabebasis, Negativpfade |
| `concept/_meta/decisions/2026-XX-XX-bridge-adapter-und-leichtpfad.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Der Bridge-Adapter setzt auf dem vorhandenen Vertrag auf.** Request-Pack,
   Receipt und deterministische Verrechnung sind unveraendert; ausgetauscht ist
   nur der Ausfuehrer. Nachgewiesen daran, dass ein Receipt, das ueber den
   Hub-Weg erzeugt worden waere, und eines vom Bridge-Weg **dieselbe**
   Validierung durchlaufen. Eine neue, parallele Receipt-Form ist ein Fehler.
2. **Der Hub-spezifische Betrieb ist zurueckgebaut, nicht danebengestellt.**
   Nach dieser Story existiert kein zweiter Ausfuehrungsweg fuer W2/W3.
3. **Die leichte Freigabebasis existiert und ist messbar in beide Richtungen.**
   „Nicht weniger als freigegeben" und „nicht mehr als freigegeben" sind
   maschinell pruefbar, ohne `FULL_ATOM`-Lauf. Nachgewiesen an einem
   konstruierten Aenderungssatz, bei dem je eine Aussage **fehlt** und eine
   **zusaetzlich** enthalten ist — beide Faelle werden erkannt.
4. **Der Auftragsvertrag ist ausfuehrbar, nicht nur beschrieben.** Ein Agent
   bekommt Ziel, Leitplanken, Nachweispflichten und Abbruchkriterien als
   Artefakt. „Konnte nicht geprueft werden" ist ein modelliertes Ergebnis und
   **nie** PASS.
5. **Die Ermittlung ist frei, die Verrechnung deterministisch.** Der Agent
   liefert typisierte Belege mit Locator und woertlichem Zitat; ueber Freigabe
   oder Blockade entscheidet eine Policy ueber diesen Belegen, **nie** der
   Agent. Nachgewiesen durch einen Test, in dem ein Agentenbeleg mit
   Freigabe-Empfehlung die Policy **nicht** beeinflusst.
6. **Die Worttreue der Belege ist gewahrt.** Die Escape-Reparatur verdoppelt
   nicht anerkannte Backslashes statt sie zu entfernen (Decision Record
   `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.11); Schema-Schluessel
   werden am **geparsten** Dokument normalisiert. Dieser bereits erreichte
   Vertrag wird durch den Adaptertausch nicht zurueckgedreht — nachgewiesen
   durch die bestehenden Tests.
7. **Die in AG3-185 uebernommenen Bausteine sind implementiert**, soweit sie
   Code brauchen. Fuer jeden ist benannt, welcher Anteil deterministisch und
   welcher agentisch ist — bei der Provider-Claim-Kante insbesondere: „ein
   Provider-Claim ohne benannte Zielsymbole ist ein Befund" ist der
   deterministische Anteil.
8. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; Coverage haelt die 85-%-Schwelle; alle deterministischen
   Konzept-Gates gruen; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die konstruierten Faelle aus AC 3 und AC 5 sind mit Diff und Ausgabe im
  Story-Record dokumentiert.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/78_concept_incubation_process.md` §78.10, §78.11,
  §78.14
- `concept/domain-design/16-konzeption-und-konzeptinkubation.md` §6
- `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md`
  Rand 2.4a, 2.11 — Exit-Code-Vertrag und Worttreue
- Die in AG3-185 beschlossene Norm (Decision Record dieser Migration)

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS" — AC 2: kein
  zweiter Ausfuehrungsweg.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — AC 1: keine parallele
  Receipt-Form.
- `AGENTS.md` (Agentenmandat) — AC 5: frei ist die Ermittlung, nicht die
  Entscheidung.
- `CLAUDE.md` „MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL".
