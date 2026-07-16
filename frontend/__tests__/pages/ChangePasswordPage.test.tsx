import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { renderWithProviders } from '@/shared/test/render'
import { handlers } from '../mocks/handlers'
import ChangePasswordPage from '../../src/pages/ChangePasswordPage'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('ChangePasswordPage', () => {
  it('renders change password form with current password field', () => {
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })
    expect(screen.getByLabelText(/current password/i)).toHaveAttribute('name', 'current_password')
    expect(screen.getByLabelText(/current password/i)).toHaveAttribute('autocomplete', 'current-password')
  })

  it('renders new password and confirm password fields', () => {
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })
    expect(screen.getByLabelText(/^new password$/i)).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText(/confirm password/i)).toHaveAttribute('autocomplete', 'new-password')
  })

  it('renders change password button', () => {
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })
    expect(screen.getByRole('button', { name: /change password/i })).toBeInTheDocument()
  })

  it('announces validation errors and associates them with password controls', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })

    await user.type(screen.getByLabelText(/current password/i), 'current')
    await user.type(screen.getByLabelText(/^new password$/i), 'secret')
    await user.type(screen.getByLabelText(/confirm password/i), 'different')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/passwords do not match/i)
    expect(screen.getByLabelText(/^new password$/i)).toHaveAttribute('aria-describedby', alert.id)
    expect(screen.getByLabelText(/confirm password/i)).toHaveAttribute('aria-describedby', alert.id)
  })
})
