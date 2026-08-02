# AG3-200 — Blueprint-Quelle dauerhaft sichern und digest-pinnen

- **Typ:** concept
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-185, AG3-186
- **Quell-Konzept:** FK-78 §78.13 (Datenklassen, Artefakt-Register,
  Declassification), FK-78 §78.3 (Inkubator-Layout)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-16 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

## Kontext

### Befund — belegt, mit Locator

`concept-incubator/konzeptpruefung-verfahren/workspace/README.md:21-26` haelt
die Quellenlage selbst fest:

> „Der Blueprint lag urspruenglich unter `P:\_private-img2img\concept\_meta`.
> Das Laufwerk wurde waehrend dieses Laufs migriert; ab der Meldung wurde
> ausschliesslich aus der Sicherung im Scratchpad (`intima-blueprint/`, Kopie
> vom 2026-08-02) gelesen. **Die gesicherte Kopie ist selbst fluechtig** — wer
> die Befunde spaeter nachpruefen will, braucht eine dauerhafte Kopie oder den
> Originalort."

Dasselbe steht im Frontmatter von `C-befundbericht.md` (`quelle_blueprint`).

**Zwei Storys verlangen die Auswertung dieses Blueprints:** AG3-185
(Verfahrensmigration, gestuetzt auf C-1 bis C-12) und AG3-186
(Komponenten-/Schnittstellenschicht, gestuetzt auf C-4 mit den Festlegungen
`KW-L0`–`KW-L3`, `KW-C2`, `KW-C4`, `KW-H1` und §4.6). Beide zitieren Aussagen,
deren Quelle heute nicht auffindbar ist. Damit ist **jede** dieser Aussagen
unbelegt im Sinne der Provider-Claim-Kante aus C-7: „Dokument X liefert Y" ohne
nachpruefbares Y.

### Die Nebenfrage, die nicht uebersehen werden darf

Der Blueprint stammt aus einem **fremden, privaten Projekt**. C-10 haelt fest,
dass dessen Werkstatt aus Datenschutzgruenden grundsaetzlich ungetrackt bleibt
(„intime Quellen"). Eine Kopie in das versionierte AK3-Repo zu legen ist damit
**nicht** automatisch zulaessig: FK-78 §78.13 verlangt eine Datenklasse je
Artefakt (`open|internal|sensitive`, unklassifiziert zaehlt fail-closed als
`sensitive`), `effective_class` als Maximum ueber den Provenienzgraphen und ein
Commit-Gate, das Verstoesse blockiert.

Diese Story loest deshalb **nicht** „Datei kopieren", sondern „Belegbarkeit
herstellen, ohne die Datenklassenregel zu verletzen".

## Scope

### In Scope

- Klassifikation des Blueprint-Bestands nach FK-78 §78.13.
- Herstellung einer **dauerhaften, digest-gepinnten** Belegbasis mit Herkunft
  und Stand — in der Form, die die Datenklasse zulaesst.
- Alternativ, falls die Datenklasse eine Ablage verbietet: die vollstaendige
  Ueberfuehrung der uebernommenen Aussagen in eigene, belastbar lokalisierte
  Formulierungen.

### Out of Scope

- Die inhaltliche Auswertung des Blueprints — **AG3-185** und **AG3-186**.
- Die Uebernahme des Blueprint-`.gitignore`-Musters. C-10 haelt fest, dass AK3s
  Datenklassenregel die feinere Loesung ist; der Themenraum wird uebernommen,
  das Ignore-Muster nicht.
- Keine PO-Entscheidung ueber die Freigabe fremder Daten — steht sie an, wird
  sie vorgelegt, nicht getroffen.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept-incubator/konzeptpruefung-verfahren/` | geaendert | Belegbasis mit Digest, Herkunft, Stand |
| `concept-incubator/konzeptpruefung-verfahren/workspace/README.md` | geaendert | Quellenlage aufgeloest statt als Warnung stehengelassen |
| `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md` | geaendert | `quelle_blueprint` zeigt auf die dauerhafte Basis |
| Artefakt-Register / `vcs_disposition` (FK-78 §78.13) | geaendert | Datenklasse und Provenienz eingetragen |
| `concept/_meta/decisions/2026-XX-XX-blueprint-belegbasis.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Der Blueprint-Bestand ist nach FK-78 §78.13 klassifiziert.** Jedes
   uebernommene Artefakt traegt eine Datenklasse; unklassifiziert zaehlt
   fail-closed als `sensitive`. Die `effective_class` ueber den
   Provenienzgraphen ist bestimmt, und die `vcs_disposition` folgt daraus.
2. **Es gibt eine dauerhafte Belegbasis mit Digest, Herkunft und Stand** —
   erreichbar fuer jeden, der AG3-185 oder AG3-186 spaeter nachpruefen will.
   Ein Pfad im Scratchpad oder auf einem privaten Laufwerk erfuellt das nicht.
3. **Wenn die Datenklasse eine Ablage im Repo verbietet, greift die
   Alternative vollstaendig:** jede in den Werkstattdokumenten uebernommene
   Aussage ist so umformuliert, dass sie **aus AK3-eigenen Quellen** belegt
   oder als eigene Setzung ausgewiesen ist. Es bleibt **keine** Aussage stehen,
   die auf ein nicht erreichbares Dokument verweist. Nachgewiesen durch eine
   Durchsicht von `A`, `B`, `C` und `D` mit namentlicher Liste jeder
   Blueprint-Referenz und ihrem neuen Status.
4. **Der Digest ist gepruefbar.** Wer die Belegbasis benutzt, kann feststellen,
   ob sie sich seit der Auswertung geaendert hat. Ein Verweis ohne Digest
   erfuellt das nicht.
5. **Die Warnung in `workspace/README.md:21-26` ist aufgeloest**, nicht
   umformuliert. Ein Satz, der weiterhin sagt „wer das spaeter nachpruefen will,
   braucht eine dauerhafte Kopie", ist keine Erledigung.
6. **Steht eine PO-Freigabe an** (fremde Daten, `sensitive` verlaesst die
   Maschine nicht ohne Freigabe je Backend, FK-78 §78.13), ist sie
   entscheidungsreif vorgelegt und nicht selbst getroffen.
7. **Alle deterministischen Konzept-Gates gruen**, inklusive des
   Datenklassen-Commit-Gates; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg.
- Die Liste aus AC 3 liegt vollstaendig im Story-Record.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/78_concept_incubation_process.md` §78.13
  (Datenklassen, Artefakt-Register, Declassification), §78.3 (Inkubator-Layout)
- `concept-incubator/konzeptpruefung-verfahren/workspace/README.md:21-26`
  (Quellenlage)
- `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-10 (Werkstatt-Tracking, Datenschutzbegruendung des Blueprints)

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — unklassifiziert zaehlt als `sensitive`.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 5: eine stehengelassene Warnung ist keine
  Erledigung.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — die Belegbasis existiert
  genau einmal.
