import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetMockEnvironmentState, resetMockTaskState, resetMockTerminalSession } from './mock';

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
    } = await import('./endpoints');

    const session = await getTerminalSession('env-localhost');
    const workspaces = await getWorkspaces();
    const created = await createTask({
      workspace_id: 'workspace-default',
      environment_id: 'env-localhost',
      task_profile: 'claude-code',
      task_input: 'Implement harness',
    });
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

    const { getHealth } = await import('./endpoints');
    await expect(getHealth()).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.any(Object));
  });
});
