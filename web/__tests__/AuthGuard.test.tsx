import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import { AuthProvider } from '../src/context/AuthContext'
import AuthGuard from '../src/components/AuthGuard'

// Suppress Framer Motion animation warnings in tests
jest.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const mockFetch = (status: number, body: object) => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    })
  ) as jest.Mock
}

describe('AuthGuard', () => {
  afterEach(() => jest.clearAllMocks())

  it('shows a spinner while loading auth state', () => {
    // Never resolves — simulates infinite loading
    global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock
    render(
      <AuthProvider>
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      </AuthProvider>
    )
    expect(screen.getByRole('status', { name: /checking authentication/i })).toBeInTheDocument()
  })

  it('renders children when session is valid (200)', async () => {
    mockFetch(200, { email: 'test@example.com', name: 'Test User', picture: null })
    render(
      <AuthProvider>
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByText('Protected content')).toBeInTheDocument()
    )
  })

  it('renders SignInPrompt when unauthenticated (401)', async () => {
    mockFetch(401, { detail: 'Not authenticated' })
    render(
      <AuthProvider>
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    )
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })

  it('shows the Connect Google Account button in the sign-in prompt', async () => {
    mockFetch(401, { detail: 'Not authenticated' })
    render(
      <AuthProvider>
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      </AuthProvider>
    )
    await waitFor(() =>
      expect(screen.getByLabelText(/sign in with google to connect your calendar and tasks/i)).toBeInTheDocument()
    )
  })
})
