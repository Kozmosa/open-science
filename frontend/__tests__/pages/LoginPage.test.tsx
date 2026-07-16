import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '@/shared/test/render'
import { handlers } from '../mocks/handlers'
import LoginPage from '../../src/pages/LoginPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('LoginPage', () => {
  it('renders login form with username and password fields', () => {
    renderWithProviders(<LoginPage />, { route: '/login' })
    expect(screen.getByLabelText(/username/i)).toHaveAttribute('name', 'username')
    expect(screen.getByLabelText(/username/i)).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('name', 'password')
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('autocomplete', 'current-password')
  })

  it('renders OpenScience brand heading', () => {
    renderWithProviders(<LoginPage />, { route: '/login' })
    expect(screen.getByText('OpenScience')).toBeInTheDocument()
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

  it('announces login errors and associates them with the controls', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LoginPage />, { route: '/login' })

    await user.type(screen.getByLabelText(/username/i), 'invalid')
    await user.type(screen.getByLabelText(/password/i), 'invalid')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/invalid username or password/i)
    expect(screen.getByLabelText(/username/i)).toHaveAttribute('aria-describedby', alert.id)
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('aria-describedby', alert.id)
  })
})
