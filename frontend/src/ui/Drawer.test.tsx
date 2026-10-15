import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Drawer } from './Drawer'
import { Menu, MenuItem } from './Menu'

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open details</button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Track details">
        <button>First action</button>
        <button>Second action</button>
      </Drawer>
    </>
  )
}

describe('Drawer', () => {
  it('is a labelled modal dialog that takes focus', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open details' }))
    const dialog = screen.getByRole('dialog', { name: 'Track details' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'First action' })).toHaveFocus()
  })

  it('keeps Tab and Shift+Tab inside the dialog', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open details' }))
    // Order: Close, First action, Second action.
    await user.tab()
    expect(screen.getByRole('button', { name: 'Second action' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Second action' })).toHaveFocus()
  })

  it('closes on Escape and returns focus to the opener', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open details' })
    await user.click(opener)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes with the close button', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open details' }))
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('lets Escape close an open menu first, without closing the drawer', async () => {
    const user = userEvent.setup()
    render(
      <Drawer open onClose={() => {}} title="With menu">
        <Menu label="Actions">
          <MenuItem>Do it</MenuItem>
        </Menu>
      </Drawer>,
    )
    await user.click(screen.getByRole('button', { name: /actions/i }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
