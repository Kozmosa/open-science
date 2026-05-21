import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '../../src/test/render'
import { handlers } from '../mocks/handlers'
import LoginPage from '../../src/pages/LoginPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('LoginPage', () => {
  it('renders login form with username and password fields', () => {
    renderWithProviders(<LoginPage />, { route: '/login' })
    expect(screen.getByPlaceholderText(/username/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument()
  })

  it('renders login button', () => {
    renderWithProviders(<LoginPage />, { route: '/login' })
    expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument()
  })

  it('renders link to register page', () => {
    renderWithProviders(<LoginPage />, { route: '/login' })
    const links = screen.getAllByRole('link')
    const registerLink = links.find(link => link.getAttribute('href') === '/register')
    expect(registerLink).toBeInTheDocument()
  })
})
