import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import ChatInterface from '../src/components/ChatInterface'
import { AuthProvider } from '../src/context/AuthContext'

// Mock /auth/me to return a logged-in user so AuthProvider doesn't block
global.fetch = jest.fn((url: string) => {
  if (String(url).includes('/auth/me')) {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ email: 'user@example.com', name: 'Test User', picture: null }),
    })
  }
  // chat endpoint — single SSE "done" event
  return Promise.resolve({
    ok: true,
    status: 200,
    body: {
      getReader: () => {
        let done = false
        return {
          read: () => {
            if (done) return Promise.resolve({ done: true })
            done = true
            return Promise.resolve({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type": "done", "agent": "MasterAgent", "message": "done"}\n\n'
              ),
            })
          },
        }
      },
    },
  })
}) as jest.Mock

const Wrapped = () => (
  <AuthProvider>
    <ChatInterface />
  </AuthProvider>
)

describe('ChatInterface', () => {
  beforeEach(() => jest.clearAllMocks())

  it('renders the chat input and send button', () => {
    render(<Wrapped />)
    expect(screen.getByLabelText(/type your request/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send message/i })).toBeInTheDocument()
  })

  it('sends a message and displays it in the log', async () => {
    render(<Wrapped />)
    const input = screen.getByLabelText(/type your request/i)
    fireEvent.change(input, { target: { value: 'Schedule a sync tomorrow' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() =>
      expect(screen.getByText('Schedule a sync tomorrow')).toBeInTheDocument()
    )
  })

  it('calls the chat API with credentials: include', async () => {
    render(<Wrapped />)
    const input = screen.getByLabelText(/type your request/i)
    fireEvent.change(input, { target: { value: 'Create a task' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls
      const chatCall = calls.find((c: string[]) => String(c[0]).includes('/api/v1/chat'))
      expect(chatCall).toBeTruthy()
      expect(chatCall[1].credentials).toBe('include')
    })
  })
})
