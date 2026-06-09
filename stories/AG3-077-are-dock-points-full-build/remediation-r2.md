# AG3-077 — Remediation R2 (Antwort auf review-r2.md)

**Vorgehen:** Der einzige verbliebene Must-Fix-ERROR aus `review-r2.md` wird in-story
aufgeloest (Scope/AC/Kontext praezisiert, Anker gegen den realen Code auf file:line
verifiziert). Es wurde **kein** Produktionscode, **kein** Test und **keine** Konzeptdatei
angefasst — nur `story.md` (+ `status.yaml`-Titel). AG3-057-Template-Struktur
(Abschnitte 1-6) beibehalten; ARCH-55 englische Bezeichner/Wire-Keys.

---

## Round-2 Status der Round-1-ERRORs

Der Review bestaetigt: alle sechs Round-1-ERRORs sind textuell aufgeloest (AreClient-HTTP
in Scope, `CoverageVerdict.reason`/`uncovered_requirements`, `are_gate.json` korrekt als
Audit-Output, `AreBundleSignal`/`AreBundleStatus` typisiert in `SetupPayload`,
`ScopeMapping`, `EvidenceCoverage.PARTIAL`). Keine Re-Arbeit noetig.

---

## Verbliebener Must-Fix (1) — in-story aufgeloest

### MF-R2 — Productive `AreClient`-Konstruktion + Injektion aus `ProjectConfig.are` (ERROR)

**Befund (review-r2.md):** AG3-077 macht den realen ARE-Pfad weiterhin nicht buildbar,
weil die Laufzeit-Verdrahtung des `AreClient` fehlt. Der Implementation-QA-Pfad laedt
`ProjectConfig`, aber `_resolve_structural_evidence_ports` reicht **unbedingt** `None` in
`build_structural_are_provider` (`implementation/phase.py:576-582`). Das Konfig-Modell
traegt `ProjectConfig.are` + `AreConfig.rest_base_url`/`auth_token` bereits; die Story sagt
aber nur „AreClient-HTTP implementieren + Provider-Pfad unveraendert lassen". Ohne AC zur
Konstruktion/Injektion von `AreClient(rest_base_url, auth_token)` in Setup und
Layer-1/Implementation produziert `features.are: true` weiterhin ein unavailable Gate.

**Verifikation (realer Code):**
- `implementation/phase.py:580-582` reicht tatsaechlich `build_structural_are_provider(None, pipeline)` — der Client-Parameter ist hartcodiert `None`.
- `composition_root.py:2370-2371`: `typed_client = are_client if isinstance(...) else None` -> `RequirementsCoverage(typed_client, pipeline_config)`. Mit `None` greift der enabled-ohne-Client-Pfad.
- `top.py:71`: `is_enabled` reflektiert nur `features.are` -> `True`, obwohl kein Client da ist => Dauerzustand `are_gate_unavailable`.
- `config/models.py:443`: `are: AreConfig | None`; `:59-60`: `rest_base_url: str | None`, `auth_token: str | None`.
- `are_client.py:33`: Konstruktor `AreClient(base_url, auth_token=None)`.
- `config/models.py:445-454`: Validator erzwingt nur die **Praesenz** der `are`-Sektion bei `features.are=true`, **nicht** ein gesetztes `rest_base_url`. -> enabled-ohne-`rest_base_url` passiert die Validierung, kann aber keinen Client bauen (zusaetzlicher fail-closed-Fall, den die Story abdecken muss).

**Owner-Entscheidung (in-story, kein Routing):** Die Konstruktion-aus-Konfig + Injektion
ist Composition-Root-/Adapter-Verdrahtung (R-Code) desselben ARE-BC. Es existiert keine
andere Owner-Story (`_STORY_INDEX.md`: AG3-077 ist die einzige ARE-Welle-3-Story). Ein
Routing waere falsch — kein anderer Cut liefert diese Verdrahtung, und ohne sie ist der
gesamte AG3-077-Real-Pfad (trotz realem HTTP-Body + realen Andock-Punkten) funktionslos.
Daher **in-scope**. Die FK-03-Config-Validierung bleibt dagegen bewusst out-of-scope (kein
Validator-Umbau); der fehlende `rest_base_url` wird nur an der Konstruktionsstelle
fail-closed behandelt — saubere Cut-Grenze, keine Ausweitung.

**Resolution (story.md):**
- **Ist-Zustand (Abschnitt 1):** neuer Bullet, der die Kern-Luecke explizit belegt
  (`phase.py:580-582` `None`; `composition_root.py:2370-2371`; `top.py:71`;
  `config/models.py:443`/`:59-60`/`:445-454`; `are_client.py:33`).
- **In-Scope 13 (neu):** produktive `AreClient`-Konstruktion aus `ProjectConfig.are` an
  **einer** Stelle + Injektion in **beide** Real-Pfade (Layer-1-Resolver
  `phase.py:580-582` und Setup-`load_are_bundle`-Collaborator ueber
  `build_setup_phase_handler`). `features.are: false` -> Client `None`, Provider SKIPPED.
  `features.are: true` ohne `rest_base_url` -> fail-closed (`are_gate_unavailable` /
  Bundle FAILED), kein stilles Disable, kein Leer-Fallback, kein Validator-Umbau.
  Negativpfad-Liste (jetzt In-Scope 14) um die beiden neuen Faelle ergaenzt.
- **AC3 (neu, AC 3-12 nachnummeriert):** belegt Konstruktion+Injektion in beide Pfade
  (Test: Provider traegt nicht-`None`-Client), beide fail-closed-Faelle (fehlendes
  `rest_base_url` in Layer-1 **und** Setup), SKIPPED bei `features.are: false`.
- **DoD:** „AK 1-11" -> „AK 1-12".
- **Guardrails:** FAIL-CLOSED um den nicht-konstruierbaren-Client-Fall ergaenzt;
  SINGLE SOURCE OF TRUTH um „eine Konfig-Wahrheit / eine Konstruktionsstelle" ergaenzt.
- **Quell-Konzepte:** `FK-40 §40.2` (Aktivierung via `features.are`+`are.rest_base_url`)
  ergaenzt; `FK-40 §40.4` um die Composition-Root-/Adapter-Verdrahtung praezisiert.
- **Abschnitt 6:** kritische Anker um `phase.py:576-585`,
  `composition_root.py:2339-2372`, `config/models.py:443`/`:45-60`/`:445-454`,
  `are_client.py:33` erweitert; neuer Hinweis „Konstruktion ist R-Code, Validator nicht
  umbauen, fehlenden `rest_base_url` nur an der Konstruktionsstelle fail-closed".
- **Titel (`story.md` Z.1 + `status.yaml`):** „AreClient-HTTP" -> „AreClient-HTTP +
  Konfig-Konstruktion/Injektion"; FK-Anker um §40.2 ergaenzt.

---

## Geaenderte Dateien (nur AG3-077)
- `stories/AG3-077-are-dock-points-full-build/story.md` — Ist-Zustand-Bullet,
  In-Scope 13 (neu) + Negativpfad-Erweiterung, AC3 (neu) + Nachnummerierung 3-12,
  DoD AK-Zaehlung, FAIL-CLOSED/SSOT-Guardrails, Quell-Konzepte (§40.2/§40.4),
  Abschnitt-6-Anker + Hinweis, Titel.
- `stories/AG3-077-are-dock-points-full-build/status.yaml` — Titel an den korrigierten
  Scope angeglichen (AreClient-Konfig-Konstruktion/Injektion, §40.2). `status`/`phase`/
  `depends_on` unveraendert (waren korrekt: die Verdrahtung ist im selben BC-Cut, keine
  neue harte Vorgaenger-Abhaengigkeit).
- `stories/AG3-077-are-dock-points-full-build/remediation-r2.md` — diese Datei.

**Kein** Produktionscode, **kein** Test, **keine** Konzeptdatei, **keine** Fremd-Story
angefasst.
