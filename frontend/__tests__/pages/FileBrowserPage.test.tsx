import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
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
})
