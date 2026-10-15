import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from './ToastProvider'
import { useToast } from './toastContext'

function Buttons() {
  const toast = useToast()
  return (
    <>
      <button onClick={() => toast.error('Disk is full')}>fail</button>
      <button onClick={() => toast.info('Saved')}>ok</button>
    </>
  )
}

afterEach(() => {
  vi.useRealTimers()
})

describe('ToastProvider', () => {
  it('has a labelled live region before any toast', () => {
    render(
      <ToastProvider>
        <Buttons />
      </ToastProvider>,
    )
    expect(screen.getByRole('region', { name: 'Notifications' })).toBeInTheDocument()
  })

  it('announces an error as an alert and an info message as status', async () => {
    const user = userEvent.setup()
    render(
      <ToastProvider>
        <Buttons />
      </ToastProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'fail' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Disk is full')
    await user.click(screen.getByRole('button', { name: 'ok' }))
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
  })

  it('dismisses a toast by button', async () => {
    const user = userEvent.setup()
    render(
      <ToastProvider>
        <Buttons />
      </ToastProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'fail' }))
    await user.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    expect(screen.queryByText('Disk is full')).not.toBeInTheDocument()
  })

  it('dismisses toasts by itself, errors a little later', () => {
    vi.useFakeTimers()
    render(
      <ToastProvider>
        <Buttons />
      </ToastProvider>,
    )
    act(() => {
      screen.getByRole('button', { name: 'fail' }).click()
      screen.getByRole('button', { name: 'ok' }).click()
    })
    expect(screen.getByText('Disk is full')).toBeInTheDocument()
    expect(screen.getByText('Saved')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(4500)
    })
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
    expect(screen.getByText('Disk is full')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(screen.queryByText('Disk is full')).not.toBeInTheDocument()
  })

  it('requires a provider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Buttons />)).toThrow(/ToastProvider/)
  })
})
