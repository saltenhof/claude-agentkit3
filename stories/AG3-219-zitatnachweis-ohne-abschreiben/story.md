# AG3-219 — Ein Sprachmodell soll auf Text zeigen, nicht ihn abschreiben

- **Typ:** bugfix
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Blockiert:** alle offenen Storys (Pflicht-Gate der Definition of Done)
- **Quell-Konzept:** FK-78 (Concept-Governance, LLM als Bewertungsfunktion),
  AG3-159 (`scope_policy._validate_locus`), AG3-179 (Haertung des W2-Pfads)

## Befund — belegt, mit Locator

Am 2026-08-05 lief `scripts/ci/check_concept_authority_prose.py` erstmals seit
drei Tagen wieder gegen den echten Arbeitsbaum (der Multi-LLM-Hub war
ausgefallen). Zwei Laeufe hintereinander, identisches Ergebnis:

```
concept-authority-prose: ERROR (errors=1, reports=0)
[ERROR] INVALID_EVALUATION_RESPONSE
  technical-design/10_runtime_deployment_speicher.md#10-1-0-architektur-leitbild-ak3-backend-als-deterministischer-kern-002
  assertion='reported quote is absent from ...'
  prompt=authority-prose/v1  model=governance-pool/v1
```

**Das ist kein Befund ueber FK-10.** Das Gate hat die Antwort seines Bewerters
verworfen, weil das gemeldete Zitat im geprueften Chunk nicht woertlich
vorkommt. Dieses Verhalten ist richtig und soll bleiben. Falsch ist, dass es
**reproduzierbar** passiert.

## Warum es passiert — und warum die naheliegende Reparatur die falsche ist

`tools/concept_governance/policy.py:53-86` (`_require_verbatim_quote`) prueft
bewusst hart:

> „The check is deliberately identical to W3's: an exact substring test against
> the chunk text that was sent to the model, no normalization of whitespace or
> case. Anything softer would accept a quote that the corpus does not contain."

Die Begruendung im Docstring ist stichhaltig und bleibt gueltig: Vor AG3-179 las
W2 die Antwort und sah den Chunk nie wieder; ein abgedriftetes Zitat war von
einem korrekten Befund ununterscheidbar. Das dort genannte Beispiel — `C:\new`
ist syntaktisch gueltiges JSON und dekodiert zu `C:` + Zeilenumbruch + `ew` —
zeigt, dass **keine Parser-Heuristik** die Luecke schliessen kann.

Die Haertung ist also nicht das Problem. Das Problem ist die **Anforderung, die
sie an den Bewerter stellt**: ein Sprachmodell soll einen Textausschnitt
zeichengenau reproduzieren.

### Gemessene Ursache (2026-08-05, Chunk `835df473-af0b-5166-bd43-9bd2937d1239`, Bewerter `gemini`)

Gemeldete Assertion:

```
Das **AK3 Backend** ist der **deterministische Orchestrierungs- und Business-Kern** von AK3
```

Chunkinhalt an derselben Stelle:

```
Das **AK3 Backend** ist der **deterministische Orchestrierungs- und
Business-Kern** von AK3
```

Der Unterschied, zeichengenau:

```
Modell: ... Orchestrierungs- und Business-Kern ...
Chunk:  ... Orchestrierungs- und
Business-Kern ...
```

**Das Modell setzt hart umgebrochene Quellzeilen zu fortlaufender Prosa zusammen
und ersetzt den physischen Zeilenumbruch durch ein Leerzeichen.** Alle sechs
zurueckgegebenen Assertions scheiterten aus genau diesem Grund.

**Ausdruecklich widerlegt:** Die urspruengliche Vermutung dieser Story war eine
Normalisierung deutscher Typografie (Anfuehrungszeichen, Halbgeviertstriche,
Pfeile). Sie ist **nicht** die Ursache — im laengsten gemessenen Beispiel blieb
der Halbgeviertstrich unveraendert erhalten:

```
... prueft diese Arbeit — er ersetzt sie nicht ...
```

Die Vermutung stand hier als Tatsache, bevor sie gemessen war. Sie bleibt als
widerlegt stehen, damit niemand sie erneut aufgreift.

Der Substring-Test sieht die Abweichung — korrekt — und lehnt ab. Damit stehen
sich zwei richtige Anforderungen im Weg.

**Die falsche Reparatur waere, den Vergleich weicher zu machen** (Unicode-
Normalisierung, Whitespace-Toleranz, Fuzzy-Matching). Sie wuerde genau die
Luecke wieder oeffnen, die AG3-179 geschlossen hat, und zwar unsichtbar: jede
Toleranz, die eine Typografie-Abweichung durchlaesst, laesst auch eine
inhaltliche Abweichung derselben Groesse durch.

## Der Schnitt

**Ein Sprachmodell soll nicht Text abschreiben, sondern auf Text zeigen.**

Der Bewerter liefert kuenftig keinen kopierten String als Evidenz, sondern eine
**Referenz in den Chunk** — etwa Zeilen- und Spaltenbereich, Zeichenoffset oder
eine vom Gate vergebene Satz-/Absatznummer. Das Gate schneidet das Zitat
**selbst** aus dem Chunk heraus, **einschliesslich aller Zeilenumbrueche**.
Damit gilt:

- Das Zitat ist per Konstruktion woertlich; ein Abschreibfehler ist unmoeglich.
- Der Substring-Test aus AG3-179 wird nicht aufgeweicht — er wird
  **gegenstandslos**, weil das Gate die Quelle selbst besitzt.
- Eine unzulaessige Referenz (ausserhalb des Chunks, leer, unplausibel) bleibt
  ein `INVALID_EVALUATION_RESPONSE` — fail-closed wie bisher.

Der Baselinekey, der heute den Zitattext traegt, muss den neuen Nachweis
sinnvoll abbilden, ohne dass bestehende Baselines still ihre Bedeutung
verlieren. Wie das geloest wird, gehoert in einen Decision Record.

## Zweiter Befund (2026-08-05, nach Behebung des Zitatvertrags)

Der urspruengliche `INVALID_EVALUATION_RESPONSE` ist **weg** — der v2-Vertrag
traegt. An seine Stelle trat ein anderer Fehler, in vier Laeufen viermal:

```
Lauf 1  EVALUATION_TRANSPORT_FAILURE  gemini   lease_id ... not found in registry for slot 0
Lauf 2  EVALUATION_TRANSPORT_FAILURE  chatgpt  W2 Hub epoch lease omitted a configured backend
Lauf 3  EVALUATION_TRANSPORT_FAILURE  gemini   login state unknown (page not ready)
Lauf 4  EVALUATION_TRANSPORT_FAILURE  grok     login state unknown (page not ready)
```

**Jedes Mal ein anderes Backend, jedes Mal eine andere Stelle im Korpus, nie
derselbe Fehler.** Das ist kein Vertragsdefekt, sondern Transienz.

### Die strukturelle Ursache

Das Gate verlangt eine Epoch-Lease ueber **alle** konfigurierten Backends. Die
Backends des Multi-LLM-Hubs sind browsergetriebene Sitzungen mit kurzen
Nicht-Bereit-Fenstern; fuer Gemini wurde am 2026-08-05 eines von 32 Sekunden
gemessen, das sich **selbst heilte** (SPA-Navigation, Content-Script kurz
abgeraeumt). Ueber einen Lauf mit rund vierzig Chunks trifft mindestens eines
dieser Fenster nahezu sicher zu.

**Ein Gate, das nur gruen wird, wenn fuenf Browser gleichzeitig ruhig sind,
wird nie gruen** — und was nie gruen wird, wird abgeschaltet.

### Warum ein begrenzter Retry hier kein Aufweichen ist

`EVALUATION_TRANSPORT_FAILURE` ist **kein Urteil ueber den Korpus**. Es sagt
nicht „die Prosa ist in Ordnung" und nicht „sie ist es nicht" — es sagt „ich
konnte nicht fragen". Diese Unterscheidung ist entscheidend: Ein Retry auf
einem Transportfehler wiederholt eine **unbeantwortete** Frage; er ueberstimmt
keine Antwort. Fail-closed bleibt vollstaendig erhalten, denn ein Befund des
Bewerters wird niemals wiederholt.

Die Hub-Diagnose vom 2026-08-05 hat zwei Klassen belegt:

- **transient und selbstheilend** (Gemini-Navigationsfenster, ~32 s),
- **verklemmt** (Qwen-Zustandsmaschine, brauchte einen Adapter-Neustart).

Ein begrenzter Retry mit Backoff trennt beide korrekt: die erste Klasse
verschwindet, die zweite scheitert weiterhin — und zwar **benannt**, mit der
Zahl der Versuche. Genau das will `CLAUDE.md` §REALITAETSNACHWEIS: keine
stille Toleranz, aber auch kein Nachweis, der an fremder Infrastruktur
scheitert und dann als Qualitaetsaussage gelesen wird.

## Scope

### In Scope

- Der W2-Pfad (`authority-prose/v1`) liefert eine Referenz statt eines Zitats;
  `tools/concept_governance/policy.py` schneidet das Zitat selbst aus.
- Prompt und Antwortvertrag werden entsprechend gezogen.
- **W3 (`scope_policy._validate_locus`) wird mitgezogen**, wenn dort dieselbe
  Anforderung besteht. Der Docstring sagt ausdruecklich, der W2-Check sei
  „deliberately identical to W3's" — dann teilt W3 auch den Defekt. Pruefen und
  im Ergebnis benennen; falls W3 nicht betroffen ist, begruenden warum.
- Ein reproduzierender Test auf genau dem Chunk, an dem es heute scheitert.
- Decision Record fuer den geaenderten Antwortvertrag und den Umgang mit
  bestehenden Baselines.

### Out of Scope

- **Keine Aufweichung des Woertlichkeitsanspruchs.** Kein Fuzzy-Match, keine
  Unicode-Normalisierung, keine Whitespace-Toleranz als Loesung.
- Keine Aenderung an `concept/technical-design/10_runtime_deployment_speicher.md`.
  Die Typografie dort ist zulaessig; die Prosa dem Werkzeug anzupassen waere die
  Umkehrung der Verantwortung. Wer den Abschnitt umschreibt, um das Gate gruen
  zu bekommen, hat den Defekt verschoben, nicht behoben.
- Kein Ausnahmemechanismus, der einzelne Chunks von der Pruefung befreit.

## Akzeptanzkriterien

1. **Der heute scheiternde Lauf ist gruen.**
   `check_concept_authority_prose.py --mode pre-merge --base HEAD` liefert kein
   `INVALID_EVALUATION_RESPONSE` mehr fuer
   `10_runtime_deployment_speicher.md#10-1-0-...-002`. Beleg: die echte Ausgabe
   zweier aufeinanderfolgender Laeufe.
2. **Das Zitat ist per Konstruktion woertlich.** Ein Test beweist, dass ein vom
   Bewerter gelieferter Verweis immer zu einem Ausschnitt fuehrt, der im Chunk
   steht. **Der zentrale Regressionstest deckt den gemessenen Fall ab: eine
   Passage ueber einen harten Zeilenumbruch hinweg (`und\nBusiness-Kern`).**
   Tests mit typografischen Sonderzeichen duerfen ergaenzend bestehen, aber
   nicht als reproduzierte Ursache bezeichnet werden — sie ist widerlegt.
3. **Fail-closed bleibt.** Eine unzulaessige Referenz (ausserhalb des Chunks,
   leer, ueberlappend, unplausibel gross) erzeugt weiterhin
   `INVALID_EVALUATION_RESPONSE`. Negativtest je Fall.
4. **Der Woertlichkeitsanspruch ist nicht aufgeweicht.** Nachgewiesen dadurch,
   dass ein absichtlich abgedriftetes Zitat weiterhin abgelehnt wird — der
   AG3-179-Fall (`C:\new`) bleibt ein Fehler.
5. **W3 ist geprueft.** Entweder mitgezogen oder mit Begruendung als nicht
   betroffen ausgewiesen.
6. **Bestehende Baselines verlieren ihre Bedeutung nicht still.** Was mit ihnen
   geschieht, steht im Decision Record und ist getestet.
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- **Realitaetsnachweis:** AC 1 verlangt den Live-Lauf gegen den echten
  Multi-LLM-Hub. Gruene Unit-Tests sind Voraussetzung, nie Nachweis
  (`CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN). Ist der Hub nicht
  erreichbar, ist das eine benannte Luecke mit Grund — nie „gruen".
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — die Anforderung an den Bewerter
  ist das Modell, der Substring-Test ist nur die Stelle, an der es auffaellt
- `CLAUDE.md` §NO ERROR BYPASSING — kein weicherer Vergleich als „Kompromiss"
- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN
- FK-78 §78.14 — LLM nur als Bewertungsfunktion, kein Werkzeug entscheidet frei
