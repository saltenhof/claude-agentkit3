# AG3-177 — Sichtbarkeit veralteter Chunks nach einer Claim-Uebernahme

- **Typ:** implementation
- **Groesse:** M — die Groesse haengt an der in Phase 1 ratifizierten
  Loesungsform: Variante (b) ist der Hauptaufwand, Variante (c) waere S.
- **depends_on:** [AG3-174] — die Generationsleiter, der geordnete Delete und die
  Abschlussordnung stammen von dort und werden hier **nicht** neu aufgerollt.
- **unblocks:** []
- **Quell-Konzept:** FK-13 §13.9.9 (Sync-Lebenszyklus, dort als offener Rest
  verankert) · §13.3.1 (`owning_generation`) · §13.9.5 (Abfrageoberflaeche)
- **Herkunft:** Herausgeschnitten aus der Abnahme von AG3-174 (PO-Mandat
  2026-07-25 „eine Runde weiter, dann Schnitt"). Reviewbefunde N41/N46 in
  `../AG3-174-vectordb-retrieval-engine/review-7-codex.md` und
  `review-9-codex.md`; PO-Entscheidung D9 samt drei Nachtraegen in
  `../AG3-174-vectordb-retrieval-engine/po-decisions.md`. Der Schnitt ist von
  Codex bestaetigt (r10: Abgrenzung korrekt, Kriterien ausreichend).

## Kontext / Problem

Pro Quelldatei darf nur **ein** Sync arbeiten; ein zweiter wird fail-closed
abgewiesen (D3). Haengt oder stirbt ein Sync, uebernimmt ein Administrator
**ausdruecklich** — es gibt bewusst keinen Zeitablauf (D9, CLAUDE.md §6.7).

Erwacht der ueberholte Prozess **nach** der Uebernahme, schreibt er seine
inzwischen veralteten Chunks. Bei geaendertem Inhalt tragen sie andere UUIDs und
liegen deshalb **neben** den aktuellen.

**Was bereits sichergestellt und abgenommen ist** (AG3-174, nicht Gegenstand
dieser Story):
- Ein ueberholter Halter kann die Daten des neueren Besitzers **nicht loeschen** —
  storage-seitig erzwungen ueber die Generationsordnung.
- Er kann die gemeldete Freshness **nicht zurueckdrehen** und den
  Abschlussvermerk **nicht verdraengen**.
- Ein Post-Completion-Sweep raeumt den **haeufigen** Fall unmittelbar auf.
- Vorbestehende ungestempelte Zeilen konvergieren.

**Was offen bleibt — der Gegenstand dieser Story.** Ein Schreibvorgang, der
**nach** dem Abschluss-Delete eintrifft (oder waehrend des paginierten Lesens an
einer bereits gelesenen Seite vorbei), bleibt bis zum **naechsten Sync dieser
Quelle** in der Suche sichtbar. Dieser Zeitpunkt ist **nicht zeitlich
begrenzt**: er kann Stunden spaeter liegen oder nie eintreten.

Ein endlicher Aufraeumschritt kann einen Schreibvorgang nicht abfangen, der
danach eintrifft — das ist strukturell, nicht eine Frage von Sorgfalt.

**Auswirkung.** Kein Datenverlust, keine falsche Freshness-Richtung. Aber die
Suche kann **zwei widersprechende Fassungen** desselben Abschnitts liefern, und
`story_list_sources` zaehlt die Ueberzaehligen mit, waehrend `corpus_revision` den
neueren Stand meldet. Es ist ein **Melde- und Sichtbarkeitsproblem**, kein
Integritaetsproblem — aber es trifft den Kernnutzen der Faehigkeit: ein Agent
koennte veralteten Normtext als gueltig lesen.

**Eintrittsbedingung** (eng, aber real): haengender Sync **und** bewusster
Admin-Reclaim **und** wiederauferstandener Altprozess **und** kein
nachfolgender Sync.

## Scope

### Phase 1 — Entwurfsentscheidung (vor jeder Codeaenderung)

Der Aufloesungsraum ist auf drei Formen begrenzt und **vollstaendig vorbewertet**;
diese Bewertung ist zu pruefen, nicht neu zu erfinden:

| Form | Vorbefund | zu leisten |
|---|---|---|
| (a) Stale-Write storage-seitig verhindern | **Nicht verfuegbar.** Ueber drei Mechanismus-Versuche verifiziert: der gepinnte `weaviate-client` bietet keine Vorbedingung fuer `insert`/`update`/`replace`; nur `delete_many(where=…)` ist konditional. Eine Emulation ueber generationsgescopte UUIDs zerstoert die deterministische Chunk-Identitaet, auf der idempotenter Re-Sync, Delete-Closure und Identitaetspruefung beruhen. | Nur belegen, falls verworfen bleibt — **oder** ein anderes Speicherprimitiv begruenden |
| (b) Retrieval schliesst nicht-autoritative Generationen aus | **Der einzige Weg, der den Rest wirklich schliesst.** Zwei kohaerente Diskriminatoren: `corpus_revision` **oder** ein interner quellenweiser `(source_file, owning_generation)`-Autoritaetsfilter. Beide koppeln die Abfrage an die Completion-Menge und tragen denselben quellenweisen Lookup samt wachsender Filterbreite. Ausgeschlossen bleibt die Sichtbarkeit der Generation auf der **Abfrageoberflaeche** (§13.9.5). | Diskriminator waehlen, Kosten auf dem heissen Suchpfad quantifizieren |
| (c) Rest als Vertrag ratifizieren | Ehrliches Dokumentieren statt Beheben. Der PO uebernimmt bewusst, dass die Suche im engen Fall veraltete Treffer zeigen kann. | Vertragstext, Betriebshinweis, Beobachtbarkeit |

**Ergebnis von Phase 1:** ein Entwurfsdokument mit Empfehlung **und** eine
PO-Ratifizierung. Erst danach Code. Diese Reihenfolge ist verbindlich: bei
AG3-174 sind drei Mechanismen gescheitert, weil sie ohne ratifizierte
Entscheidung gebaut wurden.

### Phase 2 — Umsetzung der ratifizierten Form (In Scope)

1. Umsetzung genau der ratifizierten Variante, ohne stille Erweiterung.
2. **FK-13 §13.9.9 wahr halten:** der dort verankerte offene Rest wird durch das
   Ergebnis ersetzt bzw. praezisiert. Keine Grenze behaupten, die nicht gehalten
   wird; keine Atomizitaet. Begleitender Decision Record (P3-Pflicht).
3. Beobachtbarkeit: ein veralteter Rest muss **erkennbar** sein, nicht nur
   theoretisch beschrieben — bei (c) ist das der Kern der Lieferung.
4. Tests am realen Produktionspfad, revert-verifiziert, und **beide**
   Race-Reihenfolgen dort, wo sie erreichbar sind.

### Out of Scope

- **Die Generationsleiter, der geordnete Delete, die Abschlussordnung und die
  Legacy-Konvergenz** — alle in AG3-174 abgenommen und ausdruecklich **nicht**
  neu aufzurollen.
- Der Post-Completion-Sweep als Mechanismus (bleibt; er deckt den haeufigen Fall).
- D3s Erstschreiber-Abweisung und das Verbot automatischen Ablaufs (D9,
  CLAUDE.md §6.7) — unveraendert gueltig.
- Prozessaufsicht ausserhalb der VektorDB-Schicht (ein ueberholter Schreiber kann
  ein anderer Betriebssystemprozess sein; diese Ebene besitzt die Aufsicht nicht).
- AG3-175 (Registrierung), AG3-176 (Installer), AG3-173 (ARE).

## Betroffene Dateien

Abhaengig von der ratifizierten Form; erwartbar:

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/vectordb/engine.py` | Retrieval-Port bzw. Autoritaets-Lookup (b) |
| `src/agentkit/integration_clients/vectordb/weaviate_adapter.py` | Filterbildung (b) |
| `src/agentkit/backend/vectordb/mcp_server.py` | Envelope/Zaehler, falls Sichtbarkeit sich aendert |
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` | §13.9.9 auf das Ergebnis bringen |
| `concept/_meta/decisions/<datum>-<name>.md` | Decision Record (P3) |
| `tests/unit/vectordb/`, `tests/integration/vectordb/` | Race- und Sichtbarkeitstests |

## Akzeptanzkriterien

1. **Phase-1-Entwurf liegt vor und ist PO-ratifiziert**, mit Bewertung aller
   drei Formen, Empfehlung und — fuer (b) — quantifizierten Kosten auf dem
   Suchpfad. Kein Code vor der Ratifizierung.
2. Die ratifizierte Form ist umgesetzt, **ohne** stille Erweiterung ueber sie
   hinaus.
3. **Bei (a)/(b):** Ein Test am realen Produktionspfad beweist, dass ein nach dem
   Abschluss-Delete eingetroffener Stale-Write **nicht** als Suchtreffer
   erscheint und in den Quellzaehlern nicht mitgezaehlt wird — revert-verifiziert.
   **Bei (c):** Ein Test beweist, dass der Rest **erkennbar** gemeldet wird
   (Beobachtbarkeit), und der Vertragstext benennt ihn ohne Beschoenigung.
4. Die Zusicherungen aus AG3-174 sind **unveraendert** wirksam: kein Loeschen der
   Daten einer neueren Generation, keine Umkehrung der gemeldeten Freshness,
   Receipt-last, Legacy-Konvergenz — je durch die bestehenden Tests belegt
   (keine Regression).
5. FK-13 §13.9.9 beschreibt den **tatsaechlichen** Zustand nach dieser Story:
   keine unhaltbare Grenze, keine Atomizitaetsbehauptung; Decision Record
   vorhanden; Konzept-Gates gruen.
6. Beide erreichbaren Race-Reihenfolgen sind getestet; wo eine Reihenfolge
   strukturell unmoeglich ist, wird das **begruendet** statt durch einen
   Scheintest symmetrisch dargestellt.

## Definition of Done

- Alle Akzeptanzkriterien erfuellt; voller `pytest` gruen, Coverage haelt 85 %
  (explizit gemessen — `addopts` enthaelt kein `--cov`); `mypy src`,
  `ruff check src tests` sauber; Konzept-Gates gruen.
- Produktionscode nur unter `src/agentkit/`; `integration_clients/` bleibt
  duenner Adapter.
- Story-Bericht dokumentiert die ratifizierte Form, die verworfenen Alternativen
  **mit Begruendung**, und — falls ein Rest bleibt — dessen ehrliche Grenzen.

## Konzept-Referenzen

FK-13 §13.9.9 (offener Rest) · §13.3.1 (`owning_generation`) · §13.9.5
(Abfrageoberflaeche, Generation bleibt intern) · §13.9.10 (Default-Filter) ·
Decision Records `2026-07-21-vectordb-edge-sharpening.md` (Bounded-Window-Linie)
und `2026-07-25-claim-takeover-storage-conditional-delete.md` (D9 samt drei
Nachtraegen)

## Guardrail-Referenzen

FAIL-CLOSED · **FIX THE MODEL, NOT THE SYMPTOM** (drei gescheiterte Mechanismen
in AG3-174 sind die Vorgeschichte) · ZERO DEBT · SEVERITY-SEMANTIK (ein
verbleibender Rest wird gemeldet, nicht verschwiegen) · ARCH-55
