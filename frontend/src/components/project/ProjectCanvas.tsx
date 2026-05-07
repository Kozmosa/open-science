import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
  applyEdgeChanges,
} from '@xyflow/react';
import { Button } from '../ui';
import { useT } from '../../i18n';
import type { TaskEdge, TaskSummary } from '../../types';
import TaskNode from './TaskNode';
import { layoutDagre } from './layoutDagre';

const nodeTypes = { taskNode: TaskNode };
const LAYOUT_KEY = (projectId: string) => `ainrf:project-layout:${projectId}`;

interface CanvasInnerProps {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  onNodeClick: (taskId: string) => void;
}

function CanvasInner({ projectId, tasks, edges, onNodeClick }: CanvasInnerProps) {
  const { getNodes, fitView } = useReactFlow();
  const initialNodes: Node[] = useMemo(
    () =>
      tasks.map((task) => ({
        id: task.task_id,
        type: 'taskNode',
        position: { x: 0, y: 0 },
        data: { task },
      })),
    [tasks]
  );
  const initialEdges: Edge[] = useMemo(
    () =>
      edges.map((edge) => ({
        id: edge.edge_id,
        source: edge.source_task_id,
        target: edge.target_task_id,
        type: 'default',
        markerEnd: { type: 'arrowclosed' as const, width: 12, height: 12 },
      })),
    [edges]
  );

  const [nodes, setLocalNodes] = useState<Node[]>(initialNodes);
  const [flowEdges, setFlowEdges] = useState<Edge[]>(initialEdges);

  const runLayout = useCallback(() => {
    const saved = localStorage.getItem(LAYOUT_KEY(projectId));
    if (saved) {
      try {
        const positions: Record<string, { x: number; y: number }> = JSON.parse(saved);
        setLocalNodes(
          initialNodes.map((n) =>
            positions[n.id] ? { ...n, position: positions[n.id] } : n
          )
        );
        return;
      } catch {
        // fall through to dagre layout
      }
    }
    const laidOut = layoutDagre(initialNodes, initialEdges);
    setLocalNodes(laidOut);
  }, [projectId, initialNodes, initialEdges]);

  useEffect(() => {
    runLayout();
    setFlowEdges(initialEdges);
    const timeoutId = setTimeout(() => fitView({ padding: 0.2 }), 50);
    return () => clearTimeout(timeoutId);
  }, [runLayout, initialEdges, fitView]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setLocalNodes((current) => applyNodeChanges(changes, current));
    },
    []
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setFlowEdges((current) => applyEdgeChanges(changes, current));
    },
    []
  );

  const onNodeDragStop = useCallback(() => {
    const current = getNodes();
    const positions: Record<string, { x: number; y: number }> = {};
    for (const n of current) {
      positions[n.id] = n.position;
    }
    try {
      localStorage.setItem(LAYOUT_KEY(projectId), JSON.stringify(positions));
    } catch {
      // ignore storage errors
    }
  }, [getNodes, projectId]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onNodeClick(node.id);
    },
    [onNodeClick]
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={handleNodeClick}
      attributionPosition="bottom-right"
    >
      <Background gap={16} size={1} color="var(--border)" />
      <Controls />
      <MiniMap
        nodeColor={() => 'var(--apple-blue)'}
        maskColor="rgba(0,0,0,0.1)"
        className="rounded-lg"
      />
    </ReactFlow>
  );
}

interface Props {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  onNodeClick: (taskId: string) => void;
  onNewTask: () => void;
  onResetLayout: () => void;
}

export default function ProjectCanvas({
  projectId,
  tasks,
  edges,
  onNodeClick,
  onNewTask,
  onResetLayout,
}: Props) {
  const t = useT();

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <div className="flex gap-2">
          <Button onClick={onNewTask} className="h-8 gap-1.5 px-3 text-xs">
            <Plus size={14} />
            {t('pages.projects.newTask')}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              localStorage.removeItem(LAYOUT_KEY(projectId));
              onResetLayout();
            }}
            className="h-8 px-3 text-xs"
          >
            {t('pages.projects.resetLayout')}
          </Button>
        </div>
      </div>
      <div className="flex-1">
        {tasks.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
            {t('pages.projects.emptyCanvas')}
          </div>
        ) : (
          <ReactFlowProvider>
            <CanvasInner
              projectId={projectId}
              tasks={tasks}
              edges={edges}
              onNodeClick={onNodeClick}
            />
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}
