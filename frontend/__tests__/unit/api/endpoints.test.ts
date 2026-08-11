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

  it('uses typed preview and confirm endpoints for cross-engine Task forks', async () => {
    const { confirmFork, createTask, getTaskEdges, getTasks, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const created = await createTask({
      projectId: 'project-alpha',
      workspaceId: 'workspace-alpha',
      researcherType: 'vanilla',
      harnessEngine: 'claude-code',
      prompt: 'Strict mutation response',
      skills: [],
      mcpServers: [],
    }, 'task.create:strict-mutation');
    const beforePreview = await getTasks();

    const preview = await previewFork(created.task_id, {
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Strict fork response',
      transfer_mode: 'context_only',
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-test' },
    }, 'task.fork.preview:strict-mutation');
    const afterPreview = await getTasks();

    const forked = await confirmFork(created.task_id, preview.preview_id, {
      preview_hash: preview.preview_hash,
      source_revision: preview.source_revision,
      transfer_mode: preview.transfer_mode,
      truncation_acknowledged: false,
      full_transcript_confirmed: false,
    }, 'task.fork.confirm:strict-mutation');
    const afterConfirm = await getTasks();
    const relationships = await getTaskEdges('project-alpha');

    expect(created).toMatchObject({
      project_id: 'project-alpha',
      workspace_id: 'workspace-alpha',
      status: 'queued',
    });
    expect(preview).toMatchObject({
      source_engine_family: 'claude',
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      transfer_mode: 'context_only',
      truncated: false,
    });
    expect(afterPreview.items).toHaveLength(beforePreview.items.length);
    expect(forked).toMatchObject({
      project_id: 'project-alpha',
      workspace_id: 'workspace-alpha',
      title: 'Strict fork response',
      harness_engine: 'codex-app-server',
      status: 'queued',
    });
    expect(afterConfirm.items).toHaveLength(afterPreview.items.length + 1);
    expect(relationships.items).toContainEqual(expect.objectContaining({
      source_task_id: forked.task_id,
      target_task_id: created.task_id,
      relationship_type: 'derived_from',
    }));
    expect(forked).not.toHaveProperty('transfer_id');
  });

  it('replays an unchanged fork confirmation without creating a second target', async () => {
    const { confirmFork, getTasks, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const preview = await previewFork('task-seed', {
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Replayable fork confirmation',
      transfer_mode: 'context_only',
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-confirm-replay' },
    }, 'task.fork.preview:confirm-replay');
    const confirmPayload = {
      preview_hash: preview.preview_hash,
      source_revision: preview.source_revision,
      transfer_mode: preview.transfer_mode,
      truncation_acknowledged: false,
      full_transcript_confirmed: false,
    };
    const first = await confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:confirm-replay',
    );
    const replay = await confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:confirm-replay',
    );

    expect(replay.task_id).toBe(first.task_id);
    expect((await getTasks()).items).toHaveLength(2);
  });

  it('rejects confirmation after source transcript drift without changing task or transfer state', async () => {
    const { confirmFork, createTurn, getTaskEdges, getTasks, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const preview = await previewFork('task-seed', {
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Stale source fork',
      transfer_mode: 'context_only',
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-confirm-stale-source' },
    }, 'task.fork.preview:confirm-stale-source');
    const beforeTasks = await getTasks();
    const beforeEdges = await getTaskEdges('project-alpha');
    await createTurn('task-seed', 'Mutate source transcript before confirmation', 'task.turn:fork-stale-source');
    const afterSourceMutation = await getTasks();
    const confirmPayload = {
      preview_hash: preview.preview_hash,
      source_revision: preview.source_revision,
      transfer_mode: preview.transfer_mode,
      truncation_acknowledged: false,
      full_transcript_confirmed: false,
    };

    await expect(confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:confirm-stale-source',
    )).rejects.toMatchObject({ status: 409 });
    await expect(confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:confirm-stale-source-retry',
    )).rejects.toMatchObject({ status: 409 });

    expect(afterSourceMutation.items).toHaveLength(beforeTasks.items.length);
    expect((await getTasks()).items).toHaveLength(beforeTasks.items.length);
    expect((await getTaskEdges('project-alpha')).items).toHaveLength(beforeEdges.items.length);
  });

  it('rejects confirmation after a preview expires without creating a target Task', async () => {
    const { confirmFork, getTaskEdges, getTasks, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const previewCreatedAt = Date.parse('2026-08-11T00:00:00.000Z');
    const clock = vi.spyOn(Date, 'now').mockReturnValue(previewCreatedAt);
    const preview = await previewFork('task-seed', {
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Expired fork preview',
      transfer_mode: 'context_only',
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-confirm-expired-preview' },
    }, 'task.fork.preview:confirm-expired-preview');
    const beforeTasks = await getTasks();
    const beforeEdges = await getTaskEdges('project-alpha');
    expect(Date.parse(preview.expires_at)).toBe(previewCreatedAt + 900_000);

    clock.mockReturnValue(previewCreatedAt + 900_001);
    const confirmPayload = {
      preview_hash: preview.preview_hash,
      source_revision: preview.source_revision,
      transfer_mode: preview.transfer_mode,
      truncation_acknowledged: false,
      full_transcript_confirmed: false,
    };

    await expect(confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:confirm-expired-preview',
    )).rejects.toMatchObject({ status: 409 });

    expect((await getTasks()).items).toHaveLength(beforeTasks.items.length);
    expect((await getTaskEdges('project-alpha')).items).toHaveLength(beforeEdges.items.length);
  });

  it('replays a fork preview for the same request and rejects key reuse for changed source or payload', async () => {
    const { createTask, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const payload = {
      target_engine_family: 'codex' as const,
      target_harness_engine: 'codex-app-server' as const,
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Idempotent fork preview',
      transfer_mode: 'context_only' as const,
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-idempotency-test' },
    };
    const key = 'task.fork.preview:idempotency';
    const first = await previewFork('task-seed', payload, key);
    const replay = await previewFork('task-seed', payload, key);

    await expect(previewFork('task-seed', { ...payload, target_title: 'Changed payload' }, key))
      .rejects.toThrow('Idempotency-Key was already used for a different request');

    await createTask({
      projectId: 'project-alpha',
      workspaceId: 'workspace-alpha',
      researcherType: 'vanilla',
      harnessEngine: 'claude-code',
      prompt: 'Second source for idempotency conflict',
      skills: [],
      mcpServers: [],
    }, 'task.create:fork-idempotency-source');
    await expect(previewFork('task-mock-2', payload, key))
      .rejects.toThrow('Idempotency-Key was already used for a different request');

    expect(replay).toEqual(first);
    expect(replay.preview_id).toBe(first.preview_id);
  });

  it('rejects missing or blank fork idempotency keys without changing mock state', async () => {
    const { confirmFork, getTasks, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const payload = {
      target_engine_family: 'codex' as const,
      target_harness_engine: 'codex-app-server' as const,
      target_project_id: 'project-alpha',
      target_workspace_id: 'workspace-alpha',
      target_title: 'Missing key fork preview',
      transfer_mode: 'context_only' as const,
      transfer_range: {},
      metrics: {},
      disclosure: { caller: 'endpoint-missing-key-test' },
    };
    const initial = await getTasks();
    const requestBody = JSON.stringify(payload);
    const missingPreview = await fetch('/api/tasks/task-seed/fork-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: requestBody,
    });
    const blankPreview = await fetch('/api/tasks/task-seed/fork-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': '   ' },
      body: requestBody,
    });

    expect(missingPreview.status).toBe(409);
    expect(blankPreview.status).toBe(409);
    expect(await missingPreview.json()).toEqual({ detail: 'Idempotency-Key is required' });
    expect(await blankPreview.json()).toEqual({ detail: 'Idempotency-Key is required' });
    expect((await getTasks()).items).toHaveLength(initial.items.length);

    const preview = await previewFork('task-seed', payload, 'task.fork.preview:missing-key');
    expect(preview.preview_id).toBe('fork-preview-task-seed-1');
    const confirmPayload = {
      preview_hash: preview.preview_hash,
      source_revision: preview.source_revision,
      transfer_mode: preview.transfer_mode,
      truncation_acknowledged: false,
      full_transcript_confirmed: false,
    };
    const missingConfirm = await fetch(
      `/api/tasks/task-seed/fork-preview/${preview.preview_id}/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(confirmPayload),
      },
    );
    const blankConfirm = await fetch(
      `/api/tasks/task-seed/fork-preview/${preview.preview_id}/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': '  ' },
        body: JSON.stringify(confirmPayload),
      },
    );

    expect(missingConfirm.status).toBe(409);
    expect(blankConfirm.status).toBe(409);
    expect(await missingConfirm.json()).toEqual({ detail: 'Idempotency-Key is required' });
    expect(await blankConfirm.json()).toEqual({ detail: 'Idempotency-Key is required' });
    expect((await getTasks()).items).toHaveLength(initial.items.length);

    const forked = await confirmFork(
      'task-seed',
      preview.preview_id,
      confirmPayload,
      'task.fork.confirm:missing-key',
    );
    expect(forked.task_id).toBe('task-mock-2');
    expect((await getTasks()).items).toHaveLength(initial.items.length + 1);
  });

  it('sends independent preview and confirm idempotency keys and reads the target summary', async () => {
    const preview = {
      preview_id: 'preview-1',
      preview_hash: 'hash-1',
      source_task_id: 'task-1',
      source_revision: 'revision-1',
      source_engine_family: 'claude',
      target_engine_family: 'codex',
      target_project_id: 'project-1',
      target_workspace_id: 'workspace-1',
      target_harness_engine: 'codex-app-server',
      target_title: 'Forked Task',
      transfer_mode: 'context_only',
      truncated: false,
      expires_at: '2026-08-10T23:00:00Z',
    };
    const confirm = {
      transfer_id: 'transfer-1',
      preview_id: 'preview-1',
      source_task_id: 'task-1',
      status: 'transferred',
      target_task_id: 'task-target',
      submission_id: 'submission-target',
      reserved_turn_id: 'turn-target',
    };
    const target = {
      task_id: 'task-target',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      environment_id: 'env-1',
      researcher_type: 'vanilla',
      harness_engine: 'codex-app-server',
      status: 'queued',
      work_status: 'open',
      title: 'Forked Task',
      prompt: 'Continue from fork',
      created_at: '2026-08-10T22:00:00Z',
      updated_at: '2026-08-10T22:00:00Z',
      owner_user_id: 'user-1',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(preview), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(confirm), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(target), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    const { confirmFork, previewFork } = await import('../../../src/features/tasks/api/endpoints');
    const previewResult = await previewFork('task-1', {
      target_engine_family: 'codex',
      target_harness_engine: 'codex-app-server',
      target_project_id: 'project-1',
      target_workspace_id: 'workspace-1',
      transfer_mode: 'context_only',
      transfer_range: {},
    }, 'task.fork.preview:key-test');
    const targetResult = await confirmFork('task-1', previewResult.preview_id, {
      preview_hash: previewResult.preview_hash,
      source_revision: previewResult.source_revision,
      transfer_mode: previewResult.transfer_mode,
    }, 'task.fork.confirm:key-test');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks/task-1/fork-preview',
      '/api/tasks/task-1/fork-preview/preview-1/confirm',
      '/api/tasks/task-target',
    ]);
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key'))
      .toBe('task.fork.preview:key-test');
    expect((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Idempotency-Key'))
      .toBe('task.fork.confirm:key-test');
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Headers).get('Idempotency-Key'))
      .not.toBe((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Idempotency-Key'));
    expect(targetResult).toMatchObject({ task_id: 'task-target', harness_engine: 'codex-app-server' });
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
            canonical_path: '/workspace/new',
            workspace_context: 'Updated prompt',
            status: 'active',
            owner_user_id: 'user-1',
            created_at: '2026-04-27T00:00:00Z',
            updated_at: '2026-04-27T00:01:00Z',
            recent_activity_at: '2026-04-27T00:01:00Z',
            environment: {
              environment_id: 'env-1',
              alias: 'local',
              display_name: 'Local',
              status: 'active',
            },
            project_links: [],
            task_count: 0,
            active_task_count: 0,
            can_execute: true,
            cannot_execute_reason: null,
            can_manage_registry: true,
            git_status: { state: 'not_collected' },
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
