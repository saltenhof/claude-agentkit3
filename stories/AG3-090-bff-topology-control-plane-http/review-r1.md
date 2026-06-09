OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**

- ERROR: SSE-Owner ist falsch geschnitten. AG3-090 weist `/v1/projects/{key}/events?topics=` AG3-094 zu ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:44)), aber AG3-094 sagt: Backend-SSE-Endpoint ist AG3-003 completed, AG3-094 baut nur den Frontend-Consumer ([AG3-094 story.md](T:/codebase/claude-agentkit3/stories/AG3-094-dashboards-live-updates-sse/story.md:51)). Der reale Endpoint existiert bereits in `telemetry/http` ([routes.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/http/routes.py:22), [routes.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/http/routes.py:52)).  
  Fix: Out-of-Scope splitten: Backend-SSE = AG3-003, Producer/Topics = AG3-081, Frontend-Consumer = AG3-094. AG3-090 darf nur Tenant-Middleware-Kompatibilitaet fuer den bestehenden SSE-Pfad absichern.

- ERROR: KPI-Route kollidiert mit benachbarten Stories. AG3-090 setzt `kpi_analytics/http/ -> /v1/projects/{key}/kpis` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:36)); AG3-084 fixiert dagegen final z. B. `/v1/projects/{project_key}/kpi/stories` ([AG3-084 story.md](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:54)), und AG3-094 konsumiert `/v1/.../kpi/*` ([AG3-094 story.md](T:/codebase/claude-agentkit3/stories/AG3-094-dashboards-live-updates-sse/story.md:49)).  
  Fix: Einen kanonischen Root entscheiden und alle drei Stories/Index darauf angleichen; bis dahin darf AG3-090 keinen widersprechenden KPI-Pfad als erreichbar akzeptieren.

**AC-Schaerfe: FAIL**

- ERROR: AC2 beweist nur “mind. ein bestehender Endpunkt”, obwohl FK-72 alle projektbezogenen Ressourcen pfadgescoped verlangt ([FK-72](T:/codebase/claude-agentkit3/concept/technical-design/72_frontend_architektur.md:197)). Der Code hat mehrere ungescopte Story-/Runtime-Pfade: `/v1/stories*` ([routes.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/http/routes.py:4), [routes.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/http/routes.py:49)) und `/v1/story-runs/...` ([http.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/http.py:61)).  
  Fix: AC verlangt vollständige Altpfad-Inventur + Tests fuer Collection, Detail, Mutationen, Fields, Phase-/Closure- und Dashboard-Pfade; kein alter projektbezogener Fallthrough ohne explizite Legacy-Entscheidung.

- ERROR: Pflicht-Gates unvollstaendig. Story nennt lokale Tests/ruff/mypy/Konzept-Gates ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:57)), aber AGENTS verlangt Jenkins, Sonar und `scripts/ci/check_remote_gates.ps1` ([AGENTS.md](T:/codebase/claude-agentkit3/AGENTS.md:33), [AGENTS.md](T:/codebase/claude-agentkit3/AGENTS.md:43)).  
  Fix: AC8 um Remote-Gate-Befehl und Sonar-Zielwerte `violations=0`, `critical_violations=0`, `security_hotspots=0` erweitern.

**Klarheit: WEAK**

- WARNING: Namespace-Strategie bleibt als Owner-Klaerung offen: Scope erlaubt Move oder Re-Export ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:27)), Hinweise delegieren die Entscheidung erneut an den Owner ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:74)).  
  Fix: Vor Freigabe entscheiden: entweder `control_plane_http` ist neuer Import-Owner mit Compat-Reexport, oder reine Web-Abspaltung. Tests und Import-Migration daran binden.

- WARNING: `/v1/projects` “Liste/CRUD” wird als nicht-projektbezogen bezeichnet ([story.md](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/story.md:28)); FK-73 beschreibt aber Detail/Patch/Archive als Project-Management-Ressourcen ([FK-73](T:/codebase/claude-agentkit3/concept/technical-design/73_project_management.md:73)).  
  Fix: Als “project_management-Sonderoberflaeche ohne doppelten Projekt-Praefix” formulieren, nicht als projektneutral.

**Kontext-Sinnhaftigkeit: FAIL**

- WARNING: `status.yaml` hat `unblocks: []` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-090-bff-topology-control-plane-http/status.yaml:10)), obwohl Index und Nachbarstories AG3-091/AG3-093 direkt von AG3-090 abhaengen ([index](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:116), [index](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:118)).  
  Fix: Entweder direkte `unblocks` pflegen (`AG3-091`, `AG3-093`) oder das Feld als nicht-reziprok dokumentieren; nicht still leer lassen.

- PASS-Hinweis zu den Ist-Zustand-Ankern: Die konkreten Line-Claims in Abschnitt 1 sind im aktuellen Code wahr: `ControlPlaneApplication.handle_request` ab [http.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/http.py:185), Auth-Middleware [http.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/http.py:202), `/v1/stories` Query-`project_key` [http.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/http.py:692), und vorhandene `http/`-Module entsprechen dem Glob.

**Must-Fix**

1. AC2 auf vollständige Migration aller projektbezogenen Altpfade schärfen.
2. SSE-Out-of-Scope-Owner korrigieren: AG3-003/AG3-081/AG3-094 statt pauschal AG3-094.
3. KPI-Root-Konflikt `/kpis` vs `/kpi/*` vor Freigabe entscheiden.
4. Remote-Gates/Jenkins/Sonar in AC8 aufnehmen.
5. Namespace-Migrationsvariante verbindlich festlegen.
