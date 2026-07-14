import { http, HttpResponse } from 'msw'

export const handlers = [
  // Auth
  http.post('/api/auth/login', async ({ request }) => {
    const body = await request.json() as { username: string; password: string }
    if (body.username === 'admin' && body.password === 'admin') {
      return HttpResponse.json({
        access_token: 'mock-access-token',
        refresh_token: 'mock-refresh-token',
        user: { id: 'u1', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active', must_change_password: false },
      })
    }
    return HttpResponse.json({ detail: 'Invalid username or password' }, { status: 401 })
  }),

  http.post('/api/auth/register', () => {
    return HttpResponse.json({ message: 'Registration submitted. Awaiting admin approval.' }, { status: 201 })
  }),

  http.get('/api/auth/me', () => {
    return HttpResponse.json({
      id: 'u1', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active',
    })
  }),

  // Domain v2 frontend projections
  http.get('/api/domain/capabilities', () => {
    return HttpResponse.json({
      domain_contract_version: 2,
      mode: 'v2',
      standard_task_create: true,
      project_context: true,
      workspace_links: true,
      task_attempts: true,
      task_dispatcher: {
        participant_type: 'task-dispatcher',
        ready: true,
        maintenance_active: false,
        maintenance_epoch: null,
        stale_after_seconds: 30,
        registered_participant_ids: ['dispatcher-test'],
        active_participant_ids: ['dispatcher-test'],
        fresh_participant_ids: ['dispatcher-test'],
        stale_participant_ids: [],
      },
      literature_research_task: true,
      overview_snapshot: true,
      overview_snapshot_job_store: true,
      overview_snapshot_planner: {
        job_store_ready: true,
        planner_ready: true,
        planner_status: 'ready',
      },
    })
  }),

  http.get('/api/domain/projects', () => {
    return HttpResponse.json({ items: [domainProject()] })
  }),

  http.get('/api/domain/workspaces', () => {
    return HttpResponse.json({ items: [domainWorkspace()] })
  }),

  // Projects
  http.get('/api/projects', () => {
    return HttpResponse.json({
      items: [{ project_id: 'default', name: 'Default Project', description: '', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', owner_user_id: 'u1' }],
    })
  }),

  http.get('/api/projects/default/tasks', () => {
    return HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null })
  }),

  http.get('/api/projects/default/task-edges', () => {
    return HttpResponse.json({ items: [] })
  }),

  http.get('/api/projects/default/environment-refs', () => {
    return HttpResponse.json({ items: [] })
  }),

  http.get('/api/projects/:projectId', ({ params }) => {
    const projectId = String(params.projectId)
    return HttpResponse.json({
      project_id: projectId,
      name: projectId === 'default' ? 'Default Project' : 'Created Project',
      description: '',
      default_workspace_id: null,
      default_environment_id: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      owner_user_id: 'u1',
    })
  }),

  http.get('/api/projects/:projectId/tasks', () => {
    return HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null })
  }),

  http.get('/api/projects/:projectId/task-edges', () => {
    return HttpResponse.json({ items: [] })
  }),

  // Environments
  http.get('/api/environments', () => {
    return HttpResponse.json({ items: [] })
  }),

  // Workspaces
  http.get('/api/workspaces', () => {
    return HttpResponse.json({ items: [] })
  }),

  // Skills
  http.get('/api/skills', () => {
    return HttpResponse.json({ items: [] })
  }),

  // Files
  http.get('/api/files/list', () => {
    return HttpResponse.json({ entries: [], path: '/' })
  }),

  // Sessions
  http.get('/api/sessions', () => {
    return HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null })
  }),

  http.get('/api/sessions/batch-detail', () => {
    return HttpResponse.json({ items: {} })
  }),
]

function domainProject() {
  return {
    project_id: 'default',
    name: 'Default Project',
    description: '',
    status: 'active',
    is_default: true,
    owner_user_id: 'u1',
    current_user_role: 'owner',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    recent_activity_at: '2026-01-01T00:00:00Z',
    workspace_count: 1,
    executable_workspace_count: 1,
    task_count: 0,
    active_task_count: 0,
    running_task_count: 0,
    primary_workspace: null,
    attention_required: false,
    attention_reasons: [],
    permissions: {
      can_edit: true,
      can_publish: true,
      can_manage_members: true,
      can_archive: false,
      can_unarchive: false,
      can_create_task: true,
    },
  }
}

function domainWorkspace() {
  return {
    workspace_id: 'workspace-default',
    label: 'Repository Default',
    description: 'Seed workspace',
    canonical_path: '/workspace/project',
    workspace_context: null,
    status: 'active',
    owner_user_id: 'u1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    recent_activity_at: '2026-01-01T00:00:00Z',
    environment: {
      environment_id: 'env-1',
      alias: 'gpu-lab',
      display_name: 'GPU Lab',
      status: 'active',
    },
    project_links: [{
      project_id: 'default',
      project_name: 'Default Project',
      project_status: 'active',
      current_user_role: 'owner',
      link_status: 'active',
      is_primary: true,
      can_execute: true,
      cannot_execute_reason: null,
    }],
    task_count: 0,
    active_task_count: 0,
    can_execute: true,
    cannot_execute_reason: null,
    can_manage_registry: true,
    git_status: {
      state: 'not_collected',
      branch: null,
      is_dirty: null,
      observed_at: null,
    },
  }
}
