import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type EdgeTypes,
  type Node,
  type NodeProps,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react';
import type { Story } from '../../store';
import { FastBadge } from '../../components/FastBadge';
import { Badge } from '../../design_system/Badge';

const statusClass: Record<Story['status'], string> = {
  Backlog: 'status-backlog',
  Approved: 'status-approved',
  'In Progress': 'status-progress',
  Done: 'success',
  Cancelled: 'cancelled',
};

export function StoryNode({ data, selected }: NodeProps) {
  const story = data as unknown as Story & { dependencyHighlight?: boolean; visualState?: string };
  const statusSlug = story.status.toLowerCase().replaceAll(' ', '-');
  return (
    <button
      className={[
        'story-node',
        `status-${statusSlug}`,
        story.visualState ? `visual-${story.visualState}` : '',
        selected ? 'is-selected' : '',
        story.dependencyHighlight ? 'is-highlighted' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-story-interactive="true"
      type="button"
    >
      <Handle className="node-handle" type="target" position={Position.Left} />
      <div className="node-topline">
        <span className="node-id">
          {story.id}
          <FastBadge mode={story.mode} />
        </span>
        <Badge tone={statusClass[story.status]}>{story.status}</Badge>
      </div>
      <div className="node-title">{story.title}</div>
      <div className="node-meta">
        <span>{story.type}</span>
        <span>{story.size}</span>
        <span>Wave {story.wave}</span>
      </div>
      {story.blocker && <div className="node-blocker">{story.blocker}</div>}
      <Handle className="node-handle" type="source" position={Position.Right} />
    </button>
  );
}

export function DependencyEdge(props: EdgeProps) {
  const [path] = getBezierPath(props);
  const data = props.data as { open?: boolean; blockingHighlight?: boolean } | undefined;
  const className = [
    'dependency-edge',
    data?.open ? 'is-open' : '',
    data?.blockingHighlight ? 'is-blocking-highlight' : '',
  ]
    .filter(Boolean)
    .join(' ');
  return <BaseEdge path={path} className={className} />;
}

export const nodeTypes: NodeTypes = { story: StoryNode };
export const edgeTypes: EdgeTypes = { dependency: DependencyEdge };

export function GraphView({
  nodes,
  edges,
  onNodeClick,
  onNodesChange,
  onEdgesChange,
}: {
  nodes: Node[];
  edges: Edge[];
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodesChange: OnNodesChange<Node>;
  onEdgesChange: OnEdgesChange<Edge>;
}) {
  return (
    <div className="graph-shell">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.35}
        maxZoom={1.8}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} />
        <Controls />
        <MiniMap pannable zoomable nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
