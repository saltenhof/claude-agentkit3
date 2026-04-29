"""Authoritative Python representation of the AK3 fachliches Datenmodell (FK-17).

This module is the single source of truth for diagram exports. It does
NOT replace FK-17 — it mirrors the entity catalogue from FK-17 §17.3,
the attribute contracts from §17.3a, and the relations from §17.4 in
machine-readable form so that Mermaid and Draw.io renderings stay in
sync without hand-editing two files.

When FK-17 changes, update ENTITIES / RELATIONSHIPS here and re-run
`python -m tools.diagram_export.cli`.
"""

from __future__ import annotations

import html
import textwrap
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as xml_escape


@dataclass(frozen=True)
class Attribute:
    name: str
    type_name: str
    required: bool
    pk: bool = False
    fk: bool = False


@dataclass(frozen=True)
class Entity:
    name: str
    owner: str
    aggregate_role: str       # "root" | "internal" | "projection"
    persistence_tag: str
    attributes: tuple[Attribute, ...]
    column: int               # layout column 0..N
    row: int                  # layout row 0..N


@dataclass(frozen=True)
class Relationship:
    source: str
    target: str
    cardinality: str          # mermaid notation, e.g. "||--o{"
    label: str


# ---------------------------------------------------------------------------
# Entities (FK-17 §17.3 + §17.3a)
# ---------------------------------------------------------------------------

ENTITIES: tuple[Entity, ...] = (
    Entity(
        name="ProjectSpace",
        owner="installer",
        aggregate_role="root",
        persistence_tag="canonical_runtime_snapshot",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("display_name", "Text", True),
            Attribute("project_root", "PathRef", True),
            Attribute("runtime_profile", "Enum<RuntimeProfile>", True),
            Attribute("registration_status", "Enum<RegistrationStatus>", True),
            Attribute("skill_bundle_version", "Text", True),
            Attribute("prompt_bundle_version", "Text", True),
        ),
        column=0,
        row=0,
    ),
    Entity(
        name="Story",
        owner="story_context_manager",
        aggregate_role="root",
        persistence_tag="canonical_runtime_snapshot",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, pk=True),
            Attribute("external_item_ref", "UriRef", True),
            Attribute("title", "Text", True),
            Attribute("story_type", "Enum<StoryType>", True),
            Attribute("mode", "Enum<StoryMode>", True),
            Attribute("labels", "StringSet", False),
            Attribute("size", "Text", False),
            Attribute("status", "Enum<StoryStatus>", True),
        ),
        column=0,
        row=1,
    ),
    Entity(
        name="StoryContext",
        owner="story_context_manager",
        aggregate_role="root",
        persistence_tag="canonical_runtime_snapshot",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, pk=True),
            Attribute("story_type", "Enum<StoryType>", True),
            Attribute("mode", "Enum<StoryMode>", True),
            Attribute("scope", "Text|JsonValue", True),
            Attribute("scope_keys", "StringSet", False),
            Attribute("repo_bindings", "JsonObject", True),
            Attribute("concept_refs", "StringList", False),
            Attribute("guardrail_refs", "StringList", False),
            Attribute("external_sources", "StringList", False),
            Attribute("related_story_ids", "StringSet", False),
            Attribute("story_semantics", "JsonObject", False),
            Attribute("tracker_binding", "JsonObject", True),
            Attribute("created_at", "Instant", True),
            Attribute("last_refreshed_at", "Instant", True),
        ),
        column=0,
        row=2,
    ),
    Entity(
        name="StoryCustomFieldDefinition",
        owner="story_context_manager",
        aggregate_role="root",
        persistence_tag="canonical_runtime_snapshot",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("field_key", "FieldKey", True, pk=True),
            Attribute("display_name", "Text", True),
            Attribute("field_type", "Text", True),
            Attribute("provider", "Text", True),
            Attribute("provider_field_ref", "UriRef|Text", True),
            Attribute("is_required", "Boolean", True),
            Attribute("is_writable_by_agentkit", "Boolean", True),
            Attribute("allowed_values", "StringList", False),
        ),
        column=1,
        row=0,
    ),
    Entity(
        name="StoryCustomFieldValue",
        owner="story_context_manager",
        aggregate_role="internal",  # belongs to Story aggregate
        persistence_tag="canonical_runtime_snapshot",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, pk=True),
            Attribute("field_key", "FieldKey", True, pk=True),
            Attribute("value", "JsonValue", False),
            Attribute("value_status", "Text", False),
            Attribute("source", "Text", True),
            Attribute("last_synced_at", "Instant", False),
            Attribute("last_written_by", "Text", False),
            Attribute("provider_sync_status", "Enum<ProviderSyncStatus>", True),
            Attribute("conflict_detected", "Boolean", True),
            Attribute("last_sync_attempt_at", "Instant", False),
        ),
        column=1,
        row=1,
    ),
    Entity(
        name="FlowExecution",
        owner="pipeline_engine",
        aggregate_role="root",
        persistence_tag="canonical_runtime_ledger",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, pk=True),
            Attribute("flow_id", "FlowId", True, pk=True),
            Attribute("flow_level", "Enum<FlowLevel>", True),
            Attribute("owner_component", "Text", True),
            Attribute("status", "Enum<FlowStatus>", True),
            Attribute("current_node_id", "NodeId", False),
            Attribute("attempt_no", "Integer", True),
            Attribute("started_at", "Instant", True),
            Attribute("finished_at", "Instant", False),
        ),
        column=2,
        row=0,
    ),
    Entity(
        name="NodeExecution",
        owner="pipeline_engine",
        aggregate_role="internal",  # in FlowExecution aggregate
        persistence_tag="canonical_runtime_ledger",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("flow_id", "FlowId", True, fk=True),
            Attribute("node_id", "NodeId", True, pk=True),
            Attribute("attempt_no", "Integer", True, pk=True),
            Attribute("outcome", "Enum<NodeOutcome>", True),
            Attribute("started_at", "Instant", True),
            Attribute("finished_at", "Instant", False),
            Attribute("resume_trigger", "Text", False),
            Attribute("backtrack_target", "NodeId", False),
        ),
        column=2,
        row=1,
    ),
    Entity(
        name="AttemptRecord",
        owner="pipeline_engine",
        aggregate_role="internal",  # in FlowExecution aggregate
        persistence_tag="canonical_audit_append",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("phase", "Text", True, pk=True),
            Attribute("attempt_no", "Integer", True, pk=True),
            Attribute("outcome", "Enum<AttemptOutcome>", True),
            Attribute("failure_cause", "Text|JsonValue", False),
            Attribute("started_at", "Instant", True),
            Attribute("ended_at", "Instant", True),
        ),
        column=2,
        row=2,
    ),
    Entity(
        name="PhaseState",
        owner="phase_state_store",
        aggregate_role="projection",
        persistence_tag="runtime_projection",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, pk=True),
            Attribute("run_id", "RunId", True, pk=True),
            Attribute("phase", "Text", True),
            Attribute("status", "Enum<FlowStatus>", True),
            Attribute("payload", "JsonObject", False),
            Attribute("updated_at", "Instant", True),
        ),
        column=2,
        row=3,
    ),
    Entity(
        name="OverrideRecord",
        owner="guard_system",
        aggregate_role="root",
        persistence_tag="canonical_audit_append",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("flow_id", "FlowId", True, fk=True),
            Attribute("target_node_id", "NodeId", False),
            Attribute("override_type", "Enum<OverrideType>", True),
            Attribute("actor_type", "Enum<ActorType>", True),
            Attribute("actor_id", "Text", True),
            Attribute("reason", "Text", True),
            Attribute("created_at", "Instant", True),
            Attribute("consumed_at", "Instant", False),
        ),
        column=3,
        row=0,
    ),
    Entity(
        name="GuardDecision",
        owner="guard_system",
        aggregate_role="root",
        persistence_tag="canonical_audit_append",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("flow_id", "FlowId", True, fk=True),
            Attribute("node_id", "NodeId", False),
            Attribute("guard_key", "Text", True, pk=True),
            Attribute("outcome", "Enum<GuardOutcome>", True),
            Attribute("reason", "Text", False),
            Attribute("evidence_ref", "UriRef|PathRef", False),
            Attribute("decided_at", "Instant", True),
        ),
        column=3,
        row=1,
    ),
    Entity(
        name="ArtifactRecord",
        owner="artifact_manager",
        aggregate_role="root",
        persistence_tag="canonical_runtime_ledger",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("artifact_id", "ArtifactId", True, pk=True),
            Attribute("artifact_class", "Text", True),
            Attribute("artifact_kind", "Text", True),
            Attribute("artifact_format", "Text", True),
            Attribute("artifact_status", "Enum<ArtifactStatus>", True),
            Attribute("produced_in_phase", "Text", True),
            Attribute("producer_component", "Text", True),
            Attribute("producer_trust", "Text", True),
            Attribute("attempt_no", "Integer", False),
            Attribute("qa_cycle_id", "Text", False),
            Attribute("qa_cycle_round", "Integer", False),
            Attribute("evidence_epoch", "Integer", False),
            Attribute("protection_level", "Enum<ProtectionLevel>", True),
            Attribute("frozen", "Boolean", True),
            Attribute("integrity_verified", "Boolean", True),
            Attribute("created_at", "Instant", True),
            Attribute("finished_at", "Instant", False),
            Attribute("storage_ref", "PathRef|UriRef", True),
        ),
        column=3,
        row=2,
    ),
    Entity(
        name="ExecutionEvent",
        owner="telemetry_service",
        aggregate_role="root",
        persistence_tag="runtime_observation_append",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("story_id", "StoryId", True, fk=True),
            Attribute("run_id", "RunId", True, fk=True),
            Attribute("event_type", "Text", True),
            Attribute("occurred_at", "Instant", True),
            Attribute("source_component", "Text", True),
            Attribute("flow_id", "FlowId", False),
            Attribute("node_id", "NodeId", False),
            Attribute("severity", "Enum<EventSeverity>", True),
            Attribute("event_payload_ref", "UriRef|JsonValue", False),
        ),
        column=3,
        row=3,
    ),
    Entity(
        name="KpiProjection",
        owner="analytics",
        aggregate_role="projection",
        persistence_tag="analytics_projection",
        attributes=(
            Attribute("project_key", "ProjectKey", True, pk=True),
            Attribute("projection_key", "Text", True, pk=True),
            Attribute("metric_name", "Text", True),
            Attribute("metric_value", "JsonValue", True),
            Attribute("window_start", "Instant", False),
            Attribute("window_end", "Instant", False),
            Attribute("computed_at", "Instant", True),
        ),
        column=4,
        row=0,
    ),
)


# ---------------------------------------------------------------------------
# Relationships (FK-17 §17.4)
# ---------------------------------------------------------------------------

RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship("ProjectSpace", "Story", "||--o{", "owns"),
    Relationship("ProjectSpace", "StoryCustomFieldDefinition", "||--o{", "scopes"),
    Relationship("ProjectSpace", "KpiProjection", "||--o{", "aggregates"),
    Relationship("Story", "StoryContext", "||--||", "snapshot"),
    Relationship("Story", "StoryCustomFieldValue", "||--o{", "has-values"),
    Relationship("StoryCustomFieldDefinition", "StoryCustomFieldValue", "||--o{", "defines"),
    Relationship("Story", "Story", "||--o{", "split-lineage"),
    Relationship("Story", "FlowExecution", "||--o{", "executes-as"),
    Relationship("Story", "PhaseState", "||--o{", "per-run-projection"),
    Relationship("FlowExecution", "NodeExecution", "||--o{", "node-ledger"),
    Relationship("FlowExecution", "AttemptRecord", "||--o{", "phase-audit"),
    Relationship("FlowExecution", "OverrideRecord", "||--o{", "received"),
    Relationship("FlowExecution", "GuardDecision", "||--o{", "yielded"),
    Relationship("FlowExecution", "ArtifactRecord", "||--o{", "produced"),
    Relationship("FlowExecution", "ExecutionEvent", "||--o{", "emitted"),
    Relationship("ExecutionEvent", "KpiProjection", "}o--o{", "feeds"),
)


# ---------------------------------------------------------------------------
# Mermaid renderer
# ---------------------------------------------------------------------------

def render_mermaid() -> str:
    lines: list[str] = []
    lines.append("erDiagram")
    lines.append("")
    lines.append("    %% AK3 - Fachliches Datenmodell (FK-17, generiert)")
    lines.append("    %% Owner-Schichten:")
    for owner in sorted({e.owner for e in ENTITIES}):
        members = ", ".join(e.name for e in ENTITIES if e.owner == owner)
        lines.append(f"    %%   {owner:24s}: {members}")
    lines.append("")
    for rel in RELATIONSHIPS:
        lines.append(
            f"    {rel.source:30s} {rel.cardinality} {rel.target:30s} : \"{rel.label}\""
        )
    lines.append("")
    for entity in ENTITIES:
        lines.append(f"    {entity.name} {{")
        for attr in entity.attributes:
            marker = ""
            if attr.pk:
                marker = " PK"
            elif attr.fk:
                marker = " FK"
            type_token = attr.type_name.replace(" ", "_").replace("|", "_or_")
            lines.append(f"        {type_token:32s} {attr.name}{marker}")
        lines.append("    }")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Draw.io renderer
# ---------------------------------------------------------------------------

_AGG_COLORS = {
    "root": ("#dae8fc", "#6c8ebf"),
    "internal": ("#d5e8d4", "#82b366"),
    "projection": ("#fff2cc", "#d6b656"),
}

_OWNER_BAR_COLORS = {
    "installer": "#9673A6",
    "story_context_manager": "#1A6CC2",
    "pipeline_engine": "#0E8A4F",
    "phase_state_store": "#2BA88A",
    "guard_system": "#B25E2F",
    "artifact_manager": "#A02929",
    "telemetry_service": "#8C7A1B",
    "analytics": "#6E4FB2",
}

_COLUMN_X = (40, 360, 720, 1080, 1440)
_ROW_Y_BASE = 40
_ROW_GAP = 40
_BOX_WIDTH = 300
_HEADER_LINES = 6        # name + dash + owner + role + store + blank
_LINE_H = 16             # Courier 11pt with comfortable spacing
_PADDING_V = 16


def _box_height(entity: Entity) -> int:
    return (_HEADER_LINES + len(entity.attributes)) * _LINE_H + _PADDING_V


def _layout_positions() -> dict[str, tuple[int, int, int, int]]:
    """Return (x, y, w, h) for every entity using the column/row hints."""
    by_col: dict[int, list[Entity]] = {}
    for e in ENTITIES:
        by_col.setdefault(e.column, []).append(e)
    positions: dict[str, tuple[int, int, int, int]] = {}
    for col, members in by_col.items():
        members.sort(key=lambda e: e.row)
        y = _ROW_Y_BASE
        for entity in members:
            h = _box_height(entity)
            positions[entity.name] = (_COLUMN_X[col], y, _BOX_WIDTH, h)
            y += h + _ROW_GAP
    return positions


def _entity_text(entity: Entity) -> str:
    """Plain-text body that Lucid's draw.io importer accepts without HTML quirks."""
    lines: list[str] = []
    lines.append(entity.name)
    lines.append("-" * len(entity.name))
    lines.append(f"owner: {entity.owner}")
    lines.append(f"role : {entity.aggregate_role}")
    lines.append(f"store: {entity.persistence_tag}")
    lines.append("")
    for attr in entity.attributes:
        marker = "PK" if attr.pk else ("FK" if attr.fk else "  ")
        opt = "" if attr.required else "  (opt)"
        lines.append(f"{marker} {attr.name} : {attr.type_name}{opt}")
    return "\n".join(lines)


def _drawio_entity_xml(entity: Entity, x: int, y: int, w: int, h: int) -> str:
    fill, stroke = _AGG_COLORS.get(entity.aggregate_role, ("#ffffff", "#000000"))
    # Plain text in `value`; html=0; whiteSpace=wrap with newlines preserved.
    value = xml_escape(_entity_text(entity), entities={'"': "&quot;", "\n": "&#10;"})
    style = (
        f"rounded=0;whiteSpace=wrap;html=0;align=left;verticalAlign=top;"
        f"fillColor={fill};strokeColor={stroke};fontSize=11;fontFamily=Courier New;"
        f"spacingLeft=8;spacingRight=8;spacingTop=6;spacingBottom=6;"
    )
    return (
        f'        <mxCell id="ent-{entity.name}" value="{value}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        f'        </mxCell>'
    )


def _drawio_edge_xml(idx: int, rel: Relationship) -> str:
    cardinality_to_arrows = {
        "||--o{": ("ERone", "ERmany"),
        "||--||": ("ERone", "ERone"),
        "||--o|": ("ERone", "ERzeroToOne"),
        "}o--o{": ("ERmany", "ERmany"),
    }
    start, end = cardinality_to_arrows.get(rel.cardinality, ("ERone", "ERmany"))
    # Use orthogonalEdgeStyle which Lucid recognises; drop entityRelationEdgeStyle.
    style = (
        f"endArrow={end};startArrow={start};html=0;rounded=0;"
        f"edgeStyle=orthogonalEdgeStyle;strokeColor=#444444;"
    )
    label = xml_escape(rel.label, entities={'"': "&quot;"})
    return (
        f'        <mxCell id="edge-{idx}" value="{label}" style="{style}" '
        f'edge="1" parent="1" source="ent-{rel.source}" target="ent-{rel.target}">\n'
        f'          <mxGeometry relative="1" as="geometry"/>\n'
        f'        </mxCell>'
    )


def render_drawio() -> str:
    positions = _layout_positions()
    cells: list[str] = []
    for entity in ENTITIES:
        x, y, w, h = positions[entity.name]
        cells.append(_drawio_entity_xml(entity, x, y, w, h))
    for idx, rel in enumerate(RELATIONSHIPS, start=1):
        cells.append(_drawio_edge_xml(idx, rel))
    body = "\n".join(cells)

    max_x = max(p[0] + p[2] for p in positions.values()) + 80
    max_y = max(p[1] + p[3] for p in positions.values()) + 80

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" modified="2026-04-28T00:00:00.000Z" '
        'agent="ak3-diagram-export" version="22.1.16" type="device">\n'
        '  <diagram id="ak3-data-model" name="AK3 Fachliches Datenmodell">\n'
        f'    <mxGraphModel dx="{max_x}" dy="{max_y}" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{max_x}" pageHeight="{max_y}" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f'{body}\n'
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )


__all__ = [
    "Attribute",
    "ENTITIES",
    "Entity",
    "RELATIONSHIPS",
    "Relationship",
    "render_drawio",
    "render_mermaid",
]
