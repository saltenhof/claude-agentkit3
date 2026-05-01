# BC-Glossar — Agent-Briefing

Stand: 2026-05-01

Du bist ein Sub-Agent, der fuer **genau einen Bounded Context (BC)**
das Glossar pflegt. Dieses Briefing ist statisch und enthaelt alle
Spielregeln. Lies es zuerst vollstaendig, bevor du irgendetwas
aenderst.

## 0. Vor allem anderen

Lies zwingend vorab:

- `T:/codebase/claude-agentkit3/CLAUDE.md` — alle Projektregeln gelten.
- `concept/technical-design/00_index.md` §9.10 (BC-Schnitt), §9.11
  (Glossar-Form, Ownership), §9.12 (Glossar-Lint).
- `concept/technical-design/_meta/bounded-contexts.yaml` — die
  semantische Quelle (Verantwortung, owns, excluded pro BC).
- `concept/technical-design/_meta/domain-registry.yaml` — die
  maschinenlesbare BC-Mitgliedschaftstabelle.

Du bekommst von deinem Auftraggeber genau **einen** `bc_id` mit, z. B.
`verify-system`. Du arbeitest **ausschliesslich** an dem zugeordneten
BC. Glossarbloecke anderer BCs **nie** anfassen — auch nicht zur
Korrektur. Falls du dort einen Fehler bemerkst, melde ihn dem
Auftraggeber, aendere ihn aber nicht.

## 1. Schritt 1 — Diff-Analyse (Pflicht, immer)

Ziel: feststellen, ob es ueberhaupt etwas zu tun gibt.

### 1.1 Aktuellen Glossar-Stand des BC laden

1. In `domain-registry.yaml` deinen BC finden und die Liste der
   `contract_docs` notieren. Nur **Contract-Docs** duerfen einen
   Glossar-Block tragen (Lint L19).
2. In jedem Contract-Doc die Frontmatter lesen und pruefen, ob bereits
   ein `glossary:`-Block existiert. Form siehe §3 unten.
3. Per MCP einmal abfragen, was im Index ist:

   ```
   concept_glossary_search(query="<bc_id>", domain="<bc_id>", limit=50)
   ```

   Treffer sind die heute indizierten Begriffe deines BC. Fehlende
   Treffer == Glossar-Block fehlt oder Re-Ingest steht aus.

### 1.2 Soll-Begriffswelt des BC herleiten

Quellen, in dieser Reihenfolge:

1. **`bounded-contexts.yaml`**: dein BC-Eintrag listet `responsibility`
   und `owns`. Jeder Owns-Eintrag ist ein Kandidat fuer einen
   exportierten Begriff.
2. **Contract-Docs deines BC**: gleiche Vokabeln finden sich dort als
   `authority_over.scope`, in Headings und in Prosa. Begriffe, die in
   Prosa normativ verwendet werden, gehoeren ins Glossar.
3. **Formale Specs** unter `concept/formal-spec/<context>/...`, sofern
   dein BC welche besitzt. `entities.md` und `state-machine.md` sind
   Begriffsquellen erster Klasse.
4. **MCP-Suche** in deinem BC, ohne Filter auf Glossar:

   ```
   concept_search(query="zentrale Begriffe", domain="<bc_id>",
                  layer="technical", limit=15)
   ```

   Daraus kannst du die in Prosa wiederholt verwendeten BC-eigenen
   Begriffe extrahieren.

### 1.3 Diff bilden

- **Soll-Menge**: Begriffe aus 1.2.
- **Ist-Menge**: bereits im Glossar deines BC eingetragene
  `exported_terms` und `internal_terms`.
- **Diff**: in Soll und nicht in Ist == Kandidaten fuer Neuaufnahme.
  In Ist und nicht in Soll == sehr genau pruefen, vermutlich falsch
  einsortiert.

### 1.4 Abbruchkriterium

**Wenn der Diff leer ist und der Lint gruen ist: Stopp.** Du meldest
"keine Aenderung noetig" plus die Liste der heute indizierten
Begriffe. Du fuehrst keine Schritte 2-4 aus.

Nur wenn echte neue Begriffe fehlen oder ein Begriff sichtbar
falsch/veraltet ist, geht es weiter.

## 2. Schritt 2 — BC-Begriffswelt vervollstaendigen

Ort und Form sind hart vorgegeben (siehe §9.11 in `00_index.md`):

- Glossar lebt **nicht** in einer eigenen YAML-Datei.
- Glossar lebt **im Frontmatter des Contract-Docs**, dem der Begriff
  fachlich am naechsten ist.
- Glossar lebt **niemals** in einem Member-Doc oder cross-cutting
  Doc — Lint L19 fail-closed.
- Pro Begriff genau ein Definitions-Owner. Wenn du einen Begriff
  erweiterst, musst du ihn beim **bestehenden** Owner erweitern, du
  legst ihn nicht doppelt an.

### 2.1 Block-Schema

```yaml
# im Frontmatter eines Contract-Docs deines BC
glossary:
  exported_terms:
    - id: <Term-Slug>          # kebab-case, eindeutig im BC
      definition: <string>     # 1-3 Saetze, fail-closed praezise
      values: [optional, fuer Enums]
      see_also:
        - term: <Other-Term>
          domain: <other-bc-id>
  internal_terms:
    - id: <implementation-detail>
      reason: <warum nicht exportiert>
```

### 2.2 Was kommt nach `exported_terms`

Ein Begriff ist **exported**, wenn mindestens eines gilt:

- Er steht im `bounded-contexts.yaml` als `owns`-Eintrag deines BC.
- Er ist `authority_over.scope` in einem Contract-Doc deines BC.
- Andere BCs verweisen auf ihn (per `defers_to.scope` oder im Lauftext
  als FK-/DK-Bezug).
- Er taucht in einer formalen Spec deines BC auf, die andere BCs
  konsumieren.

Definition kurz, fail-closed, ohne Marketing. Beispiele formuliert in
Indikativ-Aktiv. Wenn der Begriff ein Enum ist, listest du `values`
explizit.

### 2.3 Was kommt nach `internal_terms`

Ein Begriff ist **internal**, wenn er den BC nicht verlaesst:

- Implementation-Detail oder interner Untertyp.
- Hilfsbegriff, der nur in BC-internen Docs auftaucht.
- Begriff, der **bewusst** keinen Vertrag nach aussen tragen soll.

Pro internen Begriff ein `reason` warum er nicht exportiert ist.
Leerer `reason` ist Lint-Verstoss.

### 2.4 `see_also` und Cross-BC-Referenzen

`see_also` ist deterministisch (Lint L19 prueft):

- `term` ist die `id` eines Begriffs aus einem **anderen BC**.
- `domain` ist die `bc_id` dieses anderen BC.
- Du darfst nur auf existierende, exportierte Begriffe verweisen.
- Eigene `internal_terms` referenzierst du nicht in `see_also` —
  dafuer ist `see_also` nicht gedacht.

Wenn ein Begriff in einem anderen BC fehlt, den du zwingend brauchst,
ist das ein Befund fuer den dortigen BC-Owner — nicht fuer dich.

### 2.5 Reihenfolge im Block

Stabile Reihenfolge: alphabetisch nach `id` innerhalb von
`exported_terms` und `internal_terms`. Das macht Diffs lesbar.

### 2.6 Beispielminimum

Ein neuer Eintrag fuer BC `verify-system` in FK-27 sieht in der
Frontmatter so aus:

```yaml
glossary:
  exported_terms:
    - id: qa-cycle
      definition: >
        Ein atomarer Verify-Durchlauf, identifiziert durch
        qa_cycle_id und qa_cycle_round. Setzt evidence_epoch und
        evidence_fingerprint kanonisch.
      see_also:
        - term: stage-registry
          domain: verify-system
        - term: phase-state-projection
          domain: pipeline-framework
```

## 3. Schritt 3 — Indizierung anstossen

Ziel: die neue oder erweiterte Begriffswelt ist in der Weaviate-
Collection `Ak3GlossaryTerm` sichtbar und ueber MCP suchbar.

### 3.1 Tooling-Pfad

Ingester liegt unter
`T:/codebase/claude-agentkit3/tools/concept_ingester/` und wird ueber
das CLI-Modul angestossen:

```
python -m tools.concept_ingester.cli <command>
```

Verfuegbare Kommandos:

- `status` — read-only Diagnose; zeigt lokal entdeckte Glossar-
  Begriffe und remote Anzahl in beiden Collections.
- `delta` — diff-basierter Sync. Inserts neue Glossar-Begriffe,
  updated geaenderte, deletet entfernte. Idempotent, sicher.
- `full` — drop und rebuild beider Collections. Nicht ohne
  Auftraggeber-Bestaetigung verwenden.
- `ensure-schema` — legt Collections an, falls nicht da.
- `drop` — destruktiv, nur mit `--yes`.

Default fuer dich: **immer `delta`**.

Konfiguration ueber Env-Variablen (Defaults sind ok, wenn Weaviate
lokal laeuft):

| Variable | Default |
| --- | --- |
| `AK3_WEAVIATE_HOST` | `127.0.0.1` |
| `AK3_WEAVIATE_HTTP_PORT` | `9903` |
| `AK3_WEAVIATE_GRPC_PORT` | `50051` |
| `AK3_CONCEPT_COLLECTION` | `Ak3ConceptChunk` (nicht aendern) |

### 3.2 Reihenfolge der Aufrufe

Genau so, sequentiell:

1. **Frontmatter-Lints zuerst** — sonst macht Indizieren keinen Sinn:

   ```
   PYTHONPATH=. python scripts/ci/check_concept_frontmatter.py
   ```

   Erwartete Ausgabe: `[concept-frontmatter] OK: 79 docs, all lints
   passed. Bounded-context layer: active.`

   Wenn rot, erst Diff-Edits korrigieren. Niemals Lints umgehen.

2. **Formal-Spec-Lint mitlaufen lassen**, falls du formale Specs
   beruehrt hast:

   ```
   PYTHONPATH=. python scripts/ci/compile_formal_specs.py
   ```

3. **Pre-Ingest-Status pruefen**:

   ```
   python -m tools.concept_ingester.cli status
   ```

   Im JSON unter `discovered.glossary_terms.total` muss die neue
   Anzahl auftauchen. Unter `discovered.glossary_terms.by_domain`
   muss dein BC erscheinen.

4. **Delta-Ingest ausfuehren**:

   ```
   python -m tools.concept_ingester.cli delta
   ```

   Erfolgsbild: `glossary.errors == []`, `glossary.inserted` oder
   `glossary.updated` enthaelt deine neuen Begriffe, kein
   `glossary.deleted` ausser wenn du wirklich gestrichen hast.

   Misslungener Lauf: STOPP. Du fixt nicht "irgendwie", du gibst die
   Fehlermeldung dem Auftraggeber zurueck.

### 3.3 Was passiert intern

`tools.concept_ingester.discovery` liest die Frontmatter aller
Contract-Docs, extrahiert `glossary.exported_terms` und
`glossary.internal_terms`, hashed pro Begriff (term + definition +
kind + domain + source_doc_id + values + see_also + reason). Geaenderte
Hashes loesen Update aus, neue Slug-IDs Insert, fehlende Slug-IDs
Delete. Du musst dafuer nichts manuell tun.

## 4. Schritt 4 — Verifikation

Drei Checks, alle Pflicht.

### 4.1 Status-Vergleich

```
python -m tools.concept_ingester.cli status
```

`discovered.glossary_terms.total` muss gleich
`remote.Ak3GlossaryTerm.total` sein. Wenn nicht, gab es einen
Ingest-Fehler oder der Server-Stand ist veraltet — siehe §3.2 Schritt
4 zur Diagnose.

### 4.2 MCP-Roundtrip

Schnellste Lebendkontrolle ueber den Index:

```
concept_glossary_search(query="<einer deiner neuen Begriffe>",
                        domain="<bc_id>", limit=5)
```

Mindestens dein Term muss als Treffer erscheinen mit:

- `domain == <bc_id>`
- `term_kind == "exported"` oder `"internal"`
- `source_doc_id == <FK-/DK-ID des Contract-Docs>`
- `definition` nicht leer

Zweite Probe ohne BC-Filter:

```
concept_glossary_search(query="<einer deiner neuen Begriffe>",
                        limit=5)
```

Der Term muss weiter unter den Top-Treffern sein. Wenn nein:
Definition-Text ueberarbeiten, kompakter und konkreter.

### 4.3 Lints final ein zweites Mal

Nach dem Schreiben in die Frontmatter, **vor** dem Hand-Off:

```
PYTHONPATH=. python scripts/ci/check_concept_frontmatter.py
PYTHONPATH=. python scripts/ci/compile_formal_specs.py
```

Beide gruen. Keine Ausnahme. ZERO DEBT (siehe CLAUDE.md).

## 5. Hand-Off an den Auftraggeber

Liefere strukturiert, mit Belegen:

1. `bc_id` und Liste der bearbeiteten Contract-Docs.
2. Vorher/Nachher-Anzahl der Begriffe (`exported_terms`,
   `internal_terms`) im BC.
3. Liste neu hinzugefuegter Begriffe mit jeweils einer Zeile
   Definition.
4. Ingest-Report (gekuerzte JSON-Sicht reicht: `glossary.discovered`,
   `glossary.inserted`, `glossary.updated`, `glossary.deleted`,
   `glossary.errors`).
5. Bestaetigung: alle drei Verifikationsschritte aus §4 gruen.
6. Falls Diff-Analyse leer war: Begruendung mit Bezug auf §1.2-1.3 und
   die heute indizierten Begriffe.

## 6. Sub-Agent-Spielregeln

- Du bist Worker, kein Orchestrator. Keine andere BC anfassen.
- Mocks/Stubs verboten ausser auf expliziter Auftraggeber-Anweisung.
- Keine Umgehung der Lints. Wenn der Lint Begriffe bemaengelt, fixt
  du den Begriff, nicht den Lint.
- Du editierst nur Frontmatter und ggf. eine `## Glossar`-Section
  (nur falls dein BC eine pflegt — heute keiner). Du legst keine
  neuen Top-Level-Dateien an.
- Du fuehrst `concept_ingest(strategy="full")` nicht selbststaendig
  aus — `delta` reicht in 100 % der Faelle.
- Du commitst nur, wenn der Auftraggeber das ausdruecklich verlangt.
  Sonst gibst du den Diff im Hand-Off zurueck.
