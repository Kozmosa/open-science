import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProjectCanvas } from '@features/projects';
import { createTaskEdge, deleteTaskEdge } from '@features/tasks';
import type { TaskSummary, TaskEdge } from '@/shared/types';

const mockFitView = vi.fn();
const mockGetNodes = vi.fn(() => []);

// Mock React Flow sub-components that depend on browser APIs not available in jsdom
vi.mock('@features/tasks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/tasks')>();
  return {
    ...actual,
    createTaskEdge: vi.fn(),
    deleteTaskEdge: vi.fn(),
  };
});

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children, nodes, edges, onConnect, onEdgesDelete }: {
    children?: React.ReactNode;
    nodes?: unknown[];
    edges?: Array<{ id: string; source: string; target: string }>;
    onConnect?: (connection: { source: string; target: string }) => void;
    onEdgesDelete?: (edges: Array<{ id: string; source: string; target: string }>) => void;
  }) => (
    <div data-testid="react-flow">
      {nodes ? <div data-testid="node-count">{nodes.length}</div> : null}
      {edges ? <div data-testid="edge-count">{edges.length}</div> : null}
      <button type="button" onClick={() => onConnect?.({ source: 't1', target: 't2' })}>
        Connect tasks
      </button>
      <button type="button" onClick={() => edges?.[0] && onEdgesDelete?.([edges[0]])}>
        Delete first edge
      </button>
      {children}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Background: () => <div data-testid="background" />,
  Controls: () => <div data-testid="controls" />,
  MiniMap: () => <div data-testid="minimap" />,
  useReactFlow: () => ({
    getNodes: mockGetNodes,
    fitView: mockFitView,
  }),
  addEdge: (edge: unknown, edges: unknown[]) => [...edges, edge],
  applyNodeChanges: (_changes: unknown[], nodes: unknown[]) => nodes,
  applyEdgeChanges: (_changes: unknown[], edges: unknown[]) => edges,
}));

const mockTasks: TaskSummary[] = [
  {
    task_id: 't1',
    project_id: 'p1',
    title: 'Task One',
    task_profile: 'claude-code',
    status: 'running',
    workspace_summary: { workspace_id: 'w1', label: 'WS1', description: null, default_workdir: null },
    environment_summary: { environment_id: 'e1', alias: 'env1', display_name: 'Env One', host: 'localhost', default_workdir: null },
    created_at: '2026-05-08T10:00:00Z',
    updated_at: '2026-05-08T10:00:00Z',
    started_at: null,
    completed_at: null,
    error_summary: null,
    latest_output_seq: 0,
  },
];

const multiMockTasks: TaskSummary[] = [
  {
    task_id: 't2',
    project_id: 'p1',
    title: 'Task Two',
    task_profile: 'claude-code',
    status: 'succeeded',
    workspace_summary: { workspace_id: 'w1', label: 'WS1', description: null, default_workdir: null },
    environment_summary: { environment_id: 'e1', alias: 'env1', display_name: 'Env One', host: 'localhost', default_workdir: null },
    created_at: '2026-05-08T10:05:00Z',
    updated_at: '2026-05-08T10:05:00Z',
    started_at: null,
    completed_at: null,
    error_summary: null,
    latest_output_seq: 0,
  },
  {
    task_id: 't1',
    project_id: 'p1',
    title: 'Task One',
    task_profile: 'claude-code',
    status: 'running',
    workspace_summary: { workspace_id: 'w1', label: 'WS1', description: null, default_workdir: null },
    environment_summary: { environment_id: 'e1', alias: 'env1', display_name: 'Env One', host: 'localhost', default_workdir: null },
    created_at: '2026-05-08T10:00:00Z',
    updated_at: '2026-05-08T10:00:00Z',
    started_at: null,
    completed_at: null,
    error_summary: null,
    latest_output_seq: 0,
  },
  {
    task_id: 't3',
    project_id: 'p1',
    title: 'Task Three',
    task_profile: 'claude-code',
    status: 'queued',
    workspace_summary: { workspace_id: 'w1', label: 'WS1', description: null, default_workdir: null },
    environment_summary: { environment_id: 'e1', alias: 'env1', display_name: 'Env One', host: 'localhost', default_workdir: null },
    created_at: '2026-05-08T10:10:00Z',
    updated_at: '2026-05-08T10:10:00Z',
    started_at: null,
    completed_at: null,
    error_summary: null,
    latest_output_seq: 0,
  },
];

const mockEdges: TaskEdge[] = [];
const mockCreateTaskEdge = vi.mocked(createTaskEdge);
const mockDeleteTaskEdge = vi.mocked(deleteTaskEdge);

describe('ProjectCanvas', () => {
  it('renders empty canvas placeholder when no tasks', () => {
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={[]}
        edges={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
        canCreateTask={false}
        canEditRelationships={false}
        canMoveTask={() => false}
      />
    );

    expect(screen.getByText("Click 'New Task' to get started")).toBeInTheDocument();
  });

  it('renders nodes when tasks are provided', () => {
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={mockTasks}
        edges={mockEdges}
        projects={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
        onMoveTaskToProject={vi.fn()}
        canCreateTask
        canEditRelationships
        canMoveTask={() => true}
      />
    );

    expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    expect(screen.getByTestId('node-count')).toHaveTextContent('1');
  });

  it('calls onNewTask when New Task button is clicked', () => {
    const onNewTask = vi.fn();
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={mockTasks}
        edges={mockEdges}
        projects={[]}
        onNodeClick={vi.fn()}
        onNewTask={onNewTask}
        onResetLayout={vi.fn()}
        onMoveTaskToProject={vi.fn()}
        canCreateTask
        canEditRelationships
        canMoveTask={() => true}
      />
    );

    const newTaskButton = screen.getByText('New Task');
    newTaskButton.click();
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });

  it('does not auto-connect tasks when no explicit edges exist', () => {
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={multiMockTasks}
        edges={[]}
        projects={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
        onMoveTaskToProject={vi.fn()}
        canCreateTask
        canEditRelationships
        canMoveTask={() => true}
      />
    );

    // With auto-connect removed, only manually-created edges appear.
    expect(screen.getByTestId('edge-count')).toHaveTextContent('0');
  });

  it('uses explicit edges instead of auto-connect when edges are provided', () => {
    const explicitEdges: TaskEdge[] = [
      {
        edge_id: 'e1',
        project_id: 'p1',
        source_task_id: 't3',
        target_task_id: 't1',
        created_at: '2026-05-08T10:00:00Z',
      },
    ];
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={multiMockTasks}
        edges={explicitEdges}
        projects={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
        onMoveTaskToProject={vi.fn()}
        canCreateTask
        canEditRelationships
        canMoveTask={() => true}
      />
    );

    expect(screen.getByTestId('edge-count')).toHaveTextContent('1');
  });

  it('replaces a temporary relationship ID and deletes through the canonical interface', async () => {
    const user = userEvent.setup();
    const explicitTasks = multiMockTasks.slice(0, 2);
    mockCreateTaskEdge.mockResolvedValue({
      edge_id: 'relationship-1',
      project_id: 'p1',
      source_task_id: 't1',
      target_task_id: 't2',
      relationship_type: 'related_to',
      created_at: '2026-05-08T10:00:00Z',
    });
    mockDeleteTaskEdge.mockResolvedValue();

    render(
      <ProjectCanvas
        projectId="p1"
        tasks={explicitTasks}
        edges={[]}
        projects={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
        onMoveTaskToProject={vi.fn()}
        canCreateTask
        canEditRelationships
        canMoveTask={() => true}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Connect tasks' }));
    await waitFor(() => expect(screen.getByTestId('edge-count')).toHaveTextContent('1'));
    await waitFor(() => expect(mockCreateTaskEdge).toHaveBeenCalledWith(
      'p1',
      { source_task_id: 't1', target_task_id: 't2' },
      expect.stringMatching(/^task\.relationship/),
    ));

    await user.click(screen.getByRole('button', { name: 'Delete first edge' }));
    await waitFor(() => expect(mockDeleteTaskEdge).toHaveBeenCalledWith(
      'p1',
      'relationship-1',
      expect.stringMatching(/^task\.relationship\.delete/),
    ));
  });
});
