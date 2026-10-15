import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingControl } from './RatingControl'

describe('RatingControl', () => {
  it('has three labelled toggle buttons in a group', () => {
    render(<RatingControl value={1} onChange={() => {}} />)
    expect(screen.getByRole('group', { name: /how well does this track fit/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Not a fit' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'OK' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Good fit' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('reports the rating chosen with the keyboard', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<RatingControl value={null} onChange={onChange} />)
    await user.tab()
    expect(screen.getByRole('button', { name: 'Not a fit' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('button', { name: 'OK' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('button', { name: 'Good fit' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(2)
    await user.keyboard('{ArrowLeft}{ArrowLeft}')
    await user.keyboard(' ')
    expect(onChange).toHaveBeenLastCalledWith(0)
  })

  it('reports 0 as a rating, not as "none"', async () => {
    const onChange = vi.fn()
    render(<RatingControl value={null} onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Not a fit' }))
    expect(onChange).toHaveBeenCalledWith(0)
  })

  it('clears the rating when the selected one is pressed again', async () => {
    const onChange = vi.fn()
    render(<RatingControl value={2} onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Good fit' }))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('does nothing when disabled', async () => {
    const onChange = vi.fn()
    render(<RatingControl value={null} onChange={onChange} disabled />)
    await userEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(onChange).not.toHaveBeenCalled()
  })
})
