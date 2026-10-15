import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Menu, MenuItem } from './Menu'

function setup(onSelect = vi.fn()) {
  render(
    <Menu label="Download credits">
      <MenuItem onSelect={() => onSelect('txt')}>Text</MenuItem>
      <MenuItem onSelect={() => onSelect('md')}>Markdown</MenuItem>
      <MenuItem href="/api/projects/1/credits?format=json" download>
        JSON
      </MenuItem>
    </Menu>,
  )
  return { onSelect, user: userEvent.setup() }
}

describe('Menu', () => {
  it('opens with the keyboard and moves with the arrow keys', async () => {
    const { user } = setup()
    const trigger = screen.getByRole('button', { name: /download credits/i })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    await user.tab()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menu', { name: 'Download credits' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Text' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Markdown' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('menuitem', { name: 'JSON' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Text' })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'JSON' })).toHaveFocus()
  })

  it('selects with Enter, closes, and returns focus to the button', async () => {
    const { user, onSelect } = setup()
    await user.click(screen.getByRole('button', { name: /download credits/i }))
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onSelect).toHaveBeenCalledWith('md')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download credits/i })).toHaveFocus()
  })

  it('renders link items for downloads', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: /download credits/i }))
    const item = screen.getByRole('menuitem', { name: 'JSON' })
    expect(item).toHaveAttribute('href', '/api/projects/1/credits?format=json')
    expect(item).toHaveAttribute('download')
  })

  it('closes on Escape and on a click outside', async () => {
    const { user } = setup()
    const trigger = screen.getByRole('button', { name: /download credits/i })
    await user.click(trigger)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    await user.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.click(document.body)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
