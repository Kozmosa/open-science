import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '../../src/test/render'
import { handlers } from '../mocks/handlers'
import FileBrowserPage from '../../src/pages/FileBrowserPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('FileBrowserPage', () => {
  it('renders prompt to select an environment when none is available', async () => {
    renderWithProviders(<FileBrowserPage />, { route: '/files' })
    expect(screen.getByText(/select an environment/i)).toBeInTheDocument()
  })

  it('opens the requested workspace file from the route query', async () => {
    let openedPath: string | null = null;
    server.use(
      http.get('/api/environments', () => HttpResponse.json({
        items: [{
          id: 'env-localhost',
          alias: 'localhost',
          display_name: 'Localhost',
          description: null,
          is_seed: true,
          tags: [],
          host: '127.0.0.1',
          port: 22,
          user: 'xuyang',
          auth_kind: 'ssh_key',
          identity_file: null,
          proxy_jump: null,
          proxy_command: null,
          ssh_options: {},
          default_workdir: '/home/xuyang/.ainrf_workspaces/default',
          preferred_python: null,
          preferred_env_manager: null,
          preferred_runtime_notes: null,
          task_harness_profile: null,
          code_server_path: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          latest_detection: null,
        }],
      })),
      http.get('/api/workspaces', () => HttpResponse.json({
        items: [{
          workspace_id: 'workspace-default',
          project_id: 'default',
          label: 'Default Workspace',
          description: '',
          default_workdir: '/home/xuyang/.ainrf_workspaces/default',
          workspace_prompt: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }],
      })),
      http.get('/api/files/list', () => HttpResponse.json({
        path: '',
        entries: [{ path: 'docs', name: 'docs', kind: 'directory', size: null, modified_at: null }],
      })),
      http.get('/api/files/read', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get('environment_id')).toBe('env-localhost');
        expect(url.searchParams.get('workspace_id')).toBe('workspace-default');
        openedPath = url.searchParams.get('path');
        expect(openedPath).toBe('docs/literature/2606.04620-overview.md');
        return HttpResponse.json({
          path: 'docs/literature/2606.04620-overview.md',
          content: '# Literature overview',
          mime_type: 'text/markdown',
          size: 21,
        });
      })
    );

    renderWithProviders(<FileBrowserPage />, {
      route: '/workspace-browser?workspace_id=workspace-default&path=docs%2Fliterature%2F2606.04620-overview.md',
    });

    expect(await screen.findByText('2606.04620-overview.md')).toBeInTheDocument();
    await waitFor(() => expect(openedPath).toBe('docs/literature/2606.04620-overview.md'));
  })
})
