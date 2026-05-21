import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
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
})
