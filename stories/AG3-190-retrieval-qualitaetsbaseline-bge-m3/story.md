# AG3-190 — Retrieval-Qualitaetsbaseline und Nichtregression bge-m3

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-181"]`
- **Quell-Konzept:** FK-13 §13.2 (Modellpin), FK-13 (Retrieval-Oberflaeche)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-8 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

## Kontext

### Befund

Der Wechsel des Einbettungsmodells auf `BAAI/bge-m3` (Commit `8d80586a`,
2026-08-02) war fachlich vermutlich richtig und ist **bis heute nicht
gemessen**. Es gibt keinen Vorher-/Nachher-Vergleich auf dem eigenen Korpus,
keine benannte Metrik und keine Schwelle, unter der der Wechsel als
Verschlechterung gaelte.

Der Anlass des Wechsels ist zugleich der Beleg dafuer, dass Selbstauskunft hier
nicht traegt: Die Drift-Erkennung funktionierte einwandfrei und war negativ
getestet — sie setzte nur den **falschen Wert** durch (`masked_mean` statt
`cls`, `CLAUDE.md`, Anlassfall 2026-08-02). Ein Mechanismus kann korrekt sein
und trotzdem das Falsche liefern. Fuer die Retrieval-Qualitaet gilt dasselbe:
dass Suchanfragen Treffer liefern, sagt nichts darueber, ob es die richtigen
sind.

### Warum diese Story hinter AG3-181 haengt

Der erste Schnitt hatte diese Messung in AG3-183 und liess AG3-181 an AG3-183
haengen. Damit haette die Messung einen Zustand bewertet, in dem der
Modellvertrag noch offen war: falscher Tokenizer, Budget ueber das falsche
Feld, Altchunks nach alter Bemessung in derselben Collection. Ein Ergebnis aus
diesem Zustand ist nicht interpretierbar — weder ein gutes noch ein schlechtes.

## Scope

### In Scope

- Ein versionierter Query-/Relevanzkorpus fuer den AK3-eigenen Konzept- und
  Story-Bestand.
- Eine benannte Retrieval-Metrik mit Mindestschwelle.
- Ein reproduzierbarer Aufbau des **Vorher**-Zustands (Modell vor dem Wechsel).
- Die Messung selbst, gegen echtes Weaviate, in beide Richtungen.
- Ein Abbruchkriterium bei Verschlechterung.

### Out of Scope

- **Keine Modellauswahl.** Diese Story misst; sie entscheidet nicht ueber einen
  Wechsel. Ergibt die Messung eine Verschlechterung, ist das ein Befund fuer den
  PO, keine Ermaechtigung, das Modell zu tauschen.
- Der Modellvertrag selbst (Tokenizer, Budget, Re-Ingest) — **AG3-181**.
- Die Verankerung des Laufs in der CI und die Vertragsmatrix — **AG3-183** /
  **AG3-194**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `tests/golden/retrieval/` (Query-/Relevanzkorpus) | neu | versionierte Bewertungsgrundlage, bewusst reviewpflichtig |
| `tests/e2e/vectordb/test_retrieval_quality.py` | neu | die Messung gegen echtes Weaviate |
| `src/agentkit/backend/vectordb/` | geaendert | falls fuer den reproduzierbaren Vorher-Aufbau eine parametrierbare Collection noetig ist |
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` | geaendert | Metrik, Schwelle und ihr Eigentuemer |
| `concept/_meta/decisions/2026-XX-XX-retrieval-qualitaetsbaseline.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Ein versionierter Query-/Relevanzkorpus existiert.** Er enthaelt Anfragen
   mit erwarteten Treffern aus dem **eigenen** Bestand (Konzepte und Stories),
   und er liegt unter Versionskontrolle mit bewusster Aktualisierungspflicht.
   Ein Korpus, der aus den Suchergebnissen des aktuellen Modells erzeugt wurde,
   erfuellt dieses Kriterium **nicht** — er misst das Modell gegen sich selbst.
   Die Herkunft jeder Relevanzaussage ist im Korpus vermerkt.
2. **Die Metrik ist benannt und begruendet.** Genau eine Hauptmetrik mit
   ausgeschriebener Definition, plus eine Mindestschwelle. „Besser" oder
   „liefert Treffer" ist keine Metrik.
3. **Der Vorher-Zustand ist reproduzierbar aufgebaut**, nicht erinnert: das
   Modell vor dem Wechsel wird tatsaechlich noch einmal gefahren, mit dem
   Tokenizer und den Budgets, die zu ihm gehoerten. Das Kommando steht im
   Story-Record. Ein Vergleich gegen eine Zahl aus einem alten Protokoll
   erfuellt dieses Kriterium nicht.
4. **Beide Messungen laufen gegen echtes Weaviate**, auf demselben Korpus, mit
   demselben Ablauf. Faellt der Dienst aus, ist das eine **benannte Luecke** mit
   Grund — nie „gruen", nie ein Ergebnis.
5. **Das Ergebnis ist eine Zahl mit Urteil.** Der Story-Record nennt beide
   Messwerte, die Differenz, die Schwelle und die Schlussfolgerung.
6. **Verschlechterung bricht ab.** Liegt bge-m3 unter der Schwelle, wird die
   Story **nicht** abgeschlossen; der Befund geht mit Zahlen an den PO. Es gibt
   keinen Pfad, auf dem eine gemessene Verschlechterung durch eine Begruendung
   ersetzt wird.
7. **Die Messung ist wiederholbar und wird kuenftig zur Nichtregression
   benutzt.** Wer das Modell, den Tokenizer oder das Chunk-Budget aendert, hat
   damit eine Vergleichsgrundlage. Der Eigentuemer der Schwelle steht in FK-13.
8. **Konzept nachgezogen** (FK-13: Metrik, Schwelle, Eigentuemer) mit Decision
   Record und Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Zahlen).
- Beide Messungen gefahren; Kommandos und Ausgaben im Story-Record.
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Alle deterministischen Konzept-Gates gruen; Decision Record im Diff oder
  gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.2
- `concept/_meta/decisions/2026-08-02-modellpin-folgt-der-laufenden-infrastruktur.md`

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 4.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 6: kein Weg, eine gemessene
  Verschlechterung wegzuerklaeren.
- `PROJECT_STRUCTURE.md` §tests Regel 5 — Golden Files sind versioniert,
  Aktualisierung erfordert bewussten Review.
