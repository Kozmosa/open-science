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
