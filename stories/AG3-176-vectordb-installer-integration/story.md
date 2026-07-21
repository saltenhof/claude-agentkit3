# AG3-176 — VektorDB-Installer-Integration (harnessuebergreifend)

- **Typ:** implementation
- **Groesse:** L — von **M** angehoben (Review, Schnitt-/Groessenurteil): nach
  vollstaendiger Ring-/Hook-Integration (CP10b/Pre-Commit, Post-Commit
  `build`→`sync`, CP10a-Receipts, strikte Config-/Preflight-Grenzen) ist die
  Story faktisch L. Der Schnitt bleibt unveraendert; keine Neuaufteilung.
- **depends_on:** [AG3-174, AG3-175] — braucht Engine und Registrierung.
- **unblocks:** []
- **Quell-Konzept:** FK-13 §13.1 (Pflichtinfrastruktur), §13.7
  (Indexierungszeitpunkte, Trigger), §13.8 (Ausfall) · FK-50 (CP10/CP10a,
  Aktivierung) · FK-03 §3.1 (deprecateter Flag) · FK-21 §21.4.3/§21.11.4 ·
  FK-43 (Skill-Bundle-Lifecycle) · Decision Record 2026-07-21 (Rand 1)
- **Herkunft:** PO-Neuschnitt 2026-07-21. Verankerte Feature-Flag-Pflicht,
  Code-Nachzug hier.

## Kontext / Problem

Engine (AG3-174) und Registrierung (AG3-175) liefern Faehigkeit und Eintrag.
Diese Story macht die Faehigkeit im Zielprojekt **real und pflichtig**: Der
Installer prueft den Endpunkt fail-closed, fuehrt die Erstindizierung
tatsaechlich aus (statt Erfolg zu simulieren), verdrahtet die laufenden
Producer, vollzieht die Pflichtaktivierung **schnittkonsistent (gemeinsam
landend)** und liefert den Skill ohne stillen Fallback. „Schnittkonsistent"
meint eine **landbare Schnittkante**, keine transaktionale Laufzeitoperation
(Review 176-P2-1): die Aktivierung wird als letzter, unteilbarer Schritt
vollzogen, wenn Server, Registrierung und Erstindex im selben landbaren Stand
vorliegen — ausdruecklich **abgegrenzt** von der nicht-atomaren
Bounded-Window-Semantik des Shadow-Replace (keine DB-Atomizitaet behauptet).

Die Feature-Flag-Pflicht ist normativ verankert (Decision Record 2026-07-21,
Rand 1: `features.vectordb` deprecateter Migrationsschluessel, `false` in
unterstuetztem Zielprojekt harter Fehler). Diese Story zieht den Code nach.

## Scope

### In Scope

1. **Endpunkt-Preflight fail-closed, ohne Default-Fallback** (Review 176-P0-1;
   Nachsicht-Pruefachse). Der Installationslauf prueft die Erreichbarkeit des
   konfigurierten VektorDB-Endpunkts und scheitert hart mit klarer Ursache
   (FK-13 §13.8, FK-21 §21.4.3). Der Installer **installiert oder startet keine
   Datenbank** — er setzt sie voraus (PO-Vorgabe). Basis ist der bestehende
   `wait_for_weaviate`, in den Pfad gehaengt, nicht dupliziert. **Fuer den
   projektgebundenen Installationspfad sind Projektconfig, explizit validierter
   Endpoint und erwartete Weaviate-Kompatibilitaet zwingend; kein
   localhost-/Default-Fallback** (der heutige Fallback in
   `wait_for_weaviate.py:93-125` wird fuer diesen Pfad ausgeschlossen). Nur der
   ausdruecklich **projektlose Diagnose-CLI-Pfad** darf dokumentierte Defaults
   behalten.
2. **Strikte Config-Grenze der Feature-Flag-Pflicht, fail-closed** (Review
   176-P0-2; Nachsicht-Pruefachse). Der Migrationsvertrag wird **vor jeder
   Aktivierungs-, Registrierungs- oder Preflight-Wirkung** exakt und strikt
   validiert: `features.vectordb` **fehlt = Pflichtinfrastruktur aktiv**,
   `true = akzeptierter Migrationswert`, **nur** echtes Boolean
   `false = benannter harter Fehler`. Strings, Zahlen, Null und doppelte
   `features`-/`vectordb`-/Endpoint-Keys sind `configuration_invalid`. Die
   YAML-Ladegrenze behandelt doppelte Keys (kein Last-wins), Lone Surrogates,
   unzulaessige Tags und extreme Tiefe fail-closed; keine Pydantic-Koerzierung
   in den verschachtelten Modellen (`config/loader.py:87` `yaml.safe_load`,
   `models.py:73-104`/`531-549` werden entsprechend verschaerft). Keine
   Wirkung vor vollstaendiger strikter Configvalidierung.
3. **CP10a-Erstindizierung wirklich ausgefuehrt, mit typisiertem Receipt**
   (Review 176-P1-1). Nach Schema und Registrierung fuehrt CP10a
   `story_sync(full_reindex=true)` **und** `concept_sync(full_reindex=true)`
   gegen den Zielkorpus aus. Fuer **beide** Syncs ein typisiertes Receipt mit
   `project_id`, Tool/owned source types, `discovered/unchanged/upserted/
   deleted/failed`, `empty_corpus`, Start-/Endrevision und Status.
   `empty_corpus=true` ist **Erfolg mit Nullmengen**; Transport-/Parse-/
   Partialfehler ist **Fehler ohne Success/Freshness**. Kein Erfolgs-
   Placeholder.
4. **CP10b und die Hook-Ringe — feuernde Installation** (Review 176-P0-3 /
   174-P0-2). Diese Story besitzt die **tatsaechlich feuernde** Ring-2-/
   Pre-Commit-Installation (die AG3-174-CLI-Operationen werden hier verdrahtet;
   `cp10b_concept_validation_hook()` registriert heute nur einen Intent —
   `cp10.py:429-448` — das ist die zu schliessende Luecke): materialisierter
   projektlokaler Pre-Commit-Dispatch, `concept validate --staged` gegen den
   Candidate-Corpus, **Erhalt der bestehenden Secret-Detection**, Idempotenz
   sowie REGISTER/DRY_RUN/VERIFY. Ring 3 ueber den Post-Commit-Pfad:
   `concept build` **VOR** `concept sync`; CI-/Corpus-Strict-Owner und der
   manuelle CLI-Pfad sind nachzuweisen.
5. **Laufende Producer verdrahtet** (FK-13 §13.7): Story-Closure-Trigger
   (Postflight-Sync, Owner in `backend/closure/`), Post-Commit-Concept-Trigger,
   Freshness-Aktualisierung — als tatsaechlich ausgefuehrte Trigger abgenommen,
   nicht nur beschrieben. Die Producer verdrahten **nur Ports auf die
   AG3-174-Engine** an den bestehenden Closure-/Postflight- und Hook-Ownern —
   **keine zweite, unverdrahtete Implementierung**. Post-Commit-Regel:
   Build-Erfolg → Sync-Erfolg → Freshness-Advance; jeder vorherige Fehler
   laesst die alte Revision stehen. Closure bleibt gemaess FK-13 **nicht
   blockierend**, muss aber den Task zuverlaessig starten und Fehler
   beobachtbar protokollieren (kein Fire-and-Forget, das verlorengeht).
6. **Schnittkonsistente (gemeinsam landende) Pflichtaktivierung** (Decision
   Record Rand 1, FK-50; Review 176-P2-1): `features.vectordb=false` in
   unterstuetztem Zielprojekt wird harter Konfigurationsfehler; der optionale
   Ast `branch_vectordb_enabled` / `SKIPPED`/`vectordb_disabled` entfaellt;
   CP10 laeuft unbedingt. Die Aktivierung wird als **letzter, unteilbarer
   Schritt** vollzogen, wenn Server (174), Registrierung (175) und Erstindex
   (diese Story) im **selben landbaren Stand** vorliegen — es gibt keinen
   Zwischenstand mit Phantomeintrag oder flaechendeckendem Ausfall. Dies ist
   eine **landbare Schnittkante**, **keine transaktionale Laufzeitatomizitaet**
   (abgegrenzt vom Bounded-Window-Shadow-Replace). FK-50-/FK-03-Code-Nachzug
   (die Norm ist bereits verankert).
7. **Skill-Auslieferung ohne stillen Fallback.** Der Grep-Rueckfall fuer
   `concept_search` in `create-userstory-core` entfaellt; der Skill fuehrt
   die Werkzeuge als regulaeren Pfad, konsumiert das konfigurierte
   `concepts_dir` (nicht den Default) und das Freshness-Gate, meldet einen
   Ausfall statt ihn wegzuerklaeren. **Harte Stops** (Review 176-P1-2): fehlender/
   staler Graph, `corpus_revision`-Mismatch, VektorDB-/Toolfehler oder
   abweichendes `concepts_dir` sind Hard Stop — **kein Grep-/Dateiscan-
   Fallback**. Vollstaendiger FK-43-Lifecycle: neues unveraenderliches Bundle
   mit Manifest-Digest, **beide Harness-Bundles/Links auf dieselbe immutable
   Version**, Pinning bestehender Projekte, Verify prueft beide Links,
   Neustarthinweis.

### Out of Scope

- Engine, Server, Tools, Corpus (AG3-174).
- Harness-Registrierung selbst (AG3-175) — hier nur die Reihenfolge-
  Abhaengigkeit fuer die Aktivierung.
- ARE (AG3-173), Postgres-Race (AG3-172).
- E2E-Retrieval-/Install-Abnahme gegen echte Infrastruktur — **nachgelagert
  mit dem PO**, nicht Story-Inhalt.

## Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py` | Preflight, CP10a-Erstindex + Receipts, **CP10b feuernde Pre-Commit-Installation** (heute nur Intent, Zeilen 429-448), Aktivierung |
| `src/agentkit/backend/installer/checkpoint_engine/` | Entfall des optionalen VektorDB-Astes |
| `src/agentkit/backend/installer/.../wait_for_weaviate.py` | Preflight in den Pfad haengen; **Default-Fallback fuer den projektgebundenen Pfad ausschliessen** (Zeilen 93-125) |
| `src/agentkit/.../config/loader.py`, `.../config/models.py` | strikte YAML-Ladegrenze + strikte `Features`/`VectorDbConfig` (Zeilen 87, 73-104, 531-549) |
| `src/agentkit/backend/closure/` | Postflight-/Story-Closure-Trigger — nur Port auf die AG3-174-Engine |
| `src/agentkit/backend/vectordb/` | Producer-Trigger (Post-Commit, Freshness) als Port auf die Engine |
| `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md` | Code-begleitender Nachzug (Norm bereits verankert) |
| `src/agentkit/bundles/skill_bundles/create-userstory-core/<neue Version>/` | Bundle ohne stillen Fallback |
| `tests/unit/installer/`, `tests/integration/installer/`, `tests/contract/` | neu/erweitern — Preflight-Negativmatrix, Config-Grenze, CP10a-Receipts, CP10b, Bundle-Hard-Stops |

## Akzeptanzkriterien

1. Ein Lauf mit aktivierter VektorDB und nicht erreichbarem Endpunkt
   scheitert hart mit klarer Ursache; ein Test beweist, dass kein
   Container-/Compose-Pfad angestossen wird. **Kein localhost-/Default-
   Fallback im projektgebundenen Pfad** (Review 176-P0-1): Negativtests fuer
   fehlenden/malformed VektorDB-Block, ungueltigen Host/Port/gRPC-Port,
   erreichbaren Nicht-Weaviate-Dienst, nicht-ready und inkompatible
   Weaviate-Version — jeweils **benannter harter Fehler vor Registrierung/
   CP10a**. Nur der projektlose Diagnose-CLI-Pfad behaelt dokumentierte
   Defaults.
2. **Strikte Config-Grenze** (Review 176-P0-2): Ein Test belegt den
   Migrationsvertrag — `fehlt`=aktiv, `true`=akzeptiert, echtes Boolean
   `false`=benannter harter Fehler; Strings/Zahlen/Null und doppelte
   `features`-/`vectordb`-/Endpoint-Keys sind `configuration_invalid`; Lone
   Surrogates, unzulaessige YAML-Tags und extreme Tiefe sind fail-closed. Ein
   Test beweist: **keine** Aktivierungs-, Registrierungs- oder Preflight-
   Wirkung vor vollstaendiger strikter Configvalidierung; keine Koerzierung.
3. Ein Installations-Integrationstest mit vorbefuelltem Story- UND
   Concept-Korpus findet unmittelbar nach CP10a beide Quellarten **ohne
   manuellen Sync**. Fuer beide Syncs ist ein **typisiertes Receipt** vorhanden
   (Review 176-P1-1) mit `project_id`, Tool/owned source types,
   `discovered/unchanged/upserted/deleted/failed`, `empty_corpus`, Start-/
   Endrevision, Status; `empty_corpus=true` ist Erfolg mit Nullmengen,
   Transport-/Parse-/Partialfehler ist Fehler ohne Success/Freshness.
   Retry/Idempotenz sind geprueft.
4. **CP10b und Hook-Ringe feuern tatsaechlich** (Review 176-P0-3): Ein Test
   belegt materialisierten projektlokalen Pre-Commit-Dispatch,
   `concept validate --staged` gegen den Candidate-Corpus, **Erhalt der
   Secret-Detection**, Idempotenz und REGISTER/DRY_RUN/VERIFY. Post-Commit
   fuehrt `concept build` **vor** `concept sync` aus: Build-Erfolg →
   Sync-Erfolg → Freshness-Advance; jeder vorherige Fehler laesst die alte
   Revision stehen und setzt **keine** Freshness. CI-/Corpus-Strict-Owner und
   der manuelle CLI-Pfad sind nachgewiesen.
5. Story-Closure- und Post-Commit-Concept-Trigger werden als ausgefuehrte
   Trigger abgenommen (nicht nur konfiguriert); sie verdrahten **nur Ports auf
   die AG3-174-Engine** an den bestehenden Closure-/Postflight-/Hook-Ownern
   (keine zweite Implementierung). Closure startet den Task zuverlaessig und
   protokolliert Fehler beobachtbar.
6. `features.vectordb=false` in unterstuetztem Zielprojekt ist harter Fehler;
   der optionale Ast ist entfernt; CP10 laeuft unbedingt. Ein Negativ-/
   Positiv-Test der **schnittkonsistenten Aktivierung** belegt: kein landbarer
   Stand mit Phantomeintrag oder flaechendeckendem Ausfall (landbare
   Schnittkante, keine transaktionale Atomizitaet).
7. Der stille Grep-Fallback ist entfernt; **Bundle-Contract-Tests** (Review
   176-P1-2) beweisen: konfiguriertes `concepts_dir` statt Default,
   `corpus_revision`-Mismatch/fehlender oder staler Graph/VektorDB-Fehler =
   Hard Stop, **kein Grep-/Dateiscan-Fallback**, beide Harness-Bundles/Links
   referenzieren **dieselbe immutable Version**. FK-43-Lifecycle vollstaendig
   abgenommen (Manifest-Digest, Alt-Projekte gepinnt, Verify prueft beide).
8. Konzept-Gates gruen (FK-50-Nachzug konsistent mit der verankerten Norm).

## Definition of Done

- Alle Akzeptanzkriterien erfuellt; `pytest` gruen, Coverage haelt 85 %;
  `mypy src`, `ruff check src tests` sauber; Konzept-Gates gruen.
- Kein God-File; Produktionscode nur unter `src/agentkit/`.
- Story-Bericht dokumentiert die Aktivierungs-Reihenfolge und die semantisch/
  wertegenaue (nicht byte-genaue) Fremdeintrag-Erhaltung im `.mcp.json`-Merge.

## Konzept-Referenzen

FK-13 §13.1/§13.7/§13.8/§13.9.9 · FK-50 (CP10/CP10a/CP10b) · FK-03 §3.1 ·
FK-21 §21.4.3/§21.11.4 · FK-43 · Decision Record
`2026-07-21-vectordb-edge-sharpening.md`

## Guardrail-Referenzen

FAIL-CLOSED · NO ERROR BYPASSING (Grep-Fallback) · ZERO DEBT · FIX THE
MODEL · ARCH-55
