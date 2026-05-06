import type { Edge, Node } from '@xyflow/react';
import type { Story } from './data';

const NODE_WIDTH_REM = 15.25;
const NODE_HEIGHT_REM = 8.75;
const MIN_NODE_GAP_REM = 1;
const LAYER_GAP_REM = 9.75;
const GRAPH_PADDING_REM = 1.25;
const ORDERING_PASSES = 8;
const COMPACTION_PASSES = 12;

type NodeVisualState = 'done' | 'blocked' | 'active' | 'terminal-muted' | 'waiting';

function rem(value: number): number {
  if (typeof window === 'undefined') return value * 16;
  const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  return value * (Number.isFinite(rootFontSize) ? rootFontSize : 16);
}

function getVisualState(story: Story, byId: Map<string, Story>): NodeVisualState {
  if (story.status === 'Done') return 'done';
  if (story.status === 'Cancelled') return 'terminal-muted';
  const hasOpenDependency = story.dependencies.some((dependency) => byId.get(dependency)?.status !== 'Done');
  if (story.blocker || ((story.status === 'Approved' || story.status === 'In Progress') && hasOpenDependency)) return 'blocked';
  if (story.status === 'Approved' || story.status === 'In Progress') return 'active';
  return 'waiting';
}

function collectDependencyPathIds(story: Story | undefined, byId: Map<string, Story>): Set<string> {
  const pathIds = new Set<string>();
  const visit = (storyId: string) => {
    if (pathIds.has(storyId)) return;
    const current = byId.get(storyId);
    if (!current) return;
    pathIds.add(storyId);
    for (const dependency of current.dependencies) {
      visit(dependency);
    }
  };

  if (story) {
    pathIds.add(story.id);
    for (const dependency of story.dependencies) {
      visit(dependency);
    }
  }

  return pathIds;
}

export function toGraph(stories: Story[], selectedStoryId: string | null = null): { nodes: Node[]; edges: Edge[] } {
  const byId = new Map(stories.map((story) => [story.id, story]));
  const selectedStory = selectedStoryId ? byId.get(selectedStoryId) : undefined;
  const dependencyPathIds = collectDependencyPathIds(selectedStory, byId);

  const nodes: Node[] = stories.map((story) => ({
    id: story.id,
    type: 'story',
    position: { x: 0, y: 0 },
    data: {
      ...story,
      dependencyHighlight: dependencyPathIds.has(story.id),
      visualState: getVisualState(story, byId),
    } as unknown as Record<string, unknown>,
  }));

  const edges: Edge[] = stories.flatMap((story) =>
    story.dependencies.map((source) => {
      const sourceStory = byId.get(source);
      return {
        id: `${source}-${story.id}`,
        source,
        target: story.id,
        type: 'dependency',
        data: {
          open: story.status !== 'Done',
          blockingHighlight: dependencyPathIds.has(story.id) && dependencyPathIds.has(source) && sourceStory?.status !== 'Done',
        },
      };
    }),
  );

  return { nodes, edges };
}

function average(values: number[]): number | undefined {
  if (!values.length) return undefined;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function knownValues(ids: string[], values: Map<string, number>): number[] {
  return ids.flatMap((id) => {
    const value = values.get(id);
    return value === undefined ? [] : [value];
  });
}

function sortByBarycenter(
  layer: string[],
  related: Map<string, string[]>,
  relatedPosition: Map<string, number>,
  fallbackOrder: Map<string, number>,
): string[] {
  return [...layer].sort((a, b) => {
    const aCenter = average(knownValues(related.get(a) ?? [], relatedPosition));
    const bCenter = average(knownValues(related.get(b) ?? [], relatedPosition));
    if (aCenter !== undefined && bCenter !== undefined && aCenter !== bCenter) return aCenter - bCenter;
    if (aCenter !== undefined && bCenter === undefined) return -1;
    if (aCenter === undefined && bCenter !== undefined) return 1;
    return (fallbackOrder.get(a) ?? 0) - (fallbackOrder.get(b) ?? 0);
  });
}

function packLayer(layer: string[], yById: Map<string, number>, desiredById: Map<string, number>, rowGap: number): void {
  if (!layer.length) return;

  let cursor = Number.NEGATIVE_INFINITY;
  for (const id of layer) {
    const desired = desiredById.get(id) ?? yById.get(id) ?? 0;
    const y = Math.max(desired, cursor);
    yById.set(id, y);
    cursor = y + rowGap;
  }

  const desiredAverage = average(layer.map((id) => desiredById.get(id) ?? yById.get(id) ?? 0));
  const actualAverage = average(layer.map((id) => yById.get(id) ?? 0));
  if (desiredAverage === undefined || actualAverage === undefined) return;

  const shift = desiredAverage - actualAverage;
  for (const id of layer) {
    yById.set(id, (yById.get(id) ?? 0) + shift);
  }

  cursor = Number.NEGATIVE_INFINITY;
  for (const id of layer) {
    const y = Math.max(yById.get(id) ?? 0, cursor);
    yById.set(id, y);
    cursor = y + rowGap;
  }
}

export async function layoutGraph(nodes: Node[], edges: Edge[]): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const nodeWidth = rem(NODE_WIDTH_REM);
  const nodeHeight = rem(NODE_HEIGHT_REM);
  const rowGap = nodeHeight + rem(MIN_NODE_GAP_REM);
  const columnGap = nodeWidth + rem(LAYER_GAP_REM);
  const padding = rem(GRAPH_PADDING_REM);
  const ids = nodes.map((node) => node.id);
  const nodeSet = new Set(ids);
  const originalOrder = new Map(ids.map((id, index) => [id, index]));
  const predecessors = new Map(ids.map((id) => [id, [] as string[]]));
  const successors = new Map(ids.map((id) => [id, [] as string[]]));
  const indegree = new Map(ids.map((id) => [id, 0]));

  for (const edge of edges) {
    if (!nodeSet.has(edge.source) || !nodeSet.has(edge.target)) continue;
    predecessors.get(edge.target)?.push(edge.source);
    successors.get(edge.source)?.push(edge.target);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  }

  const layerById = new Map(ids.map((id) => [id, 0]));
  const queue = ids.filter((id) => (indegree.get(id) ?? 0) === 0);
  const visited = new Set<string>();

  while (queue.length) {
    queue.sort((a, b) => (originalOrder.get(a) ?? 0) - (originalOrder.get(b) ?? 0));
    const id = queue.shift();
    if (!id) break;
    visited.add(id);
    for (const target of successors.get(id) ?? []) {
      layerById.set(target, Math.max(layerById.get(target) ?? 0, (layerById.get(id) ?? 0) + 1));
      indegree.set(target, (indegree.get(target) ?? 0) - 1);
      if (indegree.get(target) === 0) queue.push(target);
    }
  }

  for (const id of ids) {
    if (!visited.has(id)) {
      const fallbackLayer = Math.max(0, ...(predecessors.get(id) ?? []).map((source) => (layerById.get(source) ?? 0) + 1));
      layerById.set(id, fallbackLayer);
    }
  }

  const maxLayer = Math.max(0, ...Array.from(layerById.values()));
  const layers = Array.from({ length: maxLayer + 1 }, () => [] as string[]);
  for (const id of ids) {
    layers[layerById.get(id) ?? 0].push(id);
  }

  for (const layer of layers) {
    layer.sort((a, b) => (originalOrder.get(a) ?? 0) - (originalOrder.get(b) ?? 0));
  }

  for (let pass = 0; pass < ORDERING_PASSES; pass += 1) {
    for (let layerIndex = 1; layerIndex < layers.length; layerIndex += 1) {
      const previousPositions = new Map(layers[layerIndex - 1].map((id, index) => [id, index]));
      layers[layerIndex] = sortByBarycenter(layers[layerIndex], predecessors, previousPositions, originalOrder);
    }
    for (let layerIndex = layers.length - 2; layerIndex >= 0; layerIndex -= 1) {
      const nextPositions = new Map(layers[layerIndex + 1].map((id, index) => [id, index]));
      layers[layerIndex] = sortByBarycenter(layers[layerIndex], successors, nextPositions, originalOrder);
    }
  }

  const yById = new Map<string, number>();
  for (const layer of layers) {
    layer.forEach((id, index) => yById.set(id, index * rowGap));
  }

  for (let pass = 0; pass < COMPACTION_PASSES; pass += 1) {
    for (let layerIndex = 1; layerIndex < layers.length; layerIndex += 1) {
      const desiredById = new Map<string, number>();
      for (const id of layers[layerIndex]) {
        const predecessorY = average(knownValues(predecessors.get(id) ?? [], yById));
        if (predecessorY !== undefined) desiredById.set(id, predecessorY);
      }
      packLayer(layers[layerIndex], yById, desiredById, rowGap);
    }

    for (let layerIndex = layers.length - 2; layerIndex >= 0; layerIndex -= 1) {
      const desiredById = new Map<string, number>();
      for (const id of layers[layerIndex]) {
        const successorY = average(knownValues(successors.get(id) ?? [], yById));
        if (successorY !== undefined) desiredById.set(id, successorY);
      }
      packLayer(layers[layerIndex], yById, desiredById, rowGap);
    }
  }

  const minY = Math.min(0, ...Array.from(yById.values()));
  const positionedNodes = nodes.map((node) => ({
    ...node,
    position: {
      x: padding + (layerById.get(node.id) ?? 0) * columnGap,
      y: padding + (yById.get(node.id) ?? 0) - minY,
    },
  }));

  return { nodes: positionedNodes, edges };
}
