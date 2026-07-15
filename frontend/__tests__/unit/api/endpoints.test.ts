import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetMockEnvironmentState, resetMockTaskState, resetMockTerminalSession } from '@/shared/api/mock';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetMockTerminalSession();
  resetMockEnvironmentState();
  resetMockTaskState();
});

describe('api endpoints', () => {
  it('uses the mock transport only when VITE_USE_MOCK is true', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true');

    const {
      buildTaskStreamUrl,
      createTask,
      getTask,
      getTaskOutput,
      getTasks,
      getTerminalSession,
      getWorkspaces,
    } = await import('../../../src/shared/api/endpoints');

    const session = await getTerminalSession('env-localhost');
    const workspaces = await getWorkspaces();
    const created = await createTask({
      workspace_id: 'workspace-default',
      environment_id: 'env-localhost',
      task_profile: 'claude-code',
      task_input: 'Implement harness',
    }, 'task.create:test');
    const tasks = await getTasks();
    const detail = await getTask(created.task_id);
    const output = await getTaskOutput(created.task_id);

    expect(session.status).toBe('idle');
    expect(workspaces.items[0]?.workspace_id).toBe('workspace-default');
    expect(created.status).toBe('queued');
    expect(tasks.items[0]?.task_id).toBe(created.task_id);
    expect(detail.binding?.resolved_workdir).toBeTruthy();
    expect(output.items[0]?.kind).toBe('lifecycle');
    expect(buildTaskStreamUrl(created.task_id, 3)).toContain(`/api/tasks/${created.task_id}/stream`);
  });

  it('uses a query parameter for task stream API keys because EventSource cannot send custom headers', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    vi.stubEnv('VITE_AINRF_API_KEY', 'stream-secret');

    const { buildTaskStreamUrl } = await import('../../../src/shared/api/endpoints');

    expect(buildTaskStreamUrl('task-1', 7)).toBe(
      '/api/tasks/task-1/stream?after_seq=7&api_key=stream-secret'
    );
  });

  it('sends stable idempotency keys for Task pause, resume, and continuation', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ task_id: 'task-1', status: 'running', sequence: 1 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ));
    vi.stubGlobal('fetch', fetchMock);

    const { pauseTask, resumeTask, sendTaskPrompt } = await import('../../../src/shared/api/endpoints');
    await pauseTask('task-1', 'task.pause:test');
    await resumeTask('task-1', 'task.resume:test');
    await sendTaskPrompt('task-1', 'Continue the analysis', 'task.continue:test');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks/task-1/pause',
      '/api/tasks/task-1/resume',
      '/api/tasks/task-1/continue',
    ]);
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('task.pause:test');
    expect((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('task.resume:test');
    expect((fetchMock.mock.calls[2]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('task.continue:test');
  });

  it('uses the real api client when VITE_USE_MOCK is false', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { getHealth } = await import('../../../src/shared/api/endpoints');
    await expect(getHealth()).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.any(Object));
  });

  it('sends workspace CRUD requests through the real api client', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspace_id: 'workspace-new',
            label: 'New workspace',
            description: null,
            default_workdir: '/workspace/new',
            workspace_prompt: 'Prompt',
            created_at: '2026-04-27T00:00:00Z',
            updated_at: '2026-04-27T00:00:00Z',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspace_id: 'workspace-new',
            label: 'Updated workspace',
            description: 'Updated',
            default_workdir: '/workspace/updated',
            workspace_prompt: 'Updated prompt',
            created_at: '2026-04-27T00:00:00Z',
            updated_at: '2026-04-27T00:01:00Z',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        )
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    const { createWorkspace, updateWorkspace, deleteWorkspace } = await import('../../../src/shared/api/endpoints');

    await createWorkspace({
      label: 'New workspace',
      description: null,
      default_workdir: '/workspace/new',
      workspace_prompt: 'Prompt',
    });
    await updateWorkspace('workspace-new', {
      label: 'Updated workspace',
      description: 'Updated',
      default_workdir: '/workspace/updated',
      workspace_prompt: 'Updated prompt',
    }, 'workspace.update:test');
    await deleteWorkspace('workspace-new');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/workspaces',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          label: 'New workspace',
          description: null,
          default_workdir: '/workspace/new',
          workspace_prompt: 'Prompt',
        }),
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/workspaces/workspace-new',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          label: 'Updated workspace',
          description: 'Updated',
          default_workdir: '/workspace/updated',
          workspace_prompt: 'Updated prompt',
        }),
      })
    );
    expect((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('workspace.update:test');
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/workspaces/workspace-new',
      expect.objectContaining({ method: 'DELETE' })
    );
  });
});
