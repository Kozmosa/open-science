import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
  applyEdgeChanges,
} from '@xyflow/react';
import { Button } from '../ui';
import { useT } from '@/shared/i18n';
import { createTaskEdge } from '@/shared/api';
import type { ProjectRecord, TaskEdge, TaskSummary } from '@/shared/types';
import TaskNode from './TaskNode';
import ProjectDropZone from './ProjectDropZone';
import { layoutDagre } from './layoutDagre';

const nodeTypes = { taskNode: TaskNode };
const LAYOUT_KEY = (projectId: string) => `ainrf:project-layout:${projectId}`;

interface CanvasInnerProps {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  projects: ProjectRecord[];
  onNodeClick: (taskId: string) => void;
  onMoveTaskToProject: (taskId: string, projectId: string) => void;
}
function CanvasInner({ projectId, tasks, edges, projects, onNodeClick, onMoveTaskToProject }: CanvasInnerProps) {
  const { getNodes, fitView } = useReactFlow();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dropZoneVisible, setDropZoneVisible] = useState(false);
  const draggingNodeId = useRef<string | null>(null);
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
  const initialEdges: Edge[] = useMemo(() => {
    if (edges.length === 0) return [];
    const visibleIds = new Set(tasks.map((t) => t.task_id));
    return edges
      .filter((e) => visibleIds.has(e.source_task_id) && visibleIds.has(e.target_task_id))
      .map((edge) => ({
        id: edge.edge_id,
        source: edge.source_task_id,
        target: edge.target_task_id,
        type: 'default',
        markerEnd: { type: 'arrowclosed' as const, width: 12, height: 12 },
      }));
  }, [edges, tasks]);

  // Sync layout on mount so nodes don't stack at (0, 0) on first render
  const [nodes, setLocalNodes] = useState<Node[]>(() => {
    const saved = localStorage.getItem(LAYOUT_KEY(projectId));
    if (saved) {
      try {
        const positions: Record<string, { x: number; y: number }> = JSON.parse(saved);
        return initialNodes.map((n) =>
          positions[n.id] ? { ...n, position: positions[n.id] } : n
        );
      } catch {
        // fall through to dagre layout
      }
    }
    return layoutDagre(initialNodes, initialEdges);
  });
  const [flowEdges, setFlowEdges] = useState<Edge[]>(initialEdges);
  const manualEdgeIds = useRef<Set<string>>(new Set());

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
    // Layout initializes or restores nodes; suppress the rule because this is
    // intentionally synchronizing React Flow state after the tasks/edges change.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    runLayout();
    // Preserve manually-added edges that aren't yet in the backend set
    setFlowEdges((current) => {
      const initialIds = new Set(initialEdges.map((e) => e.id));
      const manualEdges = current.filter(
        (e) => manualEdgeIds.current.has(e.id) && !initialIds.has(e.id)
      );
      // Merge: backend edges first, then manual edges on top
      return [...initialEdges, ...manualEdges];
    });
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

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const edgeId = `edge_${connection.source}_${connection.target}`;
      manualEdgeIds.current.add(edgeId);
      setFlowEdges((current) =>
        addEdge(
          {
            ...connection,
            id: edgeId,
            type: 'smoothstep',
            animated: true,
            style: { stroke: 'var(--apple-blue)', strokeWidth: 2 },
          },
          current,
        ),
      );
      createTaskEdge(projectId, {
        source_task_id: connection.source,
        target_task_id: connection.target,
      }).catch(() => {
        manualEdgeIds.current.delete(edgeId);
        setFlowEdges((current) => current.filter((e) => e.id !== edgeId));
      });
    },
    [projectId]
  );

  const onNodeDrag = useCallback(
    (event: React.MouseEvent, node: Node) => {
      draggingNodeId.current = node.id;
      const rect = containerRef.current?.getBoundingClientRect();
      const relX = rect ? event.clientX - rect.left : event.clientX;
      setDropZoneVisible(relX < 96);
    },
    []
  );

  const onNodeDragStop = useCallback(
    (event: React.MouseEvent, node: Node) => {
      // Hit-test drop-zone cards (tagged with data-project-id) under the pointer.
      const els = document.elementsFromPoint(event.clientX, event.clientY);
      const card = els.find(
        (el): el is HTMLElement =>
          el instanceof HTMLElement && Boolean(el.dataset.projectId)
      );
      const targetProjectId = card?.dataset.projectId;
      if (targetProjectId && targetProjectId !== projectId) {
        onMoveTaskToProject(node.id, targetProjectId);
      } else {
        // No project drop — persist node positions as before.
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
      }
      draggingNodeId.current = null;
      setDropZoneVisible(false);
    },
    [getNodes, projectId, onMoveTaskToProject]
  );

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onNodeClick(node.id);
    },
    [onNodeClick]
  );

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
        onNodeClick={handleNodeClick}
        onConnect={onConnect}
        connectionLineStyle={{ stroke: 'var(--apple-blue)', strokeWidth: 2 }}
        defaultEdgeOptions={{
          type: 'smoothstep',
          animated: true,
          style: { stroke: 'var(--apple-blue)', strokeWidth: 2 },
        }}
        attributionPosition="bottom-right"
      >
        <Background gap={16} size={1} color="var(--border)" />
        <Controls />
        <MiniMap
          nodeColor={() => 'var(--apple-blue)'}
          maskColor="rgba(0,0,0,0.1)"
          className="rounded-lg"
          pannable
          zoomable
        />
      </ReactFlow>
      <ProjectDropZone
        projects={projects}
        visible={dropZoneVisible}
        currentProjectId={projectId}
      />
    </div>
  );
}

interface Props {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  projects: ProjectRecord[];
  onNodeClick: (taskId: string) => void;
  onNewTask: () => void;
  onResetLayout: () => void;
  onMoveTaskToProject: (taskId: string, projectId: string) => void;
}

export default function ProjectCanvas({
  projectId,
  tasks,
  edges,
  projects,
  onNodeClick,
  onNewTask,
  onResetLayout,
  onMoveTaskToProject,
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
      <div className="flex-1 min-h-0">
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
              projects={projects}
              onNodeClick={onNodeClick}
              onMoveTaskToProject={onMoveTaskToProject}
            />
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}
