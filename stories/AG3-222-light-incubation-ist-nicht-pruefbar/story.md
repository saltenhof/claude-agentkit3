# AG3-222 — Ein Profil, das die Norm kennt und das Werkzeug nicht

- **Typ:** bugfix
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-78 §78.16 (Proportionalitaet), §78.4 (Gate-Mapping),
  §78.3 (Layout und Felddisziplin)
- **Herkunft:** erster produktiver `LIGHT_INCUBATION`-Lauf, 2026-08-05

## Befund — belegt, mit Locator

Beim Aufsetzen des Laufs
`concept-incubator/runs/2026-08-05-review-vertrag-terminierung-085702c0`
meldet das deterministische Gate:

```
[incubator] INCOMPLETE: INCOMPLETE_CHECK_SET:
skipped=[baseline-rederivation: base_revision kind 'digest' is not diffable]
```

Exit-Code `1`, `"findings": []`, `"complete": false`. **Der Lauf selbst ist in
Ordnung** — das Gate kann ihn nur nicht zu Ende pruefen.

Die Ursache ist ein Widerspruch zwischen Norm und Werkzeug:

| Stelle | Aussage |
|---|---|
| `incubator_check.py:624` | `base_revision.kind = digest` → Baseline-Pruefung grundsaetzlich unvollstaendig („not diffable") |
| `incubator_check.py:648` | `base_revision.kind = git` → verlangt **alle** Dateien saemtlicher `concept_roots` |
| FK-78 §78.16:1150 | `LIGHT_INCUBATION`: „Coverage nur fuer **beruehrte** Dateien" |

Beide verfuegbaren Varianten scheitern: Die eine ist per Konstruktion
unvollstaendig, die andere widerspricht dem Profil, das FK-78 ausdruecklich
vorsieht. **Es gibt keinen Weg, einen LIGHT-Lauf gruen zu pruefen.**

### Zweitbefund — Baseline ausserhalb der `concept_roots`

Der Lauf nimmt `CLAUDE.md` in seine Baseline auf, weil dort die PO-Grundregel
steht, um die es inhaltlich geht (§DEFINITION OF DONE). `CLAUDE.md` liegt aber
ausserhalb der konfigurierten `concept_roots`. Auch dafuer existiert kein
Vertrag — weder eine Erlaubnis noch ein Verbot.

## Warum das mehr ist als eine Werkzeugluecke

FK-78 §78.16 fuehrt drei Profile ein, um Verfahren proportional zu halten.
`FULL_ATOM` ist teuer und fuer grosse Migrationen gedacht;
`DIRECT_GOVERNED_CHANGE` verzichtet auf den Lauf ganz. `LIGHT_INCUBATION` ist
der Mittelweg — **und genau der ist nicht abschliessbar.**

Damit hat die Norm faktisch zwei statt drei Profile: Wer einen Lauf braucht,
muss `FULL_ATOM` fahren oder mit einem `INCOMPLETE`-Gate leben. Beides
untergraebt die Proportionalitaet, die §78.16 herstellen soll. Und ein Gate,
das bei korrekter Arbeit `INCOMPLETE` meldet, wird als Rauschen gelesen — dann
faellt es auch dann nicht auf, wenn es etwas Echtes meldet.

Das ist dasselbe Muster, das am 2026-08-05 mehrfach auftrat: **die Zusage ist
geschrieben, ein realer Weg laeuft daran vorbei.**

## Scope

### In Scope

- Ein **pruefbarer Baseline-Vertrag fuer `LIGHT_INCUBATION`**: selektive,
  digest-basierte Baseline ueber genau die beruehrten Dateien, die das Gate
  vollstaendig verifizieren kann. Welche Form das annimmt — dritte
  `base_revision.kind`, explizite Dateiliste mit gepinnten Digests, oder etwas
  Besseres — ist Teil der Umsetzung.
- Ein Vertrag fuer Baseline-Dateien **ausserhalb der `concept_roots`**:
  entweder ausdruecklich erlaubt mit Regel, oder ausdruecklich verboten mit
  Begruendung. Kein stillschweigender Zustand.
- Der Pruefer muss `INCOMPLETE` fuer LIGHT-Laeufe nicht mehr melden koennen,
  wenn der Lauf korrekt ist.

### Out of Scope

- Absenken der Anforderungen an `FULL_ATOM`.
- Der Inhalt des ausloesenden Laufs — der ist Council-Arbeit und unabhaengig
  hiervon.
- Eine Ausnahme-/Unterdrueckungsliste fuer `INCOMPLETE`. Das waere die
  Umgehung: Das Gate soll pruefen koennen, nicht schweigen duerfen.

## Akzeptanzkriterien

1. **Ein korrekter `LIGHT_INCUBATION`-Lauf ist gruen pruefbar.** Nachgewiesen
   am real existierenden Lauf `2026-08-05-review-vertrag-terminierung-085702c0`
   — nicht an einem eigens gebauten Testlauf. Beleg: echte Gate-Ausgabe.
2. **Ein fehlerhafter LIGHT-Lauf wird weiterhin rot.** Negativtest je
   Fehlerart: fehlender Digest, abweichender Digest, Datei nicht in der
   Baseline, Baseline nicht gepinnt.
3. **`INCOMPLETE` bedeutet wieder etwas.** Ein Lauf, bei dem das Gate
   tatsaechlich nicht alles pruefen kann, meldet es weiterhin — mit Grund.
   Nachgewiesen durch einen Fall, der es auch nach der Aenderung ausloest.
4. **Baseline-Dateien ausserhalb der `concept_roots` haben einen Vertrag.**
   Erlaubt oder verboten, mit Regel und Test.
5. **FK-78 und der Pruefer sagen dasselbe.** Wo die Norm angepasst werden muss,
   geschieht das im Konzept, nicht durch stillschweigende Toolabweichung.
6. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FAIL-CLOSED — aber ein Gate, das bei korrekter Arbeit meckert,
  erzieht zum Wegsehen
- `CLAUDE.md` §NO ERROR BYPASSING — keine Unterdrueckungsliste als Loesung
- `CLAUDE.md` §SEVERITY-SEMANTIK — ein Befund, der immer erscheint, wird nicht
  gelesen
