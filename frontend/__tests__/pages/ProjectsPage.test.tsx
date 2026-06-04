import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '../../src/test/render'
import { handlers } from '../mocks/handlers'
import ProjectsPage from '../../src/pages/ProjectsPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('ProjectsPage', () => {
const project = {
  project_id: 'default',
  name: 'Default Project',
  description: '',
  default_workspace_id: 'workspace-default',
  default_environment_id: 'env-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const workspaceDefault = {
  workspace_id: 'workspace-default',
  project_id: 'default',
  label: 'Repository Default',
  description: 'Seed workspace',
  default_workdir: '/workspace/project',
  workspace_prompt: 'Default workspace prompt.',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const workspaceAlt = {
  ...workspaceDefault,
  workspace_id: 'workspace-alt',
  label: 'Alternate Workspace',
  default_workdir: '/workspace/alternate',
}

const environmentDefault = {
  id: 'env-1',
  alias: 'gpu-lab',
  display_name: 'GPU Lab',
  description: null,
  is_seed: false,
  tags: [],
  host: 'gpu.example.com',
  port: 22,
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: null,
  proxy_jump: null,
  proxy_command: null,
  ssh_options: {},
  default_workdir: '/workspace/project',
  preferred_python: null,
  preferred_env_manager: null,
  preferred_runtime_notes: null,
  task_harness_profile: null,
  code_server_path: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  latest_detection: null,
}

const environmentAlt = {
  ...environmentDefault,
  id: 'env-2',
  alias: 'cpu-lab',
  display_name: 'CPU Lab',
  default_workdir: '/workspace/cpu',
}

  it('renders New Task button when a project exists', async () => {
    renderWithProviders(<ProjectsPage />, { route: '/projects' })
    expect(await screen.findByRole('button', { name: /new task/i })).toBeInTheDocument()
  })

  it('shows no projects message when no projects exist', async () => {
    server.use(
      http.get('/api/projects', () => {
        return HttpResponse.json({ items: [] })
      }),
    )
    renderWithProviders(<ProjectsPage />, { route: '/projects' })
    await waitFor(() => {
      expect(screen.getByText(/no projects/i)).toBeInTheDocument()
    })
  })

  it('creates a project task with the current project and user-selected workspace and environment', async () => {
    let createdPayload: Record<string, unknown> | null = null
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ items: [project] })),
      http.get('/api/projects/default', () => HttpResponse.json(project)),
      http.get('/api/projects/default/tasks', () => HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null })),
      http.get('/api/projects/default/task-edges', () => HttpResponse.json({ items: [] })),
      http.get('/api/workspaces', () => HttpResponse.json({ items: [workspaceDefault, workspaceAlt] })),
      http.get('/api/environments', () => HttpResponse.json({ items: [environmentDefault, environmentAlt] })),
      http.get('/api/skills', () => HttpResponse.json({ items: [] })),
      http.post('/api/tasks', async ({ request }) => {
        createdPayload = await request.json() as Record<string, unknown>
        return HttpResponse.json({
          task_id: 'task-created',
          title: 'Selected bindings',
          status: 'queued',
          project_id: 'default',
          workspace_id: 'workspace-alt',
          environment_id: 'env-2',
          researcher_type: 'vanilla',
          harness_engine: 'claude-code',
          prompt: 'Run from project canvas.',
          owner_user_id: 'u1',
          exit_code: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          started_at: null,
          completed_at: null,
          error_summary: null,
          latest_output_seq: 0,
        }, { status: 201 })
      }),
    )

    renderWithProviders(<ProjectsPage />, { route: '/projects' })
    fireEvent.click(await screen.findByRole('button', { name: /new task/i }))

    await waitFor(() => expect(screen.getByLabelText('Project')).toHaveValue('default'))
    expect(screen.getByLabelText('Project')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Workspace'), { target: { value: 'workspace-alt' } })
    fireEvent.change(screen.getByLabelText('Environment'), { target: { value: 'env-2' } })
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Run from project canvas.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }))

    await waitFor(() => {
      expect(createdPayload).toMatchObject({
        project_id: 'default',
        workspace_id: 'workspace-alt',
        environment_id: 'env-2',
        prompt: 'Run from project canvas.',
      })
    })
  })
})
