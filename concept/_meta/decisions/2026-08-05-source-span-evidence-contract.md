---
concept_id: META-DEC-2026-08-05-SOURCE-SPAN-EVIDENCE-CONTRACT
title: Concept-Decision-Record — Source-Span-Evidenz statt Modellkopie
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-consistency, nightly, AG3-219]
formal_scope: prose-only
---

# Concept-Decision-Record — Source-Span-Evidenz statt Modellkopie

Datum: 2026-08-05. Record gemaess META-CONCEPT-CONSISTENCY P3/W4 fuer AG3-219.

## 1. Anlass

Der produktive W2-Lauf scheiterte fuer Chunk
`835df473-af0b-5166-bd43-9bd2937d1239` mit
`INVALID_EVALUATION_RESPONSE`. Die Messung zeigte keinen Typografiefehler:
Gemini behielt den Halbgeviertstrich bei, setzte aber die physisch getrennten
Quellzeilen `Orchestrierungs- und\nBusiness-Kern` zu fortlaufender Prosa mit
Leerzeichen zusammen. Alle sechs gemeldeten Assertions drifteten auf dieselbe
Weise. W3 verlangte in `scope_policy._validate_locus` denselben kopierten
Assertion-String und teilte damit den strukturellen Defekt.

Der exakte Substring-Check aus AG3-179 war richtig. Falsch war der
Antwortvertrag, der ein Sprachmodell zur zeichengenauen Reproduktion der
Evidenz verpflichtete.

## 2. Entscheidung

### 2.1 Neue, getrennte Antwortvertraege

W2 wechselt auf `authority-prose/v2`, W3 auf `scope-consistency/v2`. Die
jeweiligen v1-Vertraege werden nicht unter veraenderter Semantik ausgefuehrt.
Die produktiven Loader referenzieren ausschliesslich die neuen, separat
gehashten v2-Prompt-Assets.

Das Gate nummeriert die physischen Zeilen jedes unveraenderten Quellchunks in
Quellreihenfolge deterministisch als `s000000`, `s000001`, ... . Der Bewerter
liefert keinen kopierten Text:

- W2: `source_id`, inklusive `start_id` und `end_id`, `scopes`;
- W3: je Locus `source_id`, inklusive `start_id` und `end_id`.

Start- und End-ID bezeichnen inklusive die erste und letzte physische
Quellzeile. Die deterministische Policy weist fremde IDs, ausserhalb liegende
Grenzen, umgekehrte Reihenfolge, leere beziehungsweise nur aus Whitespace
bestehende Bereiche, Ueberlappungen und Bereiche ueber 2000 Zeichen als
ungueltige Evaluationsantwort zurueck. Sie schneidet den validen Bereich selbst
aus dem gate-eigenen Originaltext. LF und CRLF werden weder ersetzt noch
normalisiert. Es gibt keinen Fuzzy-, Whitespace- oder Unicode-Vergleich.
Die Groessengrenze liegt oberhalb der am 2026-08-05 gemessenen laengsten
physischen Korpuszeile (1435 Zeichen), sodass jede einzelne Quellzeile
referenzierbar bleibt, aber ein unplausibel grosser Mehrzeilenbereich hart
endet.

W2 leitet Dokument und Anker aus dem bewerteten Chunk ab. W3 leitet Dokument,
Anker und Assertion aus der bewerteten Scope-Partition ab. Das Modell kann diese
Metadaten dadurch weder abschreiben noch erfinden.

W2 validiert Ueberlappungsfreiheit ueber alle gemeldeten Aussagen eines
Chunks. W3 validiert sie je Widerspruchsgruppe: Innerhalb einer Gruppe waere
eine Ueberlappung kein zweiter unabhaengiger Locus; zwischen Gruppen darf eine
Aussage wiederverwendet werden, damit beispielsweise A↔B und A↔C gleichzeitig
darstellbar bleiben.

W3 bemisst Partitionen am vollstaendig gerenderten v2-Prompt, nicht am
Quelltext vor Einfuegen von Zeilenmarkern, JSON und Template. Das harte Limit
von 30000 Zeichen liegt mit Reserve unter der in AG3-179 reproduzierten
Qwen-Fehlerkante bei 35666 Zeichen. Uebergrosse Gruppen werden deterministisch
geteilt; passt ein einzelner vollstaendiger Chunk nicht, ist das ein
fail-closed `DISCOVERY_FAILURE` und kein Anlass zum Abschneiden. Aufrufer
duerfen das Limit fuer Diagnosezwecke weiter absenken, aber nicht erhoehen.

Die Partitionen eines Scope-Sets sind disjunkt und werden jeweils isoliert
bewertet. W3 prueft damit Widersprueche innerhalb jeder einzelnen Partition,
aber keine Widersprueche zwischen Chunks aus verschiedenen Partitionen. Ein
Scope-Set mit mehr als einer Partition ist deshalb kein vollstaendiger
Konsistenznachweis: Der Lauf bewertet weiterhin alle seine Partitionen, endet
aber mit einem benannten `INCOMPLETE_SWEEP`, der Scope und Partitionszahl nennt
und die ungeprueften Cross-Partition-Widersprueche als Grund ausweist. Nur ein
Scope-Set, das vollstaendig in genau eine Partition passt, kann durch einen
befundfreien W3-Lauf als vollstaendig geprueft gelten.

### 2.2 Befunde und Baseline

`AuthorityFinding.assertion`, `FindingLocus.assertion` und ihre Baselinekeys
behalten den Aussage-String. Der String stammt ab v2 ausschliesslich aus der
gate-seitigen Extraktion und ist daher per Konstruktion im Chunk enthalten,
einschliesslich aller Zeilenumbrueche.

Die gemeinsame Datei `concept/_meta/authority-prose-baseline.yaml` wurde am
2026-08-05 gegen den Arbeitsbaum geprueft: Sie hat `version: 1` und
`entries: []`. Ihr Dokumentschema muss deshalb nicht geaendert werden. Es gibt
keine Migration und keinen Doppel-Lesepfad. Waere ein Eintrag mit
`authority-prose/v1` oder `scope-consistency/v1` vorhanden, koennte er wegen
der Promptversion im exakten Schluessel keinen v2-Befund unterdruecken und
wuerde fail-closed als `STALE_BASELINE` neben dem neuen aktiven Befund
erscheinen. Beide Faelle sind durch Unit-Tests festgeschrieben.

### 2.3 Verhaeltnis zum AG3-179-Record

Dieses Record ersetzt ausschliesslich den in
`2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.11/2.11a beschriebenen
**Transport** der Evidenz als `QuotedAssertion` und den daran anschliessenden
Substring-Test. Der dort gehaertete Woertlichkeitsanspruch bleibt
uneingeschraenkt bestehen und wird durch die gate-seitige Extraktion staerker:
Abweichender Text kann nicht mehr Bestandteil einer gueltigen v2-Antwort sein.
Rand 2.11b zur fail-closed Zurueckweisung kollidierender JSON-Schluessel bleibt
unveraendert gueltig.

### 2.4 Transportfehler, Antwortfinalitaet und Backend-Lease

Eine Bewertung bindet weiterhin genau das Backend, das die stabile W2-Chunk-
beziehungsweise W3-Partitionsroute bestimmt. Sie erfordert aber keine
gleichzeitige Lease aller konfigurierten Backends: Der Hub-Transport erwirbt
erst beim Senden eine Lease ausschliesslich fuer das geroutete Backend. Bei
einem Wechsel der Route wird die vorherige Lease freigegeben und fuer das neue
Backend eine eigene Lease erworben. Die Vielfalt des Pools ueber den Korpus
bleibt damit erhalten, ohne dass die Bereitschaft unbeteiligter Backends zur
Vorbedingung einer einzelnen Bewertung wird.

Nur wenn der Aufruf keine Antwort geliefert hat, darf das Gate denselben
Prompt an dasselbe Backend erneut senden. Das umfasst fehlgeschlagenen
Lease-Erwerb, nicht bereites Backend, Sessionverlust, Timeout und fehlende
Antwort. Die Grenze ist fest und nicht laufzeitkonfigurierbar: hoechstens vier
Versuche mit 5, 10 und 20 Sekunden Backoff. Die insgesamt 35 Sekunden
ueberbruecken das am 2026-08-05 gemessene selbstheilende 32-Sekunden-Fenster.
Nach dem vierten fehlgeschlagenen Versuch endet der Lauf fail-closed mit einem
benannten Transportfehler, der Backend, Chunk beziehungsweise Partition,
letzte Ursache und Zahl der Versuche traegt.

Sobald der Transport einen Antworttext geliefert hat, ist diese Bewertung
endgueltig. Parser und deterministische Policy duerfen weder eine syntaktisch
ungueltige Antwort noch einen `INVALID_EVALUATION_RESPONSE`-Befund durch eine
zweite Modellantwort ersetzen. Insbesondere gibt es keinen Backend-Fallback:
Er wuerde die deterministisch zugewiesene Bewertungsfunktion austauschen und
damit aus Infrastrukturtransienz Urteilszufall machen. Der Quellspannen-,
Woertlichkeits- und Baselinevertrag aus 2.1 bis 2.3 bleibt unveraendert.

## 3. Verworfene Alternativen

- Whitespace- oder Newline-Normalisierung wurde verworfen, weil sie neben dem
  gemessenen Zeilenumbruch auch eine inhaltliche Abweichung gleicher Groesse
  unsichtbar akzeptieren wuerde.
- Unicode-Normalisierung und Fuzzy-Matching wurden aus demselben Grund
  verworfen. Die widerlegte Typografie-Hypothese ist kein Reparaturziel.
- Zeichenoffsets wurden verworfen, weil das Modell dann weiterhin exakt
  zaehlen muesste. Deterministische physische Zeilen-IDs sind kompakter,
  erhalten harte Umbrueche und vergroessern W3-Partitionen nur proportional
  zur Zeilenzahl.
- Eine semantische Umdeutung von `authority-prose/v1` wurde verworfen, weil
  derselbe Versionsname dann zwei inkompatible Antwortbedeutungen bezeichnete.
- Die Epoch-Lease ueber alle konfigurierten Backends wurde verworfen, weil je
  Bewertung nur das deterministisch geroutete Backend antwortet. Gleichzeitige
  Bereitschaft unbeteiligter Browser-Sitzungen ist kein Bestandteil eines
  Bewertungsurteils.
- Ein Fallback auf ein anderes gesundes Backend wurde verworfen, weil er die
  stabile Route und damit die Identitaet des Bewerters nach einem Fehler
  veraendern wuerde.
- Retry auf Parser- oder Policy-Ablehnung wurde verworfen, weil bereits eine
  Antwort vorliegt. Ein zweites Urteil koennte den ersten Befund zufaellig
  ueberstimmen und wuerde Fail-closed verletzen.
- Ueberlappende beziehungsweise paarabdeckende Partitionen wurden in AG3-219
  nicht umgesetzt. Sie koennten Cross-Partition-Paare sichtbar machen, sind
  aber kombinatorisch teuer und benoetigen vorab eine PO-Entscheidung ueber die
  zulaessigen Kosten; diese Entscheidung und Umsetzung liegen in AG3-221.

## 4. Impact-Sweep

Der semantische und lexikalische Sweep umfasste den W2-/W3-Owner
`META-CONCEPT-CONSISTENCY`, FK-78 §78.14, beide urspruenglichen Decision
Records, Prompt-/Parser-/Policy-/Baseline-Code unter
`tools/concept_governance/`, beide CLI-Wrapper, Jenkins-Wiring, die gemeinsame
Baseline, die Governance-Tests sowie die gemessene FK-10-Passage. Die
CLI-Wrapper importieren die versionierten Konstanten und brauchen keinen
eigenen Protokollpfad. Fuer Runde 3 wurden zusaetzlich Epoch-Lease, Routing,
Transportfehlerklassifikation, W2-/W3-Evaluatorgrenzen und deren Negativtests
geprueft. Runde 5 pruefte ausserdem die Vollstaendigkeitsaussage an der Grenze
zwischen geschlossenem Scope-Set und disjunkter Partitionsbewertung. FK-10
bleibt unveraendert; harte Zeilenumbrueche sind gueltiger Korpusinhalt.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|---|---|---|
| `concept/_meta/konzept-konsistenz-governance.md` W2/W3 | geaendert | Normativer Owner beschreibt v2-Quellspannen, Validierung und unveraenderte Woertlichkeit. |
| FK-78 §78.14 | geaendert | Ordnet den AK3-eigenen Hub-Batch-Vertrag ein und grenzt die extrahierte Evidenz vom unveraenderten Receipt-Feld ab. |
| Dieses Decision Record | neu | Persistiert Ursache, Vertragsversionierung, Baselinebehandlung und Impact-Sweep. |
| `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.11–2.11b | referenziert-jetzt | Woertlichkeit und Key-Collision bleiben; nur der kopierte Evidenztransport und sein Substring-Test werden durch v2 ersetzt. |
| `tools/concept_governance/` und v2-Prompts | geaendert | Erzeugen Zeilen-IDs, parsen Referenzen, validieren Bereiche und extrahieren Originaltext fuer W2/W3. |
| `scripts/ci/check_concept_authority_prose.py` | geprueft, nicht geaendert | Der Wrapper bezieht Promptversion und produktiven Evaluator aus dem geaenderten Owner-Code. |
| `scripts/ci/check_concept_scope_consistency.py` | geaendert | Der Wrapper bezieht Promptversion und produktiven Evaluator aus dem geaenderten Owner-Code; sein Partitionsdefault wurde von 48.000 auf `DEFAULT_PARTITION_MAX_CHARS` (30.000) umgestellt. |
| `concept/_meta/authority-prose-baseline.yaml` | geprueft, nicht geaendert | `version: 1`, `entries: []`; v1-Schluessel waeren exakt und fail-closed stale. |
| Governance Unit-/Contract-Tests | geaendert | Beweisen LF-Regression, Extraktion, Negativfaelle, v2-Schemas und stale v1-Baselines fuer W2/W3. |
| FK-10 und uebriger Konzeptkorpus | nicht-betroffen | Quellprosa und harte Umbrueche werden nicht an das Gate angepasst. |
| Generische Zielprojekt-Toolchain und Semantik-Receipt-Schema | nicht-betroffen | AG3-219 aendert ausschliesslich die AK3-eigenen W2/W3-Antwortvertraege und trifft keine neue Aussage zur Provenienz des generischen `statement`-Felds. |
| `tools/concept_governance/{transport_retry,evaluator,scope_evaluator,hub_batch,hub_lease}.py` | geaendert | Trennt unbeantwortete Transportversuche sichtbar von finalen Modellantworten und ersetzt die Pool-Gesamtlease durch lazy Ein-Backend-Leases. |
| `tools/concept_governance/{scope_runner,scope_run_findings}.py` | geaendert | Wertet disjunkte Partitionen weiter aus, meldet mehrfach partitionierte Scope-Sets aber benannt als unvollstaendig, weil Cross-Partition-Widersprueche ungeprueft bleiben. |
| FK-78 §78.14 | geaendert | Verankert Antwortfinalitaet, festen Retry-Rahmen, Exhaustion-Nachweis und die Lease nur fuer das geroutete Backend. |
| Hub-Projekt und Hub-Konfiguration | nicht-betroffen | Die Reparatur liegt vollstaendig auf der AK3-Seite der Fremdsystemgrenze; der laufende Hub wird weder geaendert noch gestartet. |
