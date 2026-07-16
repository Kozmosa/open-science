import { readFileSync, readdirSync } from 'node:fs';
import { extname, join } from 'node:path';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { setupServer } from 'msw/node';
import {
  createLiteratureCheck,
  createLiteratureResearchTask,
  createTask,
  getAdminUsers,
  getLiteratureCheck,
  getLiteraturePaper,
  getLiteraturePapers,
  getLiteratureResearchTask,
  getLiteratureResearchTasks,
  getLiteratureSummary,
  getSearchSettings,
  getSessionsBatchDetail,
  requestLiteratureSummary,
  retryTask,
} from '@/shared/api/endpoints';
import {
  acceptDomainContextCandidate,
  getDomainCapabilities,
  getDomainProjectContext,
  getDomainProjectContextCandidates,
  getDomainProjectContextDiff,
  getDomainProjectContextVersions,
  getDomainProjects,
  getDomainTaskAttempts,
  getDomainWorkspaces,
  getOverviewRefreshJob,
  getTodayOverview,
  publishDomainProjectContext,
  requestTodayOverviewRefresh,
  saveDomainProjectContextDraft,
} from '@/features/domain/api';
import { frontendMockHandlers, resetLegacyMockState } from '@/shared/api/mockHandlers';

const server = setupServer(...frontendMockHandlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());
beforeEach(() => resetLegacyMockState());

describe('frontend v2 mock contract', () => {
  it('exposes complete capability, Project, and Workspace projections', async () => {
    const capabilities = await getDomainCapabilities();
    const projects = await getDomainProjects();
    const workspaces = await getDomainWorkspaces();

    expect(capabilities).toMatchObject({
      domain_contract_version: 2,
      standard_task_create: true,
      project_context: true,
      workspace_links: true,
      task_attempts: true,
      literature_research_task: true,
      overview_snapshot: true,
    });
    expect(capabilities.task_dispatcher.ready).toBe(true);
    expect(projects.items.find((project) => project.project_id === 'project-alpha')).toMatchObject({
      status: 'active',
      current_user_role: 'owner',
      executable_workspace_count: 1,
      permissions: { can_create_task: true, can_publish: true },
    });
    expect(workspaces.items.find((workspace) => workspace.workspace_id === 'workspace-alpha')).toMatchObject({
      can_execute: true,
      environment: { environment_id: 'env-localhost', status: 'active' },
      git_status: { state: 'available', branch: 'feat/frontend-phases' },
    });
  });

  it('keeps a Task ID stable across create, Attempt projection, and retry', async () => {
    const task = await createTask({
      project_id: 'project-alpha',
      workspace_id: 'workspace-alpha',
      researcher_type: 'vanilla',
      harness_engine: 'claude-code',
      prompt: 'Exercise the deterministic Task flow.',
      skills: [],
      mcp_servers: [],
      title: 'Contract Task',
    }, 'task.create:contract');
    const initialAttempts = await getDomainTaskAttempts(task.task_id);
    const retried = await retryTask(task.task_id, 'task.retry:contract');
    const attempts = await getDomainTaskAttempts(task.task_id);

    expect(task).toMatchObject({
      status: 'queued',
      project_id: 'project-alpha',
      workspace_id: 'workspace-alpha',
      project_context_version_id: 'context-project-alpha-v1',
    });
    expect(initialAttempts.items).toHaveLength(1);
    expect(initialAttempts.items[0]).toMatchObject({ trigger: 'initial', status: 'queued' });
    expect(retried.task?.task_id ?? retried.new_task.task_id).toBe(task.task_id);
    expect(retried.attempt).toMatchObject({ task_id: task.task_id, attempt_seq: 2, trigger: 'retry' });
    expect(attempts.items.map((attempt) => attempt.trigger)).toEqual(['initial', 'retry']);
  });

  it('supports Context draft, candidate, publish, history, and diff', async () => {
    const candidates = await getDomainProjectContextCandidates('project-alpha');
    const accepted = await acceptDomainContextCandidate(
      'project-alpha',
      candidates.items[0]!.candidate_id,
      'context.candidate.accept:contract',
    );
    const afterAccept = await getDomainProjectContext('project-alpha');
    const saved = await saveDomainProjectContextDraft(
      'project-alpha',
      `${afterAccept.draft?.content ?? ''}\n\nContract-validated draft.`,
      'context.draft:contract',
    );
    const published = await publishDomainProjectContext('project-alpha', 'context.publish:contract');
    const versions = await getDomainProjectContextVersions('project-alpha');
    const diff = await getDomainProjectContextDiff(
      'project-alpha',
      published.context_version_id,
      'context-project-alpha-v1',
    );

    expect(accepted.status).toBe('accepted');
    expect(afterAccept.draft?.content).toContain(accepted.content);
    expect(saved.draft?.fingerprint).toContain('draft-project-alpha');
    expect(published).toMatchObject({ is_active: true, assembly_eligible: true });
    expect(versions.items).toHaveLength(2);
    expect(diff).toMatchObject({
      before_context_version_id: 'context-project-alpha-v1',
      after_context_version_id: published.context_version_id,
    });
    expect(diff.diff).toContain('Contract-validated draft.');
  });

  it('supports Literature check, summary, and recoverable research intent scenarios', async () => {
    const papers = await getLiteraturePapers({ view: 'unread' });
    const paper = await getLiteraturePaper(papers.items[0]!.paper_id);
    const check = await createLiteratureCheck('literature.check:contract');
    const completedCheck = await getLiteratureCheck(check.check_id);
    const queuedSummary = await requestLiteratureSummary(paper.paper_id, 'literature.summary:contract');
    const generatingSummary = await getLiteratureSummary(paper.paper_id);
    const completedSummary = await getLiteratureSummary(paper.paper_id);
    const intent = await createLiteratureResearchTask(paper.paper_id, {
      project_id: 'project-alpha',
      workspace_id: 'workspace-alpha',
      task_preset: 'standard',
      title: 'Research deterministic interfaces',
    }, 'literature.intent:contract');
    const recovered = await getLiteratureResearchTask(paper.paper_id, 'literature.intent:contract');
    const intents = await getLiteratureResearchTasks(paper.paper_id);

    expect(paper).toMatchObject({
      current_version_id: 'paper-transformers-v2',
      user_state: { is_read: false, is_saved: true },
    });
    expect(completedCheck.status).toBe('completed');
    expect(queuedSummary.status).toBe('queued');
    expect(generatingSummary.status).toBe('generating');
    expect(completedSummary).toMatchObject({ status: 'completed', version_id: paper.current_version_id });
    expect(intent).toMatchObject({ status: 'creating_task', idempotency_key: 'literature.intent:contract' });
    expect(recovered).toMatchObject({ status: 'completed', task_id: 'task-seed' });
    expect(intents.items.map((item) => item.intent_id)).toContain(intent.intent_id);
  });

  it('progresses Today refresh from queued to running and succeeded', async () => {
    const snapshot = await getTodayOverview();
    const queued = await requestTodayOverviewRefresh('overview.refresh:contract');
    const running = await getOverviewRefreshJob(queued.job_id);
    const succeeded = await getOverviewRefreshJob(queued.job_id);

    expect(snapshot.display_cards?.map((card) => card.id)).toEqual([
      'attention',
      'progress',
      'literature',
      'continue',
      'resources',
    ]);
    expect(snapshot.next_scheduled_at).toBe('2026-07-17T06:00:00+08:00');
    expect(queued.status).toBe('queued');
    expect(running.status).toBe('running');
    expect(succeeded).toMatchObject({
      status: 'succeeded',
      snapshot_id: snapshot.snapshot_id,
      source_status: 'ok',
    });
  });

  it('covers Sessions batch and settings/admin support endpoints used by current pages', async () => {
    const sessions = await getSessionsBatchDetail(['session-seed', 'missing-session']);
    const users = await getAdminUsers();
    const search = await getSearchSettings();

    expect(sessions.items['session-seed']?.[0]).toMatchObject({ task_id: 'task-seed', status: 'completed' });
    expect(sessions.items['missing-session']).toEqual([]);
    expect(users.items.some((user) => user.id === 'mock-browser-user')).toBe(true);
    expect(search).toMatchObject({ active_backend: 'builtin', auto_start_mcp_servers: [] });
  });
});

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return ['.ts', '.tsx'].includes(extname(entry.name)) ? [path] : [];
  });
}

describe('frontend mock architecture guard', () => {
  const srcRoot = join(process.cwd(), 'src');

  it('limits VITE_USE_MOCK to the bootstrap and Vite environment declaration', () => {
    const matches = sourceFiles(srcRoot)
      .filter((path) => readFileSync(path, 'utf8').includes('VITE_USE_MOCK'))
      .map((path) => path.slice(srcRoot.length + 1).replaceAll('\\', '/'))
      .sort();

    expect(matches).toEqual(['main.tsx', 'vite-env.d.ts']);
  });

  it('keeps business endpoint modules independent from direct mock implementations', () => {
    const endpointModules = [
      join(srcRoot, 'shared/api/endpoints.ts'),
      join(srcRoot, 'features/domain/api.ts'),
      join(srcRoot, 'features/tasks/api/endpoints.ts'),
      join(srcRoot, 'features/settings/api/endpoints.ts'),
    ];

    for (const path of endpointModules) {
      const source = readFileSync(path, 'utf8');
      expect(source).not.toMatch(/from ['"].*mock(?:\.ts)?['"]/);
      expect(source).not.toContain('VITE_USE_MOCK');
    }
    expect(readFileSync(join(srcRoot, 'shared/api/endpoints.ts'), 'utf8')).toContain("import { api } from './client'");
    expect(readFileSync(join(srcRoot, 'features/domain/api.ts'), 'utf8')).toContain("import { api } from '@/shared/api/client'");
  });

  it('fails unhandled browser API requests while bypassing non-API assets', () => {
    const source = readFileSync(join(srcRoot, 'shared/api/mockBrowser.ts'), 'utf8');
    expect(source).toContain("pathname.startsWith('/api/')");
    expect(source).toContain('print.error()');
    expect(source).not.toContain("onUnhandledRequest: 'bypass'");
  });
});
