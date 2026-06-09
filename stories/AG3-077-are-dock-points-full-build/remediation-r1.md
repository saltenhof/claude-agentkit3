# AG3-077 — Remediation R1 (Antwort auf review-r1.md)

**Vorgehen:** Jeder Befund wird in-story aufgeloest (Scope/AC/Kontext praezisiert oder
Anker korrigiert) oder — falls Owner woanders — sauber geroutet. Quellanker wurden
gegen den realen Code (`src/agentkit/`) und gegen FK-40/FK-22 (concept-MCP) auf
file:line verifiziert. Es wurde **kein** Produktionscode, **kein** Test und **keine**
Konzeptdatei angefasst — nur `story.md` (+ `status.yaml`-Titel).

---

## Must-Fix (6) — alle in-story aufgeloest

### MF1 — `AreClient`-Stub-Status auflösen (ERROR, Abschnitt 1)
**Befund:** Story sagt „REST-Adapter … wird nur konsumiert" (Out-of-Scope), aber der
Adapter ist selbst vollstaendig Stub (`are_client.py:50,65,79,103,117` werfen
`NotImplementedError`). Damit koennen die Dock-Points keine echten Ergebnisse liefern.
**Verifikation:** Bestaetigt. Alle fuenf `AreClient`-Methoden Stub; Modul-Docstring
`are_client.py:1-6` sagt „full HTTP implementation is deferred". Keine separate
Owner-Story im `_STORY_INDEX.md` (AG3-077 ist die einzige ARE-Story in Welle 3).
**Resolution:** `AreClient`-HTTP-Body **in den AG3-077-Scope aufgenommen** (In-Scope 3,
AC2). Begruendung fuer In-Scope statt Routing: gleicher BC (`requirements_coverage`,
FK-40 §40.4), kein anderer Owner existiert, und ohne realen Adapter waeren die
Dock-Points nur ueber verdeckte Fallbacks/Attrappen real (Verstoss gegen ZERO DEBT /
NO ERROR BYPASSING). Out-of-Scope-Eintrag „AreClient wird nur konsumiert" **entfernt**.
Titel (`status.yaml`) + FK-Anker (§40.4) entsprechend ergaenzt. Ist-Zustand Abschnitt 1
beschreibt den Adapter-Stub jetzt explizit als zu schliessende Luecke.

### MF2 — `CoverageVerdict`/Gate-Result-Vertrag konkretisieren (ERROR, Abschnitt 2)
**Befund:** Story fordert `reason="are_gate_unavailable"` + `uncovered_requirements`,
aber `CoverageVerdict` (`contract.py:149-161`) erlaubt nur `status`/`verdict`,
`extra="forbid"`.
**Verifikation:** Bestaetigt. FK-40 §40.5.4 verlangt die Liste unbelegter Anforderungen;
`top.py:171-172`-Doc skizziert `reason="are_gate_unavailable"`. Beide Felder fehlen.
**Resolution:** In-Scope 10 + AC8: `CoverageVerdict` erhaelt `uncovered_requirements:
tuple[AreRequirement, ...] = ()` und `reason: str | None = None`; `extra="forbid"`/
`frozen` bleiben; Contract-/Schema-Tests ziehen mit. Layer-1-Konsument bleibt
kompatibel (liest weiter `status`/`verdict`, `are_gate.py:65-80`). enabled-ohne-Client
liefert `CoverageVerdict(status=FAIL, verdict="FAIL", reason="are_gate_unavailable")`.

### MF3 — Falsche Aussage entfernen, dass `are_gate.py` `are_gate.json` liest (ERROR, Abschnitt 3+4)
**Befund:** Story behauptet (alt: `story.md:36,56,76`), der bestehende Layer-1-Konsument
lese `are_gate.json`. Real bekommt `check_are_gate` ein aufgeloestes `CoverageVerdict`.
**Verifikation:** Bestaetigt und tiefer belegt. `are_gate.py:35-41` nimmt
`coverage_verdict: CoverageVerdict | None` (kein Pfad). Dispatcher `checker.py:448-450`
ruft `are.coverage_verdict(...)`; Provider `composition_root.py:2395-2401` delegiert an
`check_gate`. Grep auf `are_gate.json` in `src/agentkit/` -> **kein einziger Treffer**
(Datei wird nirgends gelesen).
**Resolution:** Story korrigiert: `are_gate.json` ist das FK-40-§40.5.4-**Ergebnis-/
Audit-Artefakt**, das `check_gate` zusaetzlich schreibt — **nicht** der Input des
Layer-1-Checks. In-Scope 9 + AC7 + neuer Out-of-Scope-Punkt („Umbau des in-memory
Layer-1-Konsumenten-Pfads") + expliziter Hinweis in Abschnitt 6. Der Provider-Pfad
wird ausdruecklich **nicht** auf Datei-Lesen umgebaut.

### MF4 — `are_bundle`-Phase-State-Modell typisiert definieren (ERROR, Abschnitt 1)
**Befund:** Story verlangt `are_bundle`-Signal im Phase-State, aber `SetupPayload`
erlaubt nur `phase_type`, `extra="forbid"`; `PhaseState.payload` typisiert.
**Verifikation:** Bestaetigt. `SetupPayload` `models.py:74-77` (`extra="forbid"`,
`frozen=True`); `PhasePayload`-Union `models.py:279-284`; `PhaseState.payload`
`models.py:436-440`.
**Resolution:** In-Scope 5 + AC4: neues frozen `AreBundleSignal` (`status:
AreBundleStatus`, `requirement_count: int`) + `AreBundleStatus`-StrEnum
(LOADED/SKIPPED/FAILED); als typisiertes optionales Feld real ins `SetupPayload`
aufgenommen (kein `extra="allow"`, kein Schattenfeld); Persistenz ueber
`HandlerResult.updated_state` -> `PhaseState.payload`.

### MF5 — Scope-/StoryType-Ermittlung für `link_requirements` festlegen (WARNING, Abschnitt 2)
**Befund:** FK-40 §40.5.1 verlangt `are_get_recurring(scope, story_type)`, aber die
Andock-Signatur `(story_id, project_key)` liefert das nicht.
**Verifikation:** Bestaetigt. `top.py:84` Signatur; `StoryContext` traegt aber
`story_type` (`models.py:315`) und `participating_repos`/`project_key`
(`models.py:312,348`).
**Resolution:** In-Scope 2 + AC3: BC-interner `ScopeMapping`-Sub (FK-40 §40.4) leitet
`scope` aus den vorhandenen autoritativen Story-Feldern ab; `story_type` aus dem
`StoryContext`. Oeffentliche Top-Surface-Signatur `(story_id, project_key)` bleibt
unveraendert (FK-40 §40.5 Top-Surface-Vertrag) — Scope/StoryType sind interne
Delegation, kein neuer Aufrufer-Parameter und kein neues Persistenzfeld.

### MF6 — Partial-Evidence-Auslöser für `submit_evidence` modellieren (ERROR, Abschnitt 2)
**Befund:** Story verlangt `kind`-UPDATE `addresses -> partial`, aber `AreEvidence`
(`contract.py:89-105`) hat keinen Partial-Indikator.
**Verifikation:** Bestaetigt.
**Resolution:** In-Scope 8 + AC6: `AreEvidence` erhaelt typisiertes optionales Feld
`coverage: EvidenceCoverage = EvidenceCoverage.FULL` (StrEnum FULL/PARTIAL).
`coverage=PARTIAL` ist der **einzige** explizite Ausloeser fuer die `kind`-UPDATE via
`update_kind`; `FULL` laesst `kind` unveraendert. Keine String-Heuristik. `extra="forbid"`/
`frozen` bleiben.

---

## Weitere WARNINGs

### W1 — Setup-Einhängepunkt zu unpräzise (WARNING, Abschnitt 3)
**Befund:** „vor der Story-Typ-Weiche" ohne konkreten Collaborator/Einfuegestelle.
**Verifikation:** `SetupPhaseHandler.on_enter` baut+persistiert Context
`phase.py:174-178`; Worktree-Weiche folgt `phase.py:188`; green-main-Fehlerpfad
`phase.py:182-186`; Verdrahtung `build_setup_phase_handler`
`composition_root.py:1317-1323`.
**Resolution:** In-Scope 6 + AC10: Einhaengepunkt praezisiert auf „nach
`_build_enriched_context`/Persistenz (`phase.py:174-178`), vor der Story-Typ-Weiche
(`phase.py:188`)", Collaborator ueber `build_setup_phase_handler` injiziert (Handler
baut ihn nicht selbst — Truth-Boundary), Persistenz ueber `HandlerResult.updated_state`,
FAILED-Abbruch analog green-main-Pfad.

### W2 — Stale-`are_item_id` ohne Owner aus Scope geschoben (WARNING, Abschnitt 4)
**Befund:** Story schob Stale-Behandlung (FK-40 §40.5b.5) ohne Owner raus, obwohl
FK-40 sie beim Gate sichtbar machen muss.
**Verifikation:** FK-40 §40.5b.5: „Stale-Eintraege werden beim Andock-Punkt 4
(Gate-Pruefung) sichtbar — `are_client.check_gate` meldet das Item als unbekannt; das
Gate setzt FAIL mit explizitem Stale-Hinweis." Das ist intrinsisch Teil von Dock-Point 4,
der in Scope ist — **kein** separater Mechanismus, kein anderer Owner.
**Resolution:** Stale-Behandlung **in-scope aufgenommen** (In-Scope 9 + AC7) als
trivialer Teil des Gate-Pfads (FAIL mit Stale-Hinweis in `uncovered_requirements`). Der
fruehere „nur wenn trivial / sonst Folgebefund"-Hedge ist entfernt.

### Kontext-Sinnhaftigkeit FAIL (Abschnitt 4, ERROR)
Wurde durch MF2 (CoverageVerdict-Felder) + MF3 (are_gate.json-Korrektur) aufgeloest —
die beiden Wurzeln des „parallele Wahrheiten / unklare Contract-Aenderung"-Befunds.

---

## Genuine cross-story Voraussetzungen / Folgebefunde

Keine **harte** Vorgaenger-Abhaengigkeit zusaetzlich zu den bestehenden
(`depends_on: AG3-012, AG3-030`). Alle Must-Fix-Inhalte liegen im selben BC-Cut. Zwei
**weiche** Punkte sind bewusst geroutet (nicht in AG3-077 erledigt):

1. **FK-22 §22.4b doc-only-Nachzug:** Der FK-22-Pseudocode nutzt `Path.write_text`
   statt des autoritativen `ArtifactManager.persist`-Pfads (FK-71/FK-40 §40.5.2). Das
   ist eine Konzept-Prosa-Schwaeche, **kein** AG3-077-Code-Fix. Routing: doc-only-Welle
   10 (analog AG3-101..104-Muster im `_STORY_INDEX.md`); im AG3-077-Cut nur **melden**,
   nicht korrigieren (Hinweis in Abschnitt 6). Keine Code-Konsequenz fuer AG3-077.
2. **Aufrufer-Verdrahtung von Andock-Punkt 1** (Story-Erstellung/VektorDB): Owner
   **AG3-068** (Welle 2, FK-21). AG3-077 macht nur die Andock-Methode + Scope-Resolver
   real; der Story-Creation-Aufrufpfad bleibt bei AG3-068 (Out-of-Scope-Eintrag).
   AG3-068 ist kein Pflicht-Vorgaenger fuer AG3-077 (die Methode ist eigenstaendig
   testbar), daher **nicht** in `depends_on` aufgenommen.

---

## Geänderte Dateien (nur AG3-077)
- `stories/AG3-077-are-dock-points-full-build/story.md` — vollstaendig ueberarbeitet
  (Anker auf file:line korrigiert, AreClient in Scope, CoverageVerdict-/AreEvidence-/
  SetupPayload-Contract-Erweiterungen spezifiziert, are_gate.json-Falschaussage
  korrigiert, Scope-Resolver + Stale-Handling + Setup-Einhaengepunkt praezisiert).
  AG3-057-Template-Struktur (Abschnitte 1-6) beibehalten.
- `stories/AG3-077-are-dock-points-full-build/status.yaml` — Titel an den korrigierten
  Scope angeglichen (AreClient-HTTP, FK-40 §40.4). `status`/`phase`/`depends_on`
  unveraendert (waren korrekt).
- `stories/AG3-077-are-dock-points-full-build/remediation-r1.md` — diese Datei.

**Kein** Produktionscode, **kein** Test, **keine** Konzeptdatei, **keine** Fremd-Story
angefasst.
