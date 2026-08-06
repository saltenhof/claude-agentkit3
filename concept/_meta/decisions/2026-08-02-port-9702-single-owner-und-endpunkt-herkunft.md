---
concept_id: META-DEC-2026-08-02-PORT-9702-SINGLE-OWNER-UND-ENDPUNKT-HERKUNFT
title: Concept-Decision-Record — Portregistrierung hat einen Owner; Endpunkt-Zwang prueft Herkunft, nicht Wortlaut
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, ports, installer, control-plane, vectordb, FK-10, FK-13, FK-15]
formal_scope: prose-only
---

# Concept-Decision-Record — Portregistrierung hat einen Owner; Endpunkt-Zwang prueft Herkunft, nicht Wortlaut

Datum: 2026-08-02. Anlass: PO-Auftrag „Port 9080 ist aus diesem Projekt zu
verbannen" nach dem Befund, dass **jede frische Installation eine
`control-plane.json` schrieb, die auf einen Port zeigte, auf dem nichts
lauscht**.

## 1. Anlass

`<absolute-agentkit-wrapper> serve` kennt seit FK-10 §10.7.2 zwei Profile: `--ui-bff` (9701) und
`--project-api` (9702). Der Installer schrieb bis heute
`https://127.0.0.1:9080`. Der Wert stand als **handgeschriebenes Literal** im
Default eines `InstallConfig`-Feldes; ein zweites Literal `port: int = 9080`
stand im Listener selbst; ein drittes im Vite-Proxy des Frontends.

Am Leben gehalten wurde `9080` von einer Kompatibilitaetsschicht: dem
Deprecated-Alias `serve-control-plane`, dessen einzige verbleibende Aufgabe die
Beschreibung einer Portmigration `9080 → 9702` war. Die Migration erreichte die
uebrigen Kopien nie. Die Schicht hat nichts geschuetzt — sie hat genau den
Fehler erzeugt, gegen den sie angeblich half. Sie ist der belegte Anlassfall der
seit heute geltenden PO-Grundregel „KEINE KOMPATIBILITAETSSCHICHTEN".

Ein zweiter Defekt derselben Familie lag in der VectorDB-Endpunktsperre: eine
Zeichenketten-Sperrliste sollte „synthetisierte Localhost-Defaults" (PO-Beschluss
D2) verhindern und wies dafuer vier Literale hart ab, darunter
`localhost:50051`. Genau das ist der reale gRPC-Endpunkt einer lokalen
Weaviate-Instanz — also der **Normalfall** der AK3-Topologie (FK-15
localhost-only). Der Zwang hat den erlaubten Fall blockiert und den verbotenen
nie erkannt.

## 2. Entscheidung

**2.1 Die Portregistrierung hat genau einen Owner.** `CORE_UI_PORT`,
`CORE_UI_BFF_PORT` und `CORE_PROJECT_API_PORT` liegen ausschliesslich in
`backend/config/defaults.py` und projizieren FK-10 §10.7.2. Jeder Konsument —
die Profil-Defaults in `cli.serve`, die vom Installer geschriebene
`control-plane.json`, der SPA-Dev-Proxy — leitet daraus ab. Eine zweite Kopie
eines AK3-Portliterals ist ein Defekt, unabhaengig davon, ob der Wert gerade
stimmt.

**2.2 Der Listener besitzt keinen Port-Default.** `serve_control_plane` nimmt
`port` als Pflichtparameter. Ein Default dort waere eine zweite Aussage
darueber, wo AK3 lauscht — und war es faktisch: er trug `9080` weiter, lange
nachdem jeder andere Konsument gewechselt hatte. Wer den Listener startet, nennt
den Port; das Profil liefert ihn.

**2.3 Der Core-Endpunkt des Zielprojekts ist konfigurierbar, nicht
handgeschrieben.** `register-project` / `verify-project` / `install` nehmen
`--control-plane-base-url` und `--control-plane-ca-file`. Der Default ist aus
2.1 **abgeleitet** (`https://127.0.0.1:{CORE_PROJECT_API_PORT}`) und stuetzt sich
auf die normative Loopback-Topologie (FK-15). Damit ist er keine plausible
Vermutung, sondern eine Projektion der Portregistrierung — und kann nicht mehr
gegen sie driften. Ein Operator mit abweichendem Core sagt das an der CLI,
statt die erzeugte Datei nachtraeglich zu editieren.

**2.4 Die SPA spricht mit der UI-BFF, nie mit der Project-API.** Der
Vite-Dev-Proxy zeigt auf 9701. Die Project-API (9702) bedient
Maschinen-Principals (Hooks/Edge/CLI); das ist FK-15 §15 Principal-Trennung, kein
Konfigurationsdetail.

**2.5 „Nicht synthetisiert" wird an der Herkunft durchgesetzt, nicht am
Wortlaut.** Die Endpunkt-Sperrlisten in `vectordb.runtime_binding` und
`vectordb.project_binding` entfallen ersatzlos. D2 bleibt unveraendert gueltig
und wird strukturell garantiert: die Weaviate-Endpunkte sind
Pflicht-Konfigurationswerte ohne Default, die CLI-Flags tragen keinen Default,
und ein fehlender oder leerer Wert faellt fail-closed. Eine Zeichenkette kann
nicht unterscheiden, ob ein Endpunkt bewusst gesetzt oder versehentlich
daraufgefallen ist; ein Herkunftsnachweis kann es.

## 3. Was entfernt wurde

Der Anlassfall war `serve-control-plane`. Der PO hat den Auftrag am selben Tag
auf **jedes** Deprecated-/Compat-Konstrukt erweitert, weil es dafuer nie eine
Anforderung gab. Entfernt wurde ersatzlos, jeweils mitsamt allen Aufrufstellen
im selben Zug:

**Port 9080 / Endpunkte**

- Der Port-Default `9080` im Listener (`serve_control_plane`); `port` ist jetzt
  Pflichtparameter.
- Das Endpunkt-Literal `https://127.0.0.1:9080` im Installer.
- Das Proxy-Ziel `9080` im Vite-Dev-Server (jetzt UI-BFF 9701).
- Die vier Sperrlisten-Literale in `vectordb.runtime_binding` und die zwei in
  `vectordb.project_binding`.

**CLI-Verben** (Subparser, Handler, Dispatch, Tests, Doku)

- `serve-control-plane` -> `serve --project-api`
- `install` -> `register-project`
- `uninstall` -> `detach`

**Module und Fassaden**

- `installer/bootstrap_checkpoints/cp10.py` (Compat-Alias-Modul mit
  `sys.modules`-Tausch); Konsumenten importieren aus den Owner-Modulen.
- `backend/phase_state_store/store.py` (reine Re-Export-Fassade).
- `backend/governance/hookruntime.py` (deprecated Hook-Entry-Point).
- `installer.uninstall_agentkit` / `UninstallResult` (Fassade ueber
  `detach_project`).

**Aliase im Code**

- `GuardResult.PASS` / `.FAIL` samt zwei `# NOSONAR`. Kanonisch ist die
  snake_case-Schreibweise `pass_` / `fail` (CLAUDE.md Namensregel); alle
  Aufrufstellen sind mitgezogen, die Unterdrueckung entfaellt damit ersatzlos.
- Fuenf `read_*_record`-Wrapper in `state_backend` (`artifact_catalog_store`,
  `pipeline_runtime_store` x2, `story_lifecycle_store`, `verify_artifact_store`)
  auf ihre `load_*`-Originale.
- `state_backend.config._sqlite_allowed` auf `config.sqlite_gate.sqlite_allowed`.
- `project_management.read_models._SUBSTEP_SEQUENCE_*` — Produktionscode trug
  private Namen, damit Tests sie importieren konnten; korrigiert wurde der Test.
- Die Phase-Modell-Bruecke in `story_context_manager.__getattr__`
  (`PhaseSnapshot`/`PhaseState`/`PhaseStatus`); Owner ist
  `pipeline_engine.phase_executor`.
- `VerifySystem.layer_2`, `.adversarial_challenger`, `.policy_decision()`,
  `.adversarial_layer()` — vier Zweitnamen fuer `layer_3` bzw. den Policy-Engine-
  Aufruf, nur von Tests benutzt.
- Der Producer `verify-system.layer-2-llm` (Registry-Eintrag, den
  `write_layer_artifacts` nie erzeugen konnte).
- Das tote Injektionsseam `CiSonarScanRunner.tree_resolver` samt Protokoll
  `TreeHashResolver` — Produktion las es nie.
- Die Plugin-Key-Zweitschreibweise `communityBranchSupport`; SonarQube meldet
  ausschliesslich `communityBranchPlugin`.
- Die Alias-Re-Exports im Frontend-Prototype-Store (`project`,
  `conceptAnchors`, `projects`).

**Doppeltes Lesen (altes UND neues Format)**

- `concept_paths` als Eingabe-Alias fuer `concept_refs` in `StoryContext`.
- Derselbe Doppel-Read in `verify_system.llm_evaluator.context_sufficiency`.

## 4. Konsequenzen

- `<absolute-agentkit-wrapper> serve-control-plane` existiert nicht mehr. Der eine Level-1-Verb ist
  `<absolute-agentkit-wrapper> serve --ui-bff|--project-api` (FK-10 §10.2.5).
- Eine legitime lokale Weaviate-Instanz (`http://localhost:9903`,
  `localhost:50051`) wird akzeptiert. Der Installer wurde damit real
  durchlaufen; CP 10 erreichte die MCP-Registrierung, statt vorher an der
  Wortlaut-Sperre zu scheitern.
- Bestehende Tests, die die Sperrliste absicherten, pruefen jetzt die richtige
  Invariante: fehlender/leerer Endpunkt faellt fail-closed, ein **explizit
  registrierter** Loopback-Endpunkt wird uebernommen.

## 5. Bewusst NICHT entfernt — und warum

**Die Flow/Node/Edge-Vokabular-Aliase in `process/language/model.py`**
(`PhaseDefinition`, `TransitionRule`, `WorkflowDefinition`, `.name`, `.phases`,
`.transitions`, `get_phase()`, `get_transitions_from()`, `phase_names`).

Sie sind unstrittig Compat-Konstrukte. Ihre Entfernung ist aber **keine
Alias-Loeschung, sondern eine Vokabular-Migration** ueber rund 330 Aufrufstellen
in etwa 30 Modulen — und sie ist nicht mechanisch durchfuehrbar:

- `.name` auf `FlowDefinition` kollidiert mit `NodeDefinition.name`, das der
  kanonische Name ist und bleiben muss. Ein Sweep wuerde beide treffen.
- `.phases` / `get_phase(` existieren gleichlautend auf fachlich anderen
  Objekten (`story_context_manager`, `project_management`), die von dieser
  Umbenennung nicht betroffen sind.

Damit ist jede Fundstelle eine Einzelfallentscheidung. Das gehoert in eine
eigene, geschnittene Story mit eigener Verifikation — nicht als Beifang in eine
Portkorrektur. **Gemeldet, nicht stillschweigend stehen gelassen**; die Regel
verlangt bei unverhaeltnismaessigem Umbau ausdruecklich Stoppen und Melden.

## 6. Grenzen

Dieser Record aendert nichts an D2 selbst. Er aendert die Stelle, an der D2
durchgesetzt wird — von der Zeichenkette an die Konfigurationsherkunft. Wenn ein
kuenftiger Codepfad einen Endpunkt doch synthetisiert, ist **dieser Pfad** der
Defekt; eine Sperrliste im Binding waere wieder die falsche Antwort darauf.
