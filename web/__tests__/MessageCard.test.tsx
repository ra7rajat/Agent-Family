import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import MessageCard from '../src/components/MessageCard'

describe('MessageCard', () => {
  it('renders user message correctly', () => {
    render(<MessageCard id="1" agent="User" state="completed" message="Hello world" />)
    expect(screen.getByText('Hello world')).toBeInTheDocument()
    
    // User label should be visually hidden for the user side per our CSS, but let's check it doesn't render it in the dom
    expect(screen.queryByText('You')).not.toBeInTheDocument()
  })

  it('renders a calendar agent message', () => {
    render(<MessageCard id="2" agent="CalendarAgent" state="completed" message="Meeting scheduled" />)
    expect(screen.getByText('Calendar')).toBeInTheDocument()
    expect(screen.getByText('Meeting scheduled')).toBeInTheDocument()
  })

  it('renders a task agent message', () => {
    render(<MessageCard id="3" agent="TaskAgent" state="completed" message="Task added" />)
    expect(screen.getByText('Tasks')).toBeInTheDocument()
    expect(screen.getByText('Task added')).toBeInTheDocument()
  })

  it('displays Thinking... when state is thinking', () => {
    render(<MessageCard id="4" agent="MasterAgent" state="thinking" message="Preparing..." />)
    expect(screen.getByText('Orchestrator')).toBeInTheDocument()
    expect(screen.getByText('Thinking...')).toBeInTheDocument()
    // ensure message content isn't shown while thinking
    expect(screen.queryByText('Preparing...')).not.toBeInTheDocument()
  })
})
