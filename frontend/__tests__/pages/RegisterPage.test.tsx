import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '@/shared/test/render'
import { handlers } from '../mocks/handlers'
import RegisterPage from '../../src/pages/RegisterPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('RegisterPage', () => {
  it('renders registration form with username field', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByLabelText(/username/i)).toHaveAttribute('name', 'username')
    expect(screen.getByLabelText(/username/i)).toHaveAttribute('autocomplete', 'username')
  })

  it('renders display name field', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByLabelText(/display name/i)).toHaveAttribute('autocomplete', 'name')
  })

  it('renders password and confirm password fields', () => {
    renderWithProviders(<RegisterPage />, { route: '/register' })
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('Confirm Password')).toHaveAttribute('autocomplete', 'new-password')
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

  it('announces validation errors and associates them with password controls', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RegisterPage />, { route: '/register' })

    await user.type(screen.getByLabelText(/username/i), 'alice')
    await user.type(screen.getByLabelText(/display name/i), 'Alice')
    await user.type(screen.getByLabelText('Password'), 'secret')
    await user.type(screen.getByLabelText('Confirm Password'), 'different')
    await user.click(screen.getByRole('button', { name: /register/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/passwords do not match/i)
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-describedby', alert.id)
    expect(screen.getByLabelText('Confirm Password')).toHaveAttribute('aria-describedby', alert.id)
  })
})
