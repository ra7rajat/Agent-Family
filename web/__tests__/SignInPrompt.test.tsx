import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import { AuthProvider } from '../src/context/AuthContext'
import SignInPrompt from '../src/components/SignInPrompt'

// Mock Framer Motion
jest.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Unauthenticated state
global.fetch = jest.fn(() =>
  Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) })
) as jest.Mock

describe('SignInPrompt', () => {
  it('renders with proper dialog role and aria-modal', () => {
    render(
      <AuthProvider>
        <SignInPrompt />
      </AuthProvider>
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  it('has an accessible Connect Google Account button', () => {
    render(
      <AuthProvider>
        <SignInPrompt />
      </AuthProvider>
    )
    const btn = screen.getByLabelText(/sign in with google to connect your calendar and tasks/i)
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveAttribute(
      'aria-label',
      'Sign in with Google to connect your Calendar and Tasks'
    )
  })

  it('renders all agent intro messages', () => {
    render(
      <AuthProvider>
        <SignInPrompt />
      </AuthProvider>
    )
    expect(screen.getByText(/master orchestrator/i)).toBeInTheDocument()
    expect(screen.getByText(/Google Calendar events/i)).toBeInTheDocument()
    expect(screen.getByText(/Google Tasks/i)).toBeInTheDocument()
    expect(screen.getByText(/sign in below/i)).toBeInTheDocument()
  })

  it('button is keyboard-accessible (focusable)', () => {
    render(
      <AuthProvider>
        <SignInPrompt />
      </AuthProvider>
    )
    const btn = screen.getByLabelText(/sign in with google to connect your calendar and tasks/i)
    btn.focus()
    expect(document.activeElement).toBe(btn)
  })
})
