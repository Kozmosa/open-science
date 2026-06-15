import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '@/shared/test/render'
import { handlers } from '../mocks/handlers'
import RegisterPage from '../../src/pages/RegisterPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('RegisterPage', () => {
  it('renders registration form with username field', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByPlaceholderText(/username/i)).toBeInTheDocument()
  })

  it('renders display name field', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByPlaceholderText(/display name/i)).toBeInTheDocument()
  })

  it('renders password and confirm password fields', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Confirm Password')).toBeInTheDocument()
  })

  it('renders register button', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByRole('button', { name: /register/i })).toBeInTheDocument()
  })

  it('renders link to login page', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    const links = screen.getAllByRole('link')
    const loginLink = links.find(link => link.getAttribute('href') === '/login')
    expect(loginLink).toBeInTheDocument()
  })
})
