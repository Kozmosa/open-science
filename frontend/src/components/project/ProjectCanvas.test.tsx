import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProjectCanvas from './ProjectCanvas';
import type { TaskSummary, TaskEdge } from '../../types';

const mockFitView = vi.fn();
const mockGetNodes = vi.fn(() => []);

// Mock React Flow sub-components that depend on browser APIs not available in jsdom
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children, nodes }: { children?: React.ReactNode; nodes?: unknown[] }) => (
    <div data-testid="react-flow">
      {nodes ? <div data-testid="node-count">{nodes.length}</div> : null}
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
  applyNodeChanges: (_changes: unknown[], nodes: unknown[]) => nodes,
  applyEdgeChanges: (_changes: unknown[], edges: unknown[]) => edges,
}));

const mockTasks: TaskSummary[] = [
  {
    task_id: 't1',
    title: 'Task One',
    status: 'running',
    created_at: '2026-05-08T10:00:00Z',
    updated_at: '2026-05-08T10:00:00Z',
    workspace_summary: { workspace_id: 'w1', label: 'WS1' },
    environment_summary: { id: 'e1', alias: 'env1', display_name: 'Env One' },
  },
];

const mockEdges: TaskEdge[] = [];

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
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
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
        onNodeClick={vi.fn()}
        onNewTask={onNewTask}
        onResetLayout={vi.fn()}
      />
    );

    const newTaskButton = screen.getByText('New Task');
    newTaskButton.click();
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });
});
