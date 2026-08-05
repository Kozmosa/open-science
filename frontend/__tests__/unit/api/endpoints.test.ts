import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { frontendMockHandlers, resetLegacyMockState } from '@/app/mock/handlers';

const server = setupServer(...frontendMockHandlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetLegacyMockState();
});

describe('api endpoints', () => {
  it('routes legacy mock scenarios through the same HTTP client transport', async () => {
    const {
      createTask,
      getTask,
      getTasks,
      listCanonicalTaskItems,
    } = await import('../../../src/features/tasks/api/endpoints');
    const { getTerminalSession } = await import('../../../src/features/terminal/api/endpoints');
    const { getDomainWorkspaces } = await import('../../../src/features/domain/api');

    const session = await getTerminalSession('env-localhost');
    const workspaces = await getDomainWorkspaces(false);
    const created = await createTask({
      projectId: 'project-alpha',
      workspaceId: 'workspace-alpha',
      researcherType: 'vanilla',
      harnessEngine: 'claude-code',
      prompt: 'Implement harness',
      skills: [],
      mcpServers: [],
    }, 'task.create:test');
    const tasks = await getTasks();
    const detail = await getTask(created.task_id);
    const items = await listCanonicalTaskItems(created.task_id);

    expect(session.status).toBe('idle');
    expect(workspaces.items[0]?.workspace_id).toBe('workspace-default');
    expect(created.status).toBe('queued');
    expect(tasks.items[0]?.task_id).toBe(created.task_id);
    expect(detail.binding?.resolved_workdir).toBeTruthy();
    expect(items[0]?.item_type).toBe('user_message');
  });

  it('sends stable idempotency keys through the Turn submission Interface', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ task_id: 'task-1', status: 'running', sequence: 1 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ));
    vi.stubGlobal('fetch', fetchMock);

    const { createTurn } = await import('../../../src/features/tasks/api/endpoints');
    await createTurn('task-1', 'Continue the analysis', 'turn.submit:test');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks/task-1/turns',
    ]);
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('turn.submit:test');
  });

  it('uses the real api client when no MSW handler intercepts the request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { getHealth } = await import('../../../src/features/system/api');
    await expect(getHealth()).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.any(Object));
  });

  it('sends canonical workspace mutations through the real api client', async () => {
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

    const { createDomainWorkspace, updateDomainWorkspace, unregisterDomainWorkspace } = await import('../../../src/features/domain/api');

    await createDomainWorkspace({
      environment_id: 'env-1',
      canonical_path: '/workspace/new',
      label: 'New workspace',
    }, 'workspace.create:test');
    await updateDomainWorkspace('workspace-new', {
      label: 'Updated workspace',
      description: 'Updated',
      default_workdir: '/workspace/updated',
      workspace_prompt: 'Updated prompt',
    }, 'workspace.update:test');
    await unregisterDomainWorkspace('workspace-new', 'workspace.unregister:test');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/domain/workspaces',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          environment_id: 'env-1',
          canonical_path: '/workspace/new',
          label: 'New workspace',
        }),
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/domain/workspaces/workspace-new',
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
      '/api/domain/workspaces/workspace-new/unregister',
      expect.objectContaining({ method: 'POST' })
    );
    expect((fetchMock.mock.calls[2]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('workspace.unregister:test');
  });
});
