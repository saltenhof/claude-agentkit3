# Principal Capabilities

Dieser Kontext formalisiert die technische Capability-Schicht unterhalb
der fachlichen Rollen. Er beschreibt nicht, *warum* eine Rolle etwas
tut, sondern welche Principals welche Operationen in welchen
Pfadklassen und Story-Zustaenden technisch ausfuehren duerfen.

Ergaenzende Prosa-Konzepte:

- [FK-55](/T:/codebase/claude-agentkit3/concept/technical-design/55_principal_capability_model_story_scope_enforcement.md)
- [FK-30](/T:/codebase/claude-agentkit3/concept/technical-design/30_hook_adapter_guard_enforcement.md)
- [FK-31](/T:/codebase/claude-agentkit3/concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-42](/T:/codebase/claude-agentkit3/concept/technical-design/42_ccag_tool_governance_permission_runtime.md)

Der Kontext ist bewusst querschnittlich: Er ist keine neue
Laufzeitkomponente neben dem GuardSystem, sondern der formale Vertrag,
nach dem GuardSystem, CCAG und offizielle Servicepfade geschnitten
werden.
