import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '@/shared/test/render'
import { handlers } from '../mocks/handlers'
import ProjectsPage from '../../src/pages/ProjectsPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
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

  it('creates a project task with the current project and an executable Workspace', async () => {
    let createdPayload: Record<string, unknown> | null = null
    server.use(
      http.get('/api/projects', () => HttpResponse.json({ items: [project] })),
      http.get('/api/projects/default', () => HttpResponse.json(project)),
      http.get('/api/projects/default/tasks', () => HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null })),
      http.get('/api/projects/default/task-edges', () => HttpResponse.json({ items: [] })),
      http.get('/api/workspaces', () => HttpResponse.json({ items: [workspaceDefault, workspaceAlt] })),
      http.get('/api/environments', () => HttpResponse.json({ items: [environmentDefault, environmentAlt] })),
      http.get('/api/skills', () => HttpResponse.json({ items: [] })),
      http.get('/api/domain/projects', () => HttpResponse.json({
        items: [{
          project_id: 'default', name: 'Default Project', description: '', status: 'active',
          is_default: true, owner_user_id: 'u1', current_user_role: 'owner',
          created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
          recent_activity_at: '2026-01-01T00:00:00Z', workspace_count: 2,
          executable_workspace_count: 2, task_count: 0, active_task_count: 0,
          running_task_count: 0, primary_workspace: null, attention_required: false,
          attention_reasons: [], permissions: {
            can_edit: true, can_publish: true, can_manage_members: true,
            can_archive: false, can_unarchive: false, can_create_task: true,
          },
        }],
      })),
      http.get('/api/domain/workspaces', () => HttpResponse.json({
        items: [
          domainWorkspace('workspace-default', 'Repository Default', 'env-1', 'gpu-lab', 'GPU Lab', true),
          domainWorkspace('workspace-alt', 'Alternate Workspace', 'env-2', 'cpu-lab', 'CPU Lab', false),
        ],
      })),
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
    expect(screen.getByLabelText('Environment')).toHaveValue('CPU Lab (cpu-lab)')
    expect(screen.getByLabelText('Environment')).toHaveAttribute('readonly')
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Run from project canvas.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }))

    await waitFor(() => {
      expect(createdPayload).toMatchObject({
        project_id: 'default',
        workspace_id: 'workspace-alt',
        prompt: 'Run from project canvas.',
      })
      expect(createdPayload).not.toHaveProperty('environment_id')
    })
  })

  it('opens the create-project modal and creates a project on submit', async () => {
    let createdProjectPayload: Record<string, unknown> | null = null
    server.use(
      http.post('/api/projects', async ({ request }) => {
        createdProjectPayload = await request.json() as Record<string, unknown>
        return HttpResponse.json({
          project_id: 'proj-new',
          name: 'My New Project',
          description: 'A fresh project',
          default_workspace_id: null,
          default_environment_id: null,
          created_at: '2026-01-02T00:00:00Z',
          updated_at: '2026-01-02T00:00:00Z',
        }, { status: 201 })
      }),
    )

    renderWithProviders(<ProjectsPage />, { route: '/projects' })
    fireEvent.click(await screen.findByRole('button', { name: /new project/i }))

    const nameInput = await screen.findByLabelText('Project name')
    fireEvent.change(nameInput, { target: { value: 'My New Project' } })
    fireEvent.change(screen.getByLabelText('Description (optional)'), { target: { value: 'A fresh project' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create project' }))

    await waitFor(() => {
      expect(createdProjectPayload).toMatchObject({
        name: 'My New Project',
        description: 'A fresh project',
      })
    })
  })
})

function domainWorkspace(
  workspaceId: string,
  label: string,
  environmentId: string,
  environmentAlias: string,
  environmentDisplayName: string,
  isPrimary: boolean,
) {
  return {
    workspace_id: workspaceId,
    label,
    description: null,
    canonical_path: `/workspace/${workspaceId}`,
    workspace_context: null,
    status: 'active',
    owner_user_id: 'u1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    recent_activity_at: '2026-01-01T00:00:00Z',
    environment: {
      environment_id: environmentId,
      alias: environmentAlias,
      display_name: environmentDisplayName,
      status: 'active',
    },
    project_links: [{
      project_id: 'default',
      project_name: 'Default Project',
      project_status: 'active',
      current_user_role: 'owner',
      link_status: 'active',
      is_primary: isPrimary,
      can_execute: true,
      cannot_execute_reason: null,
    }],
    task_count: 0,
    active_task_count: 0,
    can_execute: true,
    cannot_execute_reason: null,
    can_manage_registry: true,
    git_status: { state: 'not_collected', branch: null, is_dirty: null, observed_at: null },
  }
}
