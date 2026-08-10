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

  it('adapts archive and unarchive TaskSummary responses from MSW', async () => {
    const {
      archiveTask,
      createTask,
      unarchiveTask,
    } = await import('../../../src/features/tasks/api/endpoints');
    const created = await createTask({
      projectId: 'project-alpha',
      workspaceId: 'workspace-alpha',
      researcherType: 'vanilla',
      harnessEngine: 'claude-code',
      prompt: 'Archive contract regression',
      skills: [],
      mcpServers: [],
    }, 'task.create:archive-contract');

    const archived = await archiveTask(created.task_id, 'task.archive:archive-contract');
    expect(archived).toMatchObject({
      task_id: created.task_id,
      archived_at: expect.any(String),
      archive_reason: expect.any(String),
    });
    expect(archived).not.toHaveProperty('task');

    const restored = await unarchiveTask(created.task_id, 'task.unarchive:archive-contract');
    expect(restored).toMatchObject({ task_id: created.task_id, archived_at: null, archive_reason: null });
    expect(restored).not.toHaveProperty('task');
  });

  it('adapts explicit complete and reopen TaskSummary responses from MSW', async () => {
    const {
      completeTask,
      createTask,
      reopenTask,
    } = await import('../../../src/features/tasks/api/endpoints');
    const created = await createTask({
      projectId: 'project-alpha',
      workspaceId: 'workspace-alpha',
      researcherType: 'vanilla',
      harnessEngine: 'claude-code',
      prompt: 'Complete lifecycle contract',
      skills: [],
      mcpServers: [],
    }, 'task.create:complete-contract');

    const completed = await completeTask(created.task_id, 'task.complete:contract');
    expect(completed.work_status).toBe('completed');
    const reopened = await reopenTask(created.task_id, 'task.reopen:contract');
    expect(reopened.work_status).toBe('open');
  });

  it('keeps a succeeded Turn open until explicit Task completion', async () => {
    const {
      completeTask,
      getTask,
      reopenTask,
    } = await import('../../../src/features/tasks/api/endpoints');
    const succeededTurnTask = await getTask('task-seed');

    expect(succeededTurnTask.status).toBe('succeeded');
    expect(succeededTurnTask.work_status).toBe('open');

    const completed = await completeTask(succeededTurnTask.task_id, 'task.complete:succeeded-turn');
    expect(completed.work_status).toBe('completed');
    const reopened = await reopenTask(succeededTurnTask.task_id, 'task.reopen:succeeded-turn');
    expect(reopened.work_status).toBe('open');
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

  it('sends idempotency keys through explicit Task completion and reopen actions', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({
        task_id: 'task-1',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
        environment_id: 'env-1',
        researcher_type: 'vanilla',
        harness_engine: 'claude-code',
        status: 'queued',
        work_status: 'completed',
        title: 'Task',
        prompt: 'Prompt',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        owner_user_id: 'u1',
      }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ));
    vi.stubGlobal('fetch', fetchMock);

    const { completeTask, reopenTask } = await import('../../../src/features/tasks/api/endpoints');
    await completeTask('task-1', 'task.complete:test');
    await reopenTask('task-1', 'task.reopen:test');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks/task-1/complete',
      '/api/tasks/task-1/reopen',
    ]);
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('task.complete:test');
    expect((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('task.reopen:test');
  });

  it('interrupts a concrete active Turn without using the Task cancel endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        control_request_id: 'control-1',
        expected_turn_id: 'turn-1',
        kind: 'interrupt',
        status: 'accepted',
        task_id: 'task-1',
      }), {
        status: 202,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { interruptTurn } = await import('../../../src/features/tasks/api/endpoints');
    await interruptTurn('task-1', 'turn-1', 'turn.interrupt:test');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks/task-1/turns/turn-1/interrupt',
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ expected_turn_id: 'turn-1' }),
    }));
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key')).toBe('turn.interrupt:test');
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
