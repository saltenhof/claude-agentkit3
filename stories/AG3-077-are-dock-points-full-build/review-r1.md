OVERALL CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: FAIL**

- ERROR: `AreClient` ist fälschlich out of scope. Die Story sagt „REST-Adapter … wird nur konsumiert“ (`stories/AG3-077-are-dock-points-full-build/story.md:43`), aber der reale Adapter ist selbst vollständig Stub: `are_client.py:1-5`, `:37-50`, `:52-65`, `:67-79`, `:81-103`, `:105-117`. Damit können die Dock-Points keine echten ARE-Ergebnisse liefern, außer die Implementierung baut verdeckte Fallbacks oder testet gegen Attrappen.  
  Fix: `AreClient`-HTTP-Implementierung explizit in scope nehmen oder die Story als zweiteilig schneiden: zuerst realer Adapter/Port, danach Dock-Points.

- ERROR: Phase-State-Zielmodell für `are_bundle` fehlt. Die Story verlangt ein `are_bundle`-Signal im Phase-State (`story.md:33`, `:53`), aber `SetupPayload` erlaubt aktuell nur `phase_type` und ist `extra="forbid"` (`src/agentkit/story_context_manager/models.py:74-78`); `PhaseState.payload` ist typisiert (`models.py:436-440`).  
  Fix: `AreBundleStatus`/`AreBundleSignal` und deren Platz im `SetupPayload` oder einem anderen kanonischen Control-Plane-Modell konkret spezifizieren.

**2. AC-Schaerfe: FAIL**

- ERROR: `CoverageVerdict`-ACs verlangen Felder, die das reale Modell nicht hat. Die Story fordert `reason="are_gate_unavailable"` und `uncovered_requirements` (`story.md:36`, `:56`), aber `CoverageVerdict` erlaubt nur `status` und `verdict` (`src/agentkit/requirements_coverage/contract.py:149-161`, `extra="forbid"`).  
  Fix: AC erweitern: Contract-Modelländerung mit Feldern `reason` und `uncovered_requirements` plus Schema-/Contract-Tests, oder andere Ergebnisstruktur definieren.

- ERROR: `submit_evidence`-Teilabdeckung ist nicht entscheidbar. Die Story verlangt optionales `kind`-UPDATE `addresses -> partial` (`story.md:35`, `:55`), aber `AreEvidence` enthält keinen Partial-/Coverage-Kind-Indikator (`src/agentkit/requirements_coverage/contract.py:89-105`).  
  Fix: Auslöser modellieren: z. B. neues Feld `coverage_kind`/`partial` oder klare Regel, dass ARE-Response die Änderung triggert.

- WARNING: `link_requirements(story_id, project_key)` braucht `scope` und `story_type`, aber die Signatur liefert sie nicht. FK-40 verlangt `are_get_recurring(scope, story_type)` (`concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md:238-243`), die Story belässt die Methode bei `story_id, project_key` (`story.md:32`), und die reale Top-Surface hat keine weiteren Resolver-Abhängigkeiten (`src/agentkit/requirements_coverage/top.py:62-68`, `:84`).  
  Fix: Scope-/StoryType-Quelle als Port oder explizite Parameter festlegen.

**3. Klarheit: WEAK**

- ERROR: Der behauptete `are_gate.json`-Konsument ist falsch. Die Story sagt, der bestehende Layer-1-Konsument lese `are_gate.json` (`story.md:36`, `:56`, `:76`). Real erwartet `check_are_gate` ein bereits aufgelöstes `CoverageVerdict`, keinen Dateipfad (`src/agentkit/verify_system/structural/checks/are_gate.py:35-41`), und der Dispatcher ruft `are.coverage_verdict(...)` direkt auf (`src/agentkit/verify_system/structural/checker.py:448-450`).  
  Fix: Story korrigieren: `are_gate.json` ist neu zu erzeugendes Audit-/QA-Artefakt, nicht bestehender Input des Layer-1-Checks, oder explizit den Layer-1-Pfad umbauen.

- WARNING: Setup-Einhängepunkt ist zu unpräzise. Die Story sagt „vor der Story-Typ-Weiche“ (`story.md:34`, `:58`), der reale `SetupPhaseHandler` baut Context und speichert ihn in `on_enter` (`src/agentkit/governance/setup_preflight_gate/phase.py:174-180`), prüft green-main danach (`:182-186`) und ist über `build_setup_phase_handler` verdrahtet (`src/agentkit/bootstrap/composition_root.py:1317-1362`).  
  Fix: Den konkreten Collaborator und die Einfügestelle benennen, inklusive `HandlerResult.updated_state`/Phase-State-Persistenz.

**4. Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Die Story widerspricht dem aktuellen Verify-System-Vertrag durch die Datei-Lese-Annahme für `are_gate.json` und durch nicht existierende `CoverageVerdict`-Felder. Das würde Implementierer entweder zu parallelen Wahrheiten oder zu unklaren Contract-Änderungen zwingen.  
  Evidence: `story.md:36`, `:56`; `contract.py:149-161`; `checker.py:448-450`.

- WARNING: Stale-`are_item_id` wird ohne Owner/Story aus scope geschoben (`story.md:46`), obwohl FK-40 es beim Gate sichtbar machen muss (`concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md:438-445`).  
  Fix: Entweder in AG3-077 aufnehmen oder mit konkreter Folge-Story/Owner als bewusst verbleibende Lücke ausweisen.

**Must-Fix**

1. `AreClient`-Stub-Status auflösen: in AG3-077 scope aufnehmen oder vorgelagerte Story als harte Abhängigkeit schneiden.
2. `CoverageVerdict`/Gate-Result-Vertrag konkretisieren, inklusive `reason` und `uncovered_requirements` oder alternativer Struktur.
3. Falsche Aussage entfernen, dass `are_gate.py` `are_gate.json` liest.
4. `are_bundle`-Phase-State-Modell typisiert definieren.
5. Scope-/StoryType-Ermittlung für `link_requirements` festlegen.
6. Partial-Evidence-Auslöser für `submit_evidence` modellieren.
