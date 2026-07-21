<!-- Codex job-a67ac1e2, resumed from job-8fce8e42, read-only. Loesungsdesign auf Anforderung des PO. -->

# Lösungsdesign: Human Assurance für normative Aussagen

## Kernurteil

Die Richtung trägt, aber mit drei wesentlichen Korrekturen:

1. `agent_authored` ist Herkunft, kein Ratifikationsstatus.
2. `po_informed` darf keinerlei Zustimmungswirkung haben; Schweigen ist nur nachweisbare Exposition, keine schwache Ratifikation.
3. Ratifikation darf nie abschnittsweise vererbt werden. Zulässig ist nur eine explizit aufgezählte Menge konkreter Aussage-Revisionen.

Die Frage des PO ist außerdem leicht falsch gestellt: Ein Agent darf auch gegen eine unratifizierte aktive Norm nicht einfach verstoßen. Er darf sie anfechten. Ratifikation entscheidet nicht, ob die Norm gilt, sondern wer den Konflikt abschließend auflösen darf.

## 1. Eigener Ist-Befund

### Was heute tatsächlich existiert

AK3 trennt bereits vier Statusachsen:

- Decision-Lifecycle
- lauflokale `promotion_disposition`
- korpusweiten `assertion_status`
- projektionsbezogenen `equivalence_status`

Das ist im [Assertion-Authority-Vertrag](</T:/codebase/claude-agentkit3/concept/_meta/assertion-authority.md:59>) korrekt getrennt. Keine dieser Achsen beschreibt menschliche Bestätigung.

Die laufgebundene Kette ist:

```text
SourceDocument
  → SourceUnit
  → Claim
  → Disposition
  → Atom
  → ProjectionReceipt
  → normative Zielpassage
```

Dabei gilt:

- `source-register.role = PO_DECISION` klassifiziert ein Dokument. Es bindet keine einzelne Aussage und authentifiziert nicht einmal zwingend einen Menschen.
- `author_principal_id` ist Provenienz, aber kein Ratifikationsbeleg.
- `atom-register.normative_status` bezeichnet den fachlichen Geltungscharakter des Atoms, nicht menschliche Bestätigung.
- Projection-Receipts bestätigen semantische Äquivalenz zwischen Atom und Ziel. Sie beweisen ausdrücklich keine PO-Zustimmung; siehe [receipts.py](</T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/receipts.py:239>).

### Zwei Korrekturen an deinem Befund

„Nichts überlebt die Promotion“ ist etwas zu absolut: Werkstattregister können versioniert bleiben, das Projektionsmanifest verweist auf Läufe, und Digests bleiben auditierbar. Was tatsächlich nicht überlebt, ist eine korpusweit stabile, direkt abfragbare Identität der einzelnen normativen Aussage. Die Lauf-ID `ATM-*` ist keine dauerhafte Assertion-ID über mehrere Änderungen hinweg.

Auch behauptet AK3 heute formal noch nicht, eine `PO_DECISION` habe 400 Aussagen ratifiziert. Es gibt gar keinen Ratifikationsstatus. Dieser gefährliche Fehlschluss entstünde erst, wenn man Ratifikation transitiv aus der heutigen Quellenrolle ableitete.

### Bestehender Normkonflikt

Der aktuelle Mandatsvertrag verlangt bei einem Normativkonflikt menschliche Entscheidung; siehe [FK-25 §25.2–25.3](</T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md:163>). Dein gewünschtes agentisches Selbstadjudikationsrecht für unratifizierte Normen wäre daher keine bloße FK-78-Erweiterung. Es ändert mindestens:

- FK-25 und den formalen Kontext `exploration`
- Eskalationssemantik
- `CLAUDE.md` zur Konzepttreue
- Concept-Incubation-Promotion und Toolchain
- den Assertion-Authority-Vertrag

## 2. Die Achsen müssen orthogonal bleiben

Ratifikation gehört nicht als weiterer Wert in `assertion_status`. Sonst entstünde ein unbeherrschbares Kreuzprodukt wie `active_ratified`, `blocked_projection_ratified`, `superseded_unratified`.

Das Zielmodell hat getrennte Dimensionen:

| Dimension | Frage |
|---|---|
| Authority/Lifecycle | Ist dies die aktuelle normative Aussage? |
| Projection | Sind ihre verpflichtenden Darstellungen äquivalent? |
| Human Assurance | Hat ein autorisierter Mensch genau diese Revision bestätigt? |
| Challenge | Liegt ein konkreter, noch offener Widerspruch vor? |
| Provenienz | Wer oder was hat die Aussage hervorgebracht? |

Die Ausführungsentscheidung wird daraus abgeleitet:

```text
Scope nicht active oder Projektion blockiert
    → Ausführung blockiert, Ratifikation irrelevant

Scope active, kein erkannter Konflikt
    → Norm ist zu befolgen, unabhängig von Ratifikation

Konflikt gegen unratifizierte Norm
    → Agentengremium darf adjudizieren

Konflikt gegen ratifizierte oder ratifiziert-vorgeschützte Norm
    → nur autorisierter Mensch darf adjudizieren
```

Ratifikation macht eine Norm weder wahr noch aktiv. Sie erhöht ausschließlich die menschliche Assurance und verschiebt die Änderungsautorität.

## 3. Granularität: normative Proposition, nicht Satz oder Abschnitt

### Gewähltes Niveau

Die Identitätseinheit sollte die kleinste unabhängig governierbare normative Proposition sein:

> Eine Aussage, über die der Mensch sinnvoll getrennt mit „ja“ oder „nein“ entscheiden könnte, ohne dass notwendige Bedingungen, Ausnahmen oder Fehlsemantik verloren gehen.

Das entspricht dem Atomprinzip aus [ATOM-01 §7](</P:/_private-img2img/concept/_meta/atomare-konzeptpruefung-und-migrationsvalidierung.md:180>), ergänzt um einen Ratifikationstest.

Getrennt wird, wenn Teile:

- unabhängig wahr oder falsch sein können,
- getrennt ratifiziert werden könnten,
- unterschiedliche Authority-Owner besitzen,
- getrennt geändert, implementiert oder getestet werden können,
- unterschiedliche Ausnahmen, Failure-Semantik oder Lifecycle haben.

Nicht getrennt werden:

- Bedingungen und Ausnahmen,
- Scope und Modus,
- zeitliche Reihenfolge,
- Failure-/Retry-Semantik,
- normative Zahlenwerte samt Population und Einheit.

### Physische Adressierung

Für freie normative Prosa braucht es explizite Bereichsmarker:

```markdown
<!-- ASSERTION:BEGIN id=ASR-a17c09ef -->
Ein stale Writer darf einen übernommenen Lock niemals überschreiben
oder freigeben.
<!-- ASSERTION:END id=ASR-a17c09ef -->
```

Regeln:

- keine Verschachtelung,
- keine Überlappung,
- genau ein Authority-Scope,
- Rationale und Evidenz liegen außerhalb des Blocks,
- Digest über den Blockinhalt, ohne Marker, mit minimaler LF-/Unicode-Normalisierung.

Für den Formal-Layer ist das kleinste strukturierte Objekt die Grenze: Invariante, Transition, Command, Event oder Entitätseintrag. Es erhält ebenfalls eine `assertion_id`; der Digest wird über den kanonisch serialisierten semantischen Teilbaum gebildet.

### Warum das stabil bleibt

Identität und Revision werden getrennt:

- `assertion_id` bleibt bei einer Umformulierung stabil.
- `revision_digest` ändert sich.
- Die alte Ratifikation bleibt historisch sichtbar, ist aber für die neue Revision nicht mehr wirksam.

Damit kollabieren Referenzen nicht bei jeder Änderung. Nur die Assurance wird ehrlich stale. Da ausschließlich ratifizierte, angefochtene oder neu berührte Aussagen explizit registriert werden müssen, entsteht auch kein sofortiger 20.000-Aussagen-Umbau.

Ein Split oder Merge erzeugt dagegen neue Assertion-IDs; die alte Identität wird tombstoned beziehungsweise superseded.

## 4. Datenmodell

### 4.1 Dauerhaftes Assertion-Register

Unter `concept/_meta/` sollte eine schema-validierte, nach Authority-Ownern geschärfte Registry entstehen:

```text
concept/_meta/assertions/
  index.json
  by-owner/
    DK-16.json
    FK-78.json
    formal.concept-incubation.invariants.json
  assurance-events/
    <event_id>.json
```

`index.json` führt die vollständige Shard-Menge samt Digests. Dadurch kann niemand einen Shard oder Event still entfernen.

Ein `AssertionRecord` enthält keine Kopie der normativen Aussage:

```text
assertion_id
owner_concept_id
authority_scope_id
locator:
  mode
  path
  marker_id | formal_object_id | selector
revisions[]:
  revision
  content_digest
  introduced_by:
    run_id?
    atom_ids[]
    decision_ids[]
  status: current | superseded
origin:
  kind: agent_synthesized | human_literal | mixed | legacy_unknown
supersedes[]
```

Die normative Aussage bleibt ausschließlich im Authority-Dokument. Das Register trägt Identität, Locator, Digest und Provenienz. Eine `statement`-Kopie im Register würde das Single-Assertion-Prinzip verletzen.

### 4.2 Human-Assurance-Events

Ratifikation ist ein unveränderliches Ereignis:

```text
event_id
event_type:
  presentation_acknowledged
  ratification_granted
  ratification_revoked
subjects[]:
  assertion_id
  revision_digest
issued_by:
  principal_id
  credential_id
  session_ref
issued_at
evidence:
  packet_digest
  corpus_revision
  context_refs[]
signature
```

Wesentliche Regeln:

- `subjects[]` ist eine explizite Liste. Keine Wildcards, Abschnitte oder „alle Nachfahren“.
- Ein Batch-Event ist zulässig, aber jede Assertion-Revision ist einzeln aufgezählt.
- `presentation_acknowledged` beweist nur, dass ein Paket vorlag. Es verändert weder Konfliktregime noch Authority.
- `ratification_revoked` entfernt keine Norm. Es ändert nur die Assurance und muss die ursprüngliche Ratifikation referenzieren.
- Der effektive Status wird aus Events und aktueller Revision abgeleitet, nicht als frei editierbares Flag gespeichert.

### 4.3 Authentizität ist Pflicht

Der heutige `principal_id`-Mechanismus reicht nicht. Ein Agent könnte selbst eine Datei mit `principal_id: po` schreiben.

`po_ratified` darf deshalb nur entstehen, wenn das Event über einen authentifizierten menschlichen Kanal kommt, beispielsweise:

- signierter Git-Commit gegen eine projektseitige Allowed-Signers-Liste,
- detached SSH-/GPG-Signatur,
- authentifizierter Control-Plane-Befehl.

`concept-governance.json` kann Human-Principals, Schlüssel und erlaubte Scopes referenzieren. Der eigentliche Trust Root darf aber nicht durch denselben unautorisierten Agenten änderbar sein. Ohne verifizierbare Authentifizierung lautet das Ergebnis `unverified_attestation`, niemals `ratified`.

Das ist die größte fehlende Komponente deines Proposals.

### 4.4 Verbindung zur Promotion

Die runlokale Atom-ID darf nicht zur dauerhaften Assertion-ID umgedeutet werden: Ein Atom kann nichtnormativ sein, auf mehrere Ziele aufgeteilt werden oder in späteren Läufen anders geschnitten sein.

Stattdessen entsteht:

```text
promotion/assertion-bindings.tsv

atom_id
assertion_id
revision_digest
target_ref
binding_kind: exact | split_part
receipt_ref
```

Closure-Regeln:

- jedes akzeptierte `COVERED_*`-Atom hat mindestens eine Assertion-Bindung;
- jede neue Assertion-Revision besitzt eine direkte Atom-, Decision- oder explizite Neusynthese-Herkunft;
- `COVERED_SPLIT` darf mehrere Assertion-IDs erzeugen;
- `PO_DECISION` allein erzeugt keine Ratifikation;
- eine neue Ratifikation darf erst nach Feststehen des endgültigen Assertion-Digests signiert werden.

`atom-register.normative_status` bleibt unverändert. Ratifikation dort einzubauen wäre die Vermischung zweier Lebenszyklen.

### 4.5 Laufzeitabfrage

Die Toolchain braucht eine strikt read-only Abfrage:

```text
check.py assertion-status --id <assertion_id>
check.py assertion-status --at <path>#<marker-or-formal-id>
check.py assertion-status --scope <scope_id> --json
```

Ergebnis:

```json
{
  "authority_status": "active",
  "projection_status": "equivalent",
  "ratification_status": "unratified",
  "exposure_status": "presented",
  "origin_kind": "agent_synthesized",
  "resolution_authority": "agent_council",
  "open_challenge_ids": [],
  "reason_codes": []
}
```

Ein nicht registrierter Locator ergibt fail-closed:

```text
ratification_status = unratified
origin_kind = legacy_unknown
registration_status = implicit
```

Der Agent muss diese Abfrage nicht für jede normale Codezeile ausführen. Pflichttrigger sind:

- erkannter Konflikt mit einem Konzept,
- beabsichtigte normative Änderung,
- gewünschte Ausnahme,
- Änderung einer bereits ratifizierten Assertion.

## 5. Konfliktregime

### Grundregel

Eine aktive Norm besitzt eine widerlegbare, aber bindende Vermutung der Richtigkeit.

„Unratifiziert“ bedeutet nicht „optional“. Es bedeutet nur: Ein qualifiziertes Agentengremium darf ihre Änderung selbst adjudizieren.

### Challenge-Zustände

```text
NONE
  → OPEN
  → CLASSIFIED
  → AGENT_ADJUDICATION | HUMAN_ESCALATION
  → UPHELD | RESOLVED_BY_PROMOTION | EXCEPTION_GRANTED | WITHDRAWN
```

Jede Challenge bindet:

- `assertion_id` und `revision_digest`,
- konkrete Evidenz oder ein reproduzierbares Gegenbeispiel,
- betroffenen Work- und Authority-Scope,
- Auswirkung,
- gewünschte Lösung,
- Begründung, warum bloße Konformität nicht sachgerecht ist,
- Challenger-Principal und Session.

### Auflösungsautorität

| Assurance | Resolver |
|---|---|
| implizit/unregistriert | unabhängiges Agentengremium |
| unratifiziert | unabhängiges Agentengremium |
| nur präsentiert | unabhängiges Agentengremium |
| ratifiziert | autorisierter Mensch |
| Ratifikation durch Änderung stale | autorisierter Mensch |
| explizit menschlich widerrufen | Agentengremium darf spätere Änderungen adjudizieren |

Die stale Ratifikation muss menschlich geschützt bleiben. Sonst könnte ein Agent die ratifizierte Passage minimal verändern, Ratifikation dadurch stale machen und anschließend selbst die neue Fassung freigeben. Deshalb gilt:

> Eine Assertion mit ratifiziertem Vorgänger darf weder geändert, gesplittet, verschoben noch superseded werden, solange keine menschlich authentifizierte Revisionsfreigabe oder Revocation vorliegt.

### Schutz gegen die Bequemlichkeits-Generalklausel

Ein Implementierungsworker darf seine eigene Challenge nie abschließend entscheiden.

Für agentische Adjudikation gelten:

- unabhängiger Reviewer, anderer Principal und andere Session;
- bei hoher Tragweite Council statt Einzelreview;
- bloße Kosten-, Stil- oder Bequemlichkeitsargumente sind kein zulässiger Challenge-Grund;
- der bestehende Code darf die Norm nicht „durch Realität überstimmen“;
- bis zur Auflösung bleibt die betroffene Landung blockiert;
- `amend` schließt erst, wenn die normative Promotion vollständig gelandet und alle Gates grün sind;
- ein Agent darf in v1 keine normative Ausnahme erteilen;
- agentische Ergebnisse sind nur `uphold` oder `change_via_governed_promotion`.

Ein humaner Resolver darf zusätzlich eine zeitlich und sachlich begrenzte Ausnahme erteilen. Diese braucht Scope, Ablaufbedingung, Owner und sichtbaren Anker.

Damit bleibt das Agentenrecht ein formalisiertes Änderungsrecht, kein Disobedience-Recht.

## 6. Migration der bestehenden Konzeptwelt

### Phase 0: sichere Defaultsemantik

Die vorhandene Konzeptwelt wird nicht als `agent_authored` klassifiziert, sondern:

```text
origin_kind = legacy_unknown
ratification_status = unratified
```

Alle aktiven Normen gelten weiterhin. Es entsteht kein globaler Blocker.

### Phase 1: Register-on-touch

Explizite Assertion-Identitäten werden verlangt, sobald eine Aussage:

- ratifiziert werden soll,
- angefochten wird,
- normativ geändert wird,
- neu entsteht.

Untouched Legacy-Prosa muss nicht vorab atomisiert werden.

### Phase 2: ratifikationsorientierte Priorisierung

Priorität lässt sich aus folgenden Faktoren ableiten:

- Authority-/Referenz-Blast-Radius,
- Sicherheits-, Daten- oder Vertragskritikalität,
- Zahl der Consumer,
- Änderungshäufigkeit,
- vergangene Challenges,
- Zahl abhängiger Projektionen.

Der Wert ist eine Priorisierungsheuristik, kein mathematischer Driftbeweis.

Eine Kennzahl „Ratifikationsdichte“ ist nur zulässig, wenn der Nenner bekannt ist. Bei partieller Inventarisierung muss das Ergebnis etwa lauten:

```text
registered_assertions: 320
current_ratified: 47
legacy_unregistered: unknown
inventory_coverage: incomplete
```

Kein Prozentwert über den Gesamtkorpus ohne vollständiges Inventar.

### Phase 3: menschliche Review-Pakete

Ein Paket darf mehrere Aussagen enthalten, muss aber alle Assertion-IDs und Digests explizit auflisten. Ein Häkchen „Abschnitt ratifizieren“ ist nur eine UI-Abkürzung für diese feste Menge; es erfasst weder spätere Ergänzungen noch implizite Nachfahren.

## 7. Deterministische Checks und falsches Grün

### Mechanisch zuverlässig prüfbar

- Assertion-ID-Eindeutigkeit und Nichtwiederverwendung
- vollständige Shard-/Event-Mengen
- Marker-Paarigkeit, Nichtüberlappung und Locator-Auflösung
- Re-Derivation der Content-Digests
- monotone Revisionen und Tombstones
- Event-Schema und Signatur
- Scope-Berechtigung des Ratifiers
- exakte Subject-Menge ohne Wildcards
- effektiver Ratifikationsstatus einschließlich `stale`
- Schutz ratifizierter Vorgängerrevisionen
- Atom↔Assertion-Bindung in beide Richtungen
- Challenge-State-Machine und Resolver-Berechtigung
- offene Challenge blockiert Landung
- fehlender Registereintrag ergibt niemals ratifiziert
- Ratifikation aktiviert keinen blockierten Projektionsscope

### Nicht mechanisch beweisbar

- ob die Atomgrenze fachlich richtig gewählt wurde,
- ob ein Mensch das Paket verstanden hat,
- ob der Text tatsächlich seinem tieferen Intent entspricht,
- ob Challenge-Evidenz fachlich überzeugt,
- ob zwei Formulierungen semantisch gleich sind,
- ob der Referenzgraph den realen Wirkungsradius vollständig beschreibt.

Hier braucht es weiterhin semantische Reviews. Der deterministische Gate darf nur beweisen: „Ein zulässiger Reviewer hat zu exakt diesem Digest ein Verdict abgegeben“, nicht „die Aussage ist wahr“.

### Vorab erkennbare False-Green-Pfade

1. Ein Block enthält mehrere unabhängig ratifizierbare Aussagen.
2. Qualifikatoren stehen außerhalb des digestierten Blocks.
3. Ein Agent schreibt selbst ein vermeintliches PO-Event.
4. Abschnittsratifikation erfasst spätere Ergänzungen.
5. Ein altes `assertion_id` wird für neue Semantik wiederverwendet.
6. Eine ratifizierte Norm wird erst verändert und danach als unratifiziert agentisch ersetzt.
7. `po_informed` wird im Prompt als schwache Zustimmung dargestellt.
8. Ein format-only-Marker trägt Ratifikation automatisch über eine Inhaltsänderung.
9. Ein Assertion-Shard oder Event wird gemeinsam mit seinem Index entfernt.
10. Ein grünes Projection-Receipt wird als Human-Ratifikation missverstanden.
11. Ein Agentenreviewer ist nur eine zweite Session desselben entscheidenden Akteurs.
12. Eine Coverage-Kennzahl verschweigt unregistrierte Legacy-Aussagen.

Alle zwölf Fälle müssen als Negativtests beziehungsweise explizite Aussagegrenzen in die Konzeption.

## 8. Harte Bewertung deines Proposals

### Richtig

- Ratifikation als digestgebundenes Ereignis
- fail-closed ohne Ratifikation
- Konflikte immer sichtbar machen
- unterschiedliche Auflösungsautorität
- dauerhafte Aussagenidentität
- wirkungsradiusbasierte Priorisierung

### Falsch oder gefährlich

- `agent_authored` als Ratifikationsstufe vermischt Herkunft und Assurance.
- `po_informed` plus „kein Widerspruch“ erzeugt genau die Scheinsicherheit, die du verhindern willst.
- Vererbung per Abschnitt ist nicht bloß erklärungsbedürftig, sondern sollte verboten sein.
- Die bestehende Atomkette liefert noch keine dauerhafte Assertion-Identität; sie ist nur ein guter Seed dafür.
- Ratifikationsdichte ist kein Drift-Risiko, sondern höchstens Assurance-Coverage.
- Ein vollständiges dauerhaftes Register aller 20.000 Aussagen in v1 wäre überkonstruiert.
- Ohne authentifizierte Human Events ist das gesamte Modell wirkungslos: Ein Agent könnte sich selbst die höchste Stufe ausstellen.

## 9. Minimum und Kür

### Minimum, das das PO-Problem wirklich löst

1. Assertion-ID plus exakter Revisionsdigest für ratifizierte, angefochtene und neu berührte Aussagen.
2. Fehlender Eintrag bedeutet `unratified`, nicht Fehler und nicht `agent_authored`.
3. Authentifiziertes, unveränderliches Ratifikationsereignis.
4. Keine Vererbung und keine Wildcards.
5. Read-only Statusabfrage für implementierende Agents.
6. Challenge-Regime mit Agentenresolver für unratifiziert und Humanresolver für ratifiziert.
7. Änderungsverbot für ratifizierte Assertion-Linien ohne menschliche Freigabe.
8. Promotion-Bindung Atom → dauerhafte Assertion.

Das ist der notwendige Kern.

### Kür

- vollständige Korpusatomisierung,
- `presented`-/Exposure-Metriken,
- Ratifikationsdashboard,
- graphbasierte Priorisierung,
- UI für signierte Batch-Ratifikation,
- semantische Diff-Vorschläge,
- assertion-genaue Projection-Graphen,
- automatische Code→Assertion-Kontextpakete,
- Control-Plane-Persistenz und Telemetrie.

## Schlussposition

Ich würde Ratifikation als neuen Meta-Governance-Kontext `assertion-governance` modellieren, nicht in den Laufstatus von `concept-incubation` einbauen. FK-78 produziert Assertion-Bindungen; der Assertion-Authority-Vertrag besitzt Assurance und Challenge-Semantik; Exploration und Implementation konsumieren die daraus abgeleitete Auflösungsautorität.

Der zentrale Satz sollte lauten:

> Jede aktive Norm ist zu befolgen, bis ein formaler Konflikt aufgelöst ist. Bei unratifizierten Normen darf ein unabhängiges Agentengremium die normative Änderung adjudizieren; bei ratifizierten oder ratifiziert vorgeschützten Normen darf dies ausschließlich ein authentifizierter Mensch.

So wird die Konzeptwelt weder unverbindlich noch menschliche Intention vorgetäuscht.