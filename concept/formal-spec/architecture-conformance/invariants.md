---
id: formal.architecture-conformance.invariants
title: Architecture Conformance Invariants
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: invariant-set
version: 6
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Invariants

Diese Invarianten definieren die importbasierten, fail-closed
Architektur-Konformanz-Invarianten fuer AK3 — den maschinenlesbaren
Kern der Konformanz-Suite (FK-07 §7.7).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.architecture-conformance.invariants
schema_version: 1
kind: invariant-set
context: architecture-conformance
dependency_rules:
  - id: architecture-conformance.rule.story_dashboard_must_not_depend_on_transport_or_hook_adapters
    source_module_prefixes:
      - agentkit.backend.story
      - agentkit.dashboard
    forbidden_module_prefixes:
      - agentkit.backend.control_plane_http
      - agentkit.harness_client.projectedge.client
      - agentkit.backend.governance.hookruntime
    message: story and dashboard application code may not depend on control-plane transport, project-edge transport, or hook runtime adapters
  - id: architecture-conformance.rule.story_dashboard_control_plane_must_not_depend_on_raw_state_drivers
    source_module_prefixes:
      - agentkit.backend.story
      - agentkit.dashboard
      - agentkit.backend.control_plane
    forbidden_module_prefixes:
      - agentkit.backend.state_backend.postgres_store
      - agentkit.backend.state_backend.sqlite_store
    message: application and control-plane modules may not import raw state-backend drivers directly
  - id: architecture-conformance.rule.projectedge_must_not_depend_on_control_plane_http
    source_module_prefixes:
      - agentkit.harness_client.projectedge
    forbidden_module_prefixes:
      - agentkit.backend.control_plane_http
    message: project-edge client must not depend on the control-plane HTTP adapter implementation
  - id: architecture-conformance.rule.control_plane_http_must_not_depend_on_state_backend_repository
    source_module_prefixes:
      - agentkit.backend.control_plane_http
    forbidden_module_prefixes:
      - agentkit.backend.state_backend.store
    message: control-plane HTTP/BFF modules may not bypass owner BC ports via direct state-backend repository access
acyclic_group_sets:
  - id: architecture-conformance.acyclic.application_surface
    group_ids:
      - architecture-conformance.group.story_types
      - architecture-conformance.group.kpi_analytics_dashboard
      - architecture-conformance.group.story_context_manager
      - architecture-conformance.group.kpi_analytics
  - id: architecture-conformance.acyclic.runtime_core
    group_ids:
      - architecture-conformance.group.pipeline_engine
      - architecture-conformance.group.story_context_manager
      - architecture-conformance.group.phase_state_store
      - architecture-conformance.group.telemetry
      - architecture-conformance.group.prompt_runtime
      - architecture-conformance.group.llm_evaluator
  - id: architecture-conformance.acyclic.governance_core
    group_ids:
      - architecture-conformance.group.guard_system
      - architecture-conformance.group.governance_observer
      - architecture-conformance.group.conformance_service
      - architecture-conformance.group.stage_registry
      - architecture-conformance.group.failure_corpus
mutation_surface_rules:
  - id: architecture-conformance.rule.story_context_write_surface
    writer_symbols:
      - save_story_context
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.pipeline_engine
      - agentkit.backend.exploration
      - agentkit.backend.implementation
      - agentkit.backend.closure
      - agentkit.backend.state_backend.store
    message: story context mutation may only be imported from state-backend or pipeline-phase surfaces
  - id: architecture-conformance.rule.phase_state_projection_write_surface
    writer_symbols:
      - save_phase_state
      - save_phase_snapshot
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
    message: phase-state projection mutation may only be imported from pipeline surfaces
  - id: architecture-conformance.rule.execution_runtime_write_surface
    writer_symbols:
      - save_flow_execution
      - save_node_execution_ledger
      - save_override_record
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
      - agentkit.backend.phase_state_store
    message: execution ledger mutation may only be imported from pipeline or phase-state-store surfaces
  - id: architecture-conformance.rule.attempt_write_surface
    writer_symbols:
      - save_attempt
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
    message: attempt mutation may only be imported from pipeline surfaces
  - id: architecture-conformance.rule.telemetry_event_write_surface
    writer_symbols:
      - append_execution_event
      - append_execution_event_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.telemetry
      - agentkit.backend.telemetry_service
      - agentkit.backend.control_plane
    message: execution event append may only be imported from telemetry or control-plane surfaces
  - id: architecture-conformance.rule.control_plane_binding_write_surface
    writer_symbols:
      - save_session_run_binding_global
      - delete_session_run_binding_global
      - save_story_execution_lock_global
      - save_control_plane_operation_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.control_plane
    message: session, lock, and control-plane operation mutation may only be imported from control-plane surfaces
  - id: architecture-conformance.rule.closure_projection_write_surface
    writer_symbols:
      - upsert_story_metrics
      - record_closure_report
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.closure
    message: closure projections may only be imported from closure surfaces
read_surface_rules:
  - id: architecture-conformance.rule.story_read_surface
    reader_symbols:
      - load_story_contexts_global
      - load_story_context_global
      - load_story_context_by_story_number_global
      - load_story_context_by_uuid_global
      - load_story_context_rows_global
      - load_phase_state_global
      - load_flow_execution_global
      - load_latest_story_metrics_global
      - load_execution_events_global
      - load_execution_event_rows_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.story.repository
    message: story read loaders may only be imported from the explicit story repository surface
  - id: architecture-conformance.rule.control_plane_runtime_read_surface
    reader_symbols:
      - load_control_plane_operation_global
      - load_session_run_binding_global
      - load_story_execution_lock_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.control_plane.repository
    message: control-plane runtime read loaders may only be imported from the explicit control-plane repository surface
  - id: architecture-conformance.rule.telemetry_project_read_surface
    reader_symbols:
      - load_execution_events_for_project_global
      - load_execution_event_rows_for_project_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.bootstrap.composition_root
    message: project-scoped telemetry execution-event read loaders may only be imported from the state-backend telemetry read surface or the composition-root wiring seam; A-code and BFF read paths must consume the published telemetry read port instead of the generic state_backend.store facade
  - id: architecture-conformance.rule.project_catalog_read_surface
    reader_symbols:
      - load_project
      - load_projects
      - load_project_by_story_id_prefix
    allowed_module_prefixes:
      - agentkit.backend.state_backend
    message: project-catalog read loaders may only be imported from the state-backend project repository surface; A-code and BFF read paths must consume the published ProjectRepository port instead of the generic state_backend.store facade
distribution_dependency_rules:
  - id: architecture-conformance.rule.core_must_not_depend_on_edge
    source_distribution: architecture-conformance.distribution.core
    forbidden_distributions:
      - architecture-conformance.distribution.edge
    include_type_checking_edges: true
    message: >-
      core modules may not import edge modules, neither directly nor
      transitively and not under TYPE_CHECKING; the core distribution must be
      installable without the edge distribution
  - id: architecture-conformance.rule.edge_must_not_depend_on_core
    source_distribution: architecture-conformance.distribution.edge
    forbidden_distributions:
      - architecture-conformance.distribution.core
    include_type_checking_edges: true
    message: >-
      edge modules may not import core modules; what the edge must not import
      is not installed on the developer machine
  - id: architecture-conformance.rule.wire_is_a_leaf
    source_distribution: architecture-conformance.distribution.wire
    forbidden_distributions:
      - architecture-conformance.distribution.edge
      - architecture-conformance.distribution.core
    include_type_checking_edges: true
    forbidden_module_prefixes:
      - os
      - io
      - pathlib
      - socket
      - subprocess
      - shutil
      - tempfile
      - sqlite3
      - urllib
      - http
      - httpx
      - requests
      - psycopg
    allowed_third_party_distributions:
      - pydantic
    forbidden_dynamic_module_loads: true
    message: >-
      the wire contract package is an I/O-free leaf: it imports neither edge
      nor core, performs no filesystem, network, database, subprocess or
      environment access, and declares no third-party dependency other than
      pydantic. dynamic loads (import_module, __import__) onto edge or core
      paths are the same violation as a static import and are checked
      separately, because the import graph does not see them
  - id: architecture-conformance.rule.no_inter_distribution_package_dependency
    scope: all-distributions
    allowed_edges:
      - from: architecture-conformance.distribution.edge
        to: architecture-conformance.distribution.wire
      - from: architecture-conformance.distribution.core
        to: architecture-conformance.distribution.wire
    message: >-
      no distribution may declare another AK3 distribution in Requires-Dist
      except edge to wire and core to wire; in particular agentkit-backend must
      not depend on agentkit-project-edge. this is independent of the import
      graph: a core wheel without a single edge import can still pull the edge
      distribution onto every core host through its metadata
  - id: architecture-conformance.rule.declared_dependencies_match_normative_sets
    scope: all-distributions
    comparison: bidirectional
    message: >-
      for every distribution the resolved Requires-Dist set must equal the
      normative runtime_dependencies set: no surplus (no core-only distribution
      inside the edge) and no shortfall (a library that only arrives
      transitively counts as undeclared). one-directional checking would have
      missed the undeclared packaging dependency of the core
  - id: architecture-conformance.rule.wire_declares_pydantic_only
    scope: architecture-conformance.distribution.wire
    message: >-
      agentkit-wire declares exactly pydantic and nothing else
  - id: architecture-conformance.rule.dual_declaration_list_is_closed
    scope: all-distributions
    applies_to: third-party-distributions-only
    message: >-
      a THIRD-PARTY library declared by both edge and core must appear in
      dual_declared_dependencies; every further dual declaration is a violation,
      so the closed list stays closed. AK3-owned distributions are out of scope:
      their dual declaration is not tolerated but mandated. the mandate does NOT
      come from no_inter_distribution_package_dependency -- that rule merely
      PERMITS the edge->wire and core->wire edges (and forbids edge<->core). it
      comes from the runtime dependency sets, which carry agentkit-wire on both
      sides, together with declared_dependencies_match_normative_sets. listing
      agentkit-wire here would file an obligation as an exception
  - id: architecture-conformance.rule.wire_surface_matches_symbol_boundaries
    scope: architecture-conformance.distribution.wire
    message: >-
      the public surface of the built agentkit-wire wheel equals the union of
      wire_exported_symbols in distribution_symbol_boundaries; every additional
      exported symbol is a violation. without this a prefix rule would drag all
      22 exception classes of backend/exceptions.py into the contract package
  - id: architecture-conformance.rule.symbol_boundary_is_the_rule
    scope: all-distributions
    counting_unit: architecture-conformance.counting_unit.public_module_symbol
    criterion: architecture-conformance.criterion.mixing_freedom
    message: >-
      the distribution boundary runs at symbol level. the counting unit is the
      public module-level symbol and the aggregation unit is the module, both
      defined in distribution_counting_unit; without a fixed unit "mixes no
      concerns" is not checkable, and the pre-measurement that preceded this
      rule mixed four units in one table. a module prefix assignment is
      permitted only where distribution_mixing_freedom_criterion holds; where
      it does not, the target distribution inherits everything else the module
      does. the criterion is a VETO, not an election: it can forbid an
      assignment, it can never choose a side. the side is elected by the
      entry-point contract (FK-10 section 10.2.11) together with the authority
      invariants I1/I3/I5, and every elected side carries its own
      distribution_membership_evidence entry. a prefix assignment without
      measured evidence is a violation of this rule, not a special case
  - id: architecture-conformance.rule.distribution_membership_is_total_and_disjoint
    scope: all-distributions
    precondition: distribution_classification_status is closed
    precondition_check: pending_symbol_inventory is empty
    message: >-
      every module under the AK3 import root belongs to exactly one
      distribution; membership resolves by longest matching module prefix, and
      two equally long matching prefixes owned by different distributions are a
      violation rather than a resolution case. there is deliberately NO default
      distribution: a fallback would assign an owner to every unmeasured module
      without evidence. the precondition has two parts and BOTH must hold:
      distribution_classification_status is closed AND pending_symbol_inventory
      is empty. an open classification or a non-empty pending inventory makes
      the function non-total and the gate reports NOT_RUN with reason
  - id: architecture-conformance.rule.import_root_follows_distribution_name
    scope: all-distributions
    message: >-
      each distribution's target_import_root equals its distribution_name with
      hyphens replaced by underscores; no distribution and no import root is
      named 'agentkit'
  - id: architecture-conformance.rule.single_resolution_path
    scope: all-distributions
    message: >-
      no alias, shim, re-export module or transition window in which an old and
      a new import root both resolve; a second resolution path for the same
      symbol is a violation, not a migration
packaging_gate:
  id: architecture-conformance.gate.distribution_packaging
  blocking: true
  baseline_allowed: false
  result_states:
    - PASS
    - FAIL
    - NOT_RUN
  missing_result_is: FAIL
  not_run_requires_reason: true
  # Solange pending_symbol_inventory nicht leer ist, ist die
  # Zugehoerigkeitsfunktion unvollstaendig. Das Gate meldet dann NOT_RUN mit
  # genau diesem Grund -- nicht PASS, und auch nicht FAIL: es hat nichts
  # gemessen, was falsch waere, sondern etwas, das noch nicht entschieden ist.
  #
  # AG3-237 hat die Klassifikation geschlossen. Der Zweig bleibt bestehen: er
  # ist die Vorbedingungspruefung des Gates, nicht ein Vermerk ueber einen
  # einmaligen Zustand. Wer spaeter ein Paket wieder auf Pending stellt, faellt
  # damit automatisch auf NOT_RUN zurueck statt still auf PASS.
  pending_membership:
    blocks_pass: true
    result_state: NOT_RUN
    precondition: >-
      pending_symbol_inventory is empty AND distribution_classification_status
      is closed
    current_state: >-
      satisfied since 2026-08-07 (AG3-237): pending_symbol_inventory is empty
      and all 44 immediate backend subpackages plus the root module
      exceptions.py carry a measured membership in
      distribution_membership_evidence
    reason: >-
      distribution membership incomplete -- pending_symbol_inventory is not
      empty or distribution_classification_status is not closed
  # Gate-Checkliste: was VOR dem ersten Lauf erfuellt sein muss. AG3-209 baut
  # das Gate; diese Liste ist die Vorbedingung, die es nicht uebersehen darf.
  preconditions:
    - id: architecture-conformance.gate.precondition.pending_inventory_empty
      requirement: pending_symbol_inventory is empty
      owner: AG3-237
      status: satisfied
      note: >-
        the gate must READ this predicate at run time and report NOT_RUN when
        it fails. a gate that only checks it once at build time would pass on a
        classification that was reopened afterwards
    - id: architecture-conformance.gate.precondition.every_prefix_has_evidence
      requirement: >-
        every module_prefix and module_member of every distribution has a
        matching measured-evidence entry -- the 46 backend entries in
        distribution_membership_evidence and the 8 anchor entries in
        distribution_anchors. the earlier wording said "under agentkit.backend"
        and thereby exempted the anchors from AC 3, which AC 3 does not permit
      owner: AG3-237
      status: satisfied
  checks:
    - id: architecture-conformance.gate.check.source_graph
      subject: source-import-graph
      evaluates:
        - architecture-conformance.rule.core_must_not_depend_on_edge
        - architecture-conformance.rule.edge_must_not_depend_on_core
        - architecture-conformance.rule.wire_is_a_leaf
        - architecture-conformance.rule.distribution_membership_is_total_and_disjoint
        - architecture-conformance.rule.import_root_follows_distribution_name
        - architecture-conformance.rule.single_resolution_path
      reports:
        - modules_per_distribution
        - forbidden_edges_with_locator
    - id: architecture-conformance.gate.check.wheel_reachability
      subject: built-wheels
      evaluates:
        - architecture-conformance.rule.no_inter_distribution_package_dependency
        - architecture-conformance.rule.declared_dependencies_match_normative_sets
        - architecture-conformance.rule.wire_declares_pydantic_only
        - architecture-conformance.rule.dual_declaration_list_is_closed
        - architecture-conformance.rule.wire_surface_matches_symbol_boundaries
      rule: >-
        (a) no built wheel contains a module belonging to a foreign
        distribution; (b) no distribution declares another AK3 distribution
        except edge to wire and core to wire; (c) agentkit-wire declares exactly
        pydantic; (d) every resolved Requires-Dist set equals its normative set
        in both directions; (e) dual declarations stay inside
        dual_declared_dependencies; (f) the public wire surface equals the
        declared symbol boundaries
      reports:
        - wheel_contents_per_distribution
        - resolved_dependency_set_per_distribution
        - inter_distribution_dependency_edges
        - dependency_set_surplus_and_shortfall_per_distribution
        - wire_public_surface_vs_symbol_boundaries
    - id: architecture-conformance.gate.check.clean_edge_install
      subject: empty-environment
      rule: >-
        in a previously empty environment that carries only
        agentkit-project-edge, a real agentkit-hook-claude or
        agentkit-hook-codex process fed real stdin must return a decision, and
        no distribution listed in core_only_distributions may be present;
        a dry run or a unit test does not satisfy this check
      reports:
        - installed_distribution_inventory
        - hook_process_exit_code
        - hook_process_output
invariants:
  - id: architecture-conformance.invariant.core_does_not_reach_edge
    scope: static-analysis
    rule: no module of the core distribution reaches a module of the edge distribution, directly or transitively, including TYPE_CHECKING edges
  - id: architecture-conformance.invariant.edge_does_not_reach_core
    scope: static-analysis
    rule: no module of the edge distribution reaches a module of the core distribution, directly or transitively, including TYPE_CHECKING edges
  - id: architecture-conformance.invariant.wire_is_an_io_free_leaf
    scope: static-analysis
    rule: the wire contract package imports neither edge nor core, performs no I/O and depends on pydantic only; dynamic module loads onto edge or core paths count as imports
  - id: architecture-conformance.invariant.no_distribution_depends_on_another_except_wire
    scope: build-artifact
    rule: package metadata declares no AK3 distribution dependency other than edge to wire and core to wire; a core wheel that depends on the edge distribution violates the architecture even with a clean import graph
  - id: architecture-conformance.invariant.declared_dependencies_equal_normative_sets
    scope: build-artifact
    rule: resolved Requires-Dist equals the normative runtime dependency set of its distribution in both directions; transitive-only availability counts as undeclared
  - id: architecture-conformance.invariant.wire_surface_is_symbol_bounded
    scope: build-artifact
    rule: the public surface of the built wire wheel equals the union of the declared wire_exported_symbols; modules whose boundary runs through them must be split as specified
  - id: architecture-conformance.invariant.symbol_boundary_is_the_rule
    scope: static-analysis
    rule: the distribution boundary is defined at symbol level, counted in public module-level symbols and aggregated per module; module prefix assignment is an optimisation permitted only where the measured mixing-freedom criterion holds, and the criterion vetoes an assignment without ever electing a side
  - id: architecture-conformance.invariant.distribution_membership_is_total_and_disjoint
    scope: static-analysis
    rule: distribution membership is a total and disjoint function over the AK3 module set; AG3-237 closed the classification on 2026-08-07 for all 44 immediate backend subpackages plus the root module exceptions.py. no module is homeless and none has two owners, and there is no default distribution to hide an unmeasured module in. an open classification or a non-empty pending_symbol_inventory makes the gate report NOT_RUN, never PASS
  - id: architecture-conformance.invariant.packaging_gate_is_blocking_and_baseline_free
    scope: build-artifact
    rule: the packaging gate blocks on violation, keeps no baseline of tolerated findings, and distinguishes NOT_RUN with a named reason from PASS; a missing or unreadable result counts as FAIL
  - id: architecture-conformance.invariant.clean_edge_install_runs_a_real_hook
    scope: build-artifact
    rule: an edge-only installation in a previously empty environment executes a real hook process against real stdin and carries no core-only distribution; a dry run or unit test does not satisfy the invariant
  - id: architecture-conformance.invariant.story_dashboard_transport_boundary
    scope: static-analysis
    rule: story and dashboard modules may not directly import transport or hook adapters
  - id: architecture-conformance.invariant.raw_driver_boundary
    scope: static-analysis
    rule: stable application-surface modules may not import raw state backend drivers directly
  - id: architecture-conformance.invariant.control_plane_http_has_no_persistence_bypass
    scope: static-analysis
    rule: control-plane HTTP/BFF modules compose frontend read models through owner BC read/query ports and never import state-backend repository internals directly
  - id: architecture-conformance.invariant.application_surface_is_acyclic
    scope: static-analysis
    rule: story-types, kpi-analytics dashboard, story-context-manager and kpi-analytics must not form dependency cycles. control_plane and projectedge cyclicity is enforced separately via boundary_module dependency rules.
  - id: architecture-conformance.invariant.runtime_core_is_acyclic
    scope: static-analysis
    rule: pipeline_engine, story_context_manager, phase_state_store, telemetry, prompt_runtime and llm_evaluator must not form dependency cycles
  - id: architecture-conformance.invariant.governance_core_is_acyclic
    scope: static-analysis
    rule: guard_system, governance_observer, conformance_service, stage_registry and failure_corpus must not form dependency cycles
  - id: architecture-conformance.invariant.canonical_write_surface_is_bounded
    scope: static-analysis
    rule: imports of canonical write symbols must stay within explicitly approved mutation surfaces
  - id: architecture-conformance.invariant.story_read_surface_is_bounded
    scope: static-analysis
    rule: imports of global story read loaders must stay within the explicit story repository surface
  - id: architecture-conformance.invariant.control_plane_runtime_read_surface_is_bounded
    scope: static-analysis
    rule: imports of global control-plane runtime read loaders must stay within the explicit control-plane repository surface
  - id: architecture-conformance.invariant.telemetry_project_read_surface_is_bounded
    scope: static-analysis
    rule: imports of the global project-scoped telemetry execution-event read loader must stay within the state-backend telemetry read surface and the composition-root wiring seam; A-code and BFF read models depend on the published telemetry read port, not on the generic state_backend.store facade
  - id: architecture-conformance.invariant.project_catalog_read_surface_is_bounded
    scope: static-analysis
    rule: imports of the project-catalog read loaders must stay within the state-backend project repository surface; A-code and BFF read models depend on the published ProjectRepository port, not on the generic state_backend.store facade
```
<!-- FORMAL-SPEC:END -->
