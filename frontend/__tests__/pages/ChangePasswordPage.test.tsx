import { describe, expect, it, afterAll, afterEach, beforeAll } from 'vitest'
import { screen } from '@testing-library/react'
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
    expect(screen.getByText(/current password/i)).toBeInTheDocument()
  })

  it('renders new password and confirm password fields', () => {
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })
    expect(screen.getByText(/new password/i)).toBeInTheDocument()
    expect(screen.getByText(/confirm password/i)).toBeInTheDocument()
  })

  it('renders change password button', () => {
    renderWithProviders(<ChangePasswordPage />, { route: '/change-password' })
    expect(screen.getByRole('button', { name: /change password/i })).toBeInTheDocument()
  })
})
