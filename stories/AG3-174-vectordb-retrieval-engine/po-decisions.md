# PO-Entscheidungen — VektorDB-Story-Kette (AG3-174 / AG3-175 / AG3-176)

- **Datum:** 2026-07-23
- **Entscheider:** PO (Stefan Altenhof)
- **Gilt fuer:** AG3-174, AG3-175, AG3-176
- **Grundlage:** `batch-review-codex.md`, Abschnitt „Noch delegierte
  Entscheidungen" (sechs Punkte, die vor Uebergabe an einen Umsetzungsagenten
  fest sein muessen). Die Review-Auflage erlaubt ausdruecklich die Fixierung
  „normativ **oder** im PO-gebundenen Briefing"; dies ist das PO-Briefing.
- **Verhaeltnis zum Decision Record 2026-07-21:** Der DR
  `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` regelt die
  Konzeptraender (Feature-Flag→Pflicht, Quelle→Tool, Tokenizer-Lieferweg,
  Codex-MCP-Vertrag, Bounded-Window). Die hier ratifizierten sechs Punkte sind
  die davon **nicht** abgedeckten Umsetzungsdetails; sie widersprechen dem DR
  nicht, sondern praezisieren ihn ausfuehrungsseitig.

Ergebnis: Alle sechs Entscheidungen bestaetigen die bereits in die
ueberarbeiteten `story.md` eingebauten Defaults. Es ist **kein** Umschreiben
von Story-Inhalt noetig (Ausnahme: die eine Praezisierung bei D3, siehe dort).

---

## D1 — Rueckgabe-Shape von `story_list_sources`

**Frage:** FK-13 §13.4.1 nennt nur „Uebersicht ueber Source-Types und
Projekte". Welche Felder gibt das Tool abnahmeverbindlich zurueck?

**Entscheidung:** Minimale, prueffbare Shape (Variante A). Mindestens:
gebundenes `project_id`, `source_type`, Producer/Tool, Source-/Chunk-Zaehler,
letzte erfolgreiche Revision/Freshness. **Keine** fremden Projekte.

**Begruendung:** Minimal, prueffbar, isolationskonform; kein Konzeptkonflikt.

**Stand in Story:** AG3-174 AC 8 — bereits eingebaut, keine Aenderung.

## D2 — Umgang mit fremdem `project_id` an den MCP-Tools

**Frage:** Der Server startet projektlokal per `env`; die Tools akzeptieren
laut FK-13 §13.4.1/§13.9.5 ein optionales `project_id`. Wird ein abweichend
uebergebenes `project_id` abgelehnt oder als Cross-Project-Abfrage ausgefuehrt?

**Entscheidung:** Fail-Closed + Projektisolation (Variante A). `env` ist
alleinige Autoritaet fuer `PROJECT_ID`/Endpunkt; `cwd` ist nur
Containment-Grenze, keine zweite Konfigurationsquelle; kein
localhost-/Default-Fallback. Ausgelassenes `project_id` → gebundene ID;
**abweichendes `project_id` → Ablehnung**, niemals Cross-Project. Gilt auch fuer
`story_list_sources`.

**Begruendung:** FAIL-CLOSED-Guardrail und Projektisolation. Ein
Cross-Project-Pfad ueber einen Tool-Parameter waere ein Datenleck.

**Stand in Story:** AG3-174 Scope 3 + AC 11 — bereits eingebaut, keine
Aenderung.

## D3 — Sync-Receipt (`corpus_revision`), Retry und ueberlappende Writer

**Frage:** Wo/wann wird der Abschlussmarker geschrieben, wie raeumt ein Retry
Reste, und was tun zwei gleichzeitige Syncs derselben Quelle?

**Entscheidung:** Bounded-Window-Vertrag wie vorgeschlagen ratifiziert:
(1) neue Sollgeneration vollstaendig schreiben und Sollmenge validieren;
(2) alte/fremde Chunks derselben Source erst danach loeschen; (3) erst nach
erfolgreichem Delete ein digestgebundenes Sync-Receipt mit `corpus_revision`
publizieren; (4) Crash davor laesst den letzten Abschlussmarker unveraendert,
Retry bereinigt vollstaendige/partielle Reste deterministisch. Kein CAS, kein
Generations-Zeiger (konsistent mit DR 2026-07-21 Rand 5). Kein sofortiger
Single-Generation-Zustand nach Crash garantiert.

**Sub-Fork entschieden:** Parallele Syncs desselben `(project_id,
source_file)` werden **fail-closed abgewiesen** (nicht serialisiert). Einfacher,
deterministisch, kein Lock-Management im ersten Wurf; Serialisierung bleibt eine
spaeter moegliche Erweiterung.

**Begruendung:** Ehrliche, implementierbare Semantik; Abweisen ist die
konservativste FAIL-CLOSED-Variante.

**Stand in Story:** AG3-174 AC 6 — Kontrakt eingebaut. **Kleine Nachziehung
noetig:** AC 6 formuliert derzeit „serialisiert **oder** fail-closed
abgewiesen"; das „oder" ist auf **abgewiesen** zu verengen.

## D4 — Bedeutung eines fehlenden `features.vectordb`-Schluessels

**Frage:** Wenn ein unterstuetztes Zielprojekt den Schluessel nicht enthaelt —
aktiv oder Fehler?

**Entscheidung:** Fehlt = **Pflichtinfrastruktur aktiv** (Variante A). `true` =
akzeptierter Migrationswert; **nur** echtes Boolean `false` = benannter harter
Fehler. Strings, Zahlen, Null und doppelte `features`-/`vectordb`-/Endpoint-Keys
= `configuration_invalid`. Keine Aktivierungs-/Registrierungs-/Preflight-Wirkung
vor vollstaendiger strikter Configvalidierung.

**Begruendung:** Der Ruecwaerts-Kompatibilitaetsfall ist hypothetisch — es gibt
kein AK3-Altprojekt (PO-Feststellung). Das stuetzt A: Da der Schluessel laut DR
2026-07-21 Rand 1 *deprecated* ist, ist sein Normalzustand „abwesend". „Fehlt =
aktiv" ist die einzige kohaerente Wahl; „fehlt = Fehler" wuerde einen
deprecateten Schluessel de-facto zur Pflicht machen. Konsistent mit FK-13 §13.1
(„immer aktiv, keine Feature-Flag-Stufung") und FK-21 §21.4.3.

**Stand in Story:** AG3-176 In-Scope 2 + AC 2 — bereits eingebaut, keine
Aenderung.

## D5 — Exakter Tokenizer-/Library-Pin

**Frage:** Welche exakten Pins werden normativ festgeschrieben?

**Entscheidung:** Gleiche, bereits bewaehrte Bindung wie in der Vergangenheit,
nichts Neues (Variante A):
- Modell/Tokenizer `sentence-transformers/all-MiniLM-L6-v2`
- gepinnte Revision `e4ce9877abf3edfe10b0d82785e83bdcb973e22e`
- Runtime-Bibliothek `tokenizers==0.21.0`
- Asset-Liste `tokenizer.json` samt Vokabular, separate SHA-256-Digest-Datei
- Lizenznachweis Apache-2.0
- Runtime-Pin `weaviate-client>=4.9,<5.0` (statt heute optional `>=4.0`)
Digestpruefung vor Nutzung; fail-closed bei fehlendem/abweichendem Asset; keine
Laufzeit-Netzabholung, kein zeichenbasierter Ersatz.

**Begruendung:** Werte stammen aus dem erprobten alten Schnitt; beim
Story-Kollaps waren sie verlorengegangen. Neu-Evaluieren bringt hier nur Risiko;
Ziel ist bewusstes Einfrieren als Norm.

**Stand in Story:** AG3-174 Scope 1 + AC 1 — bereits eingebaut, keine
Aenderung.

## D6 — Zwei-Dateien-Fehlersemantik der Harness-Registrierung

**Frage:** `.mcp.json` und `.codex/config.toml` haben keine gemeinsame atomare
Transaktion — wie ehrlich wird der Fehlerfall modelliert?

**Entscheidung:** Ehrliche Bounded-Semantik (Variante A): beide Bestandsdateien
vor dem ersten Write strikt lesen/konfliktpruefen/vollstaendig rendern;
Conformance- oder Parse-/Konfliktfehler = **null Writes**; jeder Einzelwrite
atomar; I/O-Fehler nach dem ersten Write → best-effort-Rollback aus
gebundenem Before-Image + benannter `registration_incomplete`-Fehler;
Wiederholungslauf konvergiert idempotent. Das unvermeidbare Crashfenster
zwischen zwei Dateien wird dokumentiert, nicht als Atomizitaet verkauft.

**Begruendung:** Gleiche Ehrlichkeitslinie wie der Shadow-Replace (DR
2026-07-21 Rand 5); keine Scheinsicherung.

**Stand in Story:** AG3-175 Scope 5 + AC 6 — bereits eingebaut, keine Aenderung.

---

## Konsequenzen

- **Kein** Umschreiben von Story-Inhalt noetig — mit **einer** Ausnahme:
  AG3-174 AC 6 verengen (D3: „serialisiert oder abgewiesen" → „abgewiesen").
- Die drei Stories referenzieren dieses Briefing als Fixierung der delegierten
  Entscheidungen.
- Blockade-/Reihenfolge-Kanten bleiben unveraendert: AG3-175 haengt weiter an
  AG3-164/174, AG3-176 an AG3-174/175, und das Landen von AG3-174 bleibt an
  AG3-172 gebunden. Dieses Briefing loest keine Dependency, nur die
  Entscheidungs-Vorbedingung.
