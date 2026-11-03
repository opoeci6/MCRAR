import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Select } from './Select'
import type { SelectOption } from './Select'
import { chooseOption, optionsOf } from '../test/select'

const OPTIONS: SelectOption[] = [
  { value: '', label: 'Any' },
  { value: 'apple', label: 'Apple' },
  { value: 'apricot', label: 'Apricot', disabled: true },
  { value: 'banana', label: 'Banana' },
  { value: 'cherry', label: 'Cherry' },
]

function Harness({
  options = OPTIONS,
  initial = 'banana',
  disabled,
  onValue,
}: {
  options?: SelectOption[]
  initial?: string
  disabled?: boolean
  onValue?: (value: string) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <Select
      label="Fruit"
      hint="Pick one."
      value={value}
      options={options}
      disabled={disabled}
      onValueChange={(next) => {
        setValue(next)
        onValue?.(next)
      }}
    />
  )
}

const box = () => screen.getByRole('combobox', { name: 'Fruit' })
const optionNames = () => screen.queryAllByRole('option').map((o) => o.textContent)
const activeName = () => document.getElementById(box().getAttribute('aria-activedescendant') ?? '')?.textContent

describe('Select', () => {
  it('shows the label and the chosen option, closed, with the combobox semantics', () => {
    render(<Harness />)
    expect(box()).toHaveTextContent('Banana')
    expect(box()).toHaveAttribute('aria-haspopup', 'listbox')
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    expect(screen.getByLabelText('Fruit')).toBe(box())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('is described by its hint', () => {
    render(<Harness />)
    expect(box()).toHaveAccessibleDescription('Pick one.')
  })

  it('opens by click, lists every option and marks the chosen one', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(box())
    expect(box()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('listbox', { name: 'Fruit' })).toBeInTheDocument()
    expect(box()).toHaveAttribute('aria-controls', screen.getByRole('listbox').id)
    expect(optionNames()).toEqual(['Any', 'Apple', 'Apricot', 'Banana', 'Cherry'])
    const selected = screen.getAllByRole('option').filter((o) => o.getAttribute('aria-selected') === 'true')
    expect(selected.map((o) => o.textContent)).toEqual(['Banana'])
    expect(activeName()).toBe('Banana')
    expect(screen.getByRole('option', { name: 'Apricot' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('closes on a second click on the control', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(box())
    await user.click(box())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('chooses an option by click and closes', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await chooseOption(user, 'Fruit', 'Cherry')
    expect(onValue).toHaveBeenCalledWith('cherry')
    expect(box()).toHaveTextContent('Cherry')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('does not call back when the chosen option is already the value', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await chooseOption(user, 'Fruit', 'Banana')
    expect(onValue).not.toHaveBeenCalled()
  })

  it('lists the option texts through the test helper and closes again', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(await optionsOf(user, 'Fruit')).toEqual(['Any', 'Apple', 'Apricot', 'Banana', 'Cherry'])
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it.each(['{Enter}', ' ', '{ArrowDown}', '{ArrowUp}', '{Alt>}{ArrowDown}{/Alt}'])(
    'opens from the keyboard with %j, on the chosen option',
    async (keys) => {
      const user = userEvent.setup()
      render(<Harness />)
      box().focus()
      await user.keyboard(keys)
      expect(box()).toHaveAttribute('aria-expanded', 'true')
      expect(activeName()).toBe('Banana')
    },
  )

  it('moves the active option with the arrow keys, skipping disabled ones, and chooses with Enter', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness initial="apple" onValue={onValue} />)
    box().focus()
    await user.keyboard('{ArrowDown}')
    expect(activeName()).toBe('Apple')
    await user.keyboard('{ArrowDown}')
    expect(activeName()).toBe('Banana')
    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(activeName()).toBe('Any')
    await user.keyboard('{ArrowUp}')
    expect(activeName()).toBe('Any')
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onValue).toHaveBeenCalledWith('banana')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(box()).toHaveFocus()
  })

  it('jumps with Home, End, PageUp and PageDown', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    box().focus()
    await user.keyboard('{Enter}{End}')
    expect(activeName()).toBe('Cherry')
    await user.keyboard('{Home}')
    expect(activeName()).toBe('Any')
    await user.keyboard('{PageDown}')
    expect(activeName()).toBe('Cherry')
    await user.keyboard('{PageUp}')
    expect(activeName()).toBe('Any')
  })

  it('chooses with Space', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    box().focus()
    await user.keyboard('{Enter}{ArrowDown} ')
    expect(onValue).toHaveBeenCalledWith('cherry')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape without a change, and does not let the key reach a parent', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    const parentKey = vi.fn()
    render(
      <div onKeyDown={(event) => parentKey(event.key)}>
        <Harness onValue={onValue} />
      </div>,
    )
    box().focus()
    await user.keyboard('{Enter}{ArrowDown}{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onValue).not.toHaveBeenCalled()
    expect(box()).toHaveTextContent('Banana')
    expect(parentKey).not.toHaveBeenCalledWith('Escape')
    // Closed, the key is left alone, so a Drawer around the select can use it.
    await user.keyboard('{Escape}')
    expect(parentKey).toHaveBeenCalledWith('Escape')
  })

  it('chooses the active option on Tab and lets the focus move on', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(
      <>
        <Harness onValue={onValue} />
        <button type="button">After</button>
      </>,
    )
    box().focus()
    await user.keyboard('{Enter}{ArrowDown}{Tab}')
    expect(onValue).toHaveBeenCalledWith('cherry')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus()
  })

  it('closes when the focus leaves, and when the page is clicked elsewhere', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(
      <>
        <Harness onValue={onValue} />
        <button type="button">Elsewhere</button>
      </>,
    )
    await user.click(box())
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onValue).not.toHaveBeenCalled()
  })

  it('jumps to the option that starts with the typed letters, open', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    box().focus()
    await user.keyboard('{Enter}c')
    expect(activeName()).toBe('Cherry')
    await user.keyboard('a')
    expect(activeName()).toBe('Cherry')
    await user.keyboard('{Escape}')
    expect(box()).toHaveTextContent('Banana')
  })

  it('skips disabled options in type-ahead', async () => {
    const user = userEvent.setup()
    render(<Harness initial="" />)
    box().focus()
    await user.keyboard('{Enter}apr')
    // "Apricot" is disabled: the prefix cannot land on it, so the active option stays on "Apple".
    expect(activeName()).toBe('Apple')
    await user.keyboard('{Escape}')
  })

  it('changes the value directly by type-ahead when closed, and cycles on a repeated letter', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    const options: SelectOption[] = [
      { value: 'a1', label: 'Alpha' },
      { value: 'b1', label: 'Beta' },
      { value: 'b2', label: 'Bravo' },
    ]
    render(<Harness options={options} initial="a1" onValue={onValue} />)
    box().focus()
    await user.keyboard('b')
    expect(onValue).toHaveBeenLastCalledWith('b1')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(box()).toHaveTextContent('Beta')
    // A pause resets the typed text; the same letter again moves to the next match.
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 2000)
    await user.keyboard('b')
    expect(onValue).toHaveBeenLastCalledWith('b2')
    expect(box()).toHaveTextContent('Bravo')
  })

  it('a prefix of several letters narrows the match', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    const options: SelectOption[] = [
      { value: 'b1', label: 'Beta' },
      { value: 'b2', label: 'Bravo' },
    ]
    render(<Harness options={options} initial="b1" onValue={onValue} />)
    box().focus()
    await user.keyboard('br')
    expect(onValue).toHaveBeenLastCalledWith('b2')
  })

  it('does not open, and is not interactive, when disabled', async () => {
    const user = userEvent.setup()
    render(<Harness disabled />)
    expect(box()).toBeDisabled()
    await user.click(box())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    box().focus()
    await user.keyboard('{Enter}{ArrowDown}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('does not choose a disabled option by click', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.click(box())
    await user.click(screen.getByRole('option', { name: 'Apricot' }))
    expect(onValue).not.toHaveBeenCalled()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('shows nothing selected, and opens on the first option, when the value matches none', async () => {
    const user = userEvent.setup()
    render(<Harness initial="missing" />)
    expect(box()).toHaveTextContent('')
    await user.click(box())
    expect(activeName()).toBe('Any')
    expect(screen.getAllByRole('option').filter((o) => o.getAttribute('aria-selected') === 'true')).toHaveLength(0)
  })

  it('a click on the label moves the focus to the control without opening it', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByText('Fruit'))
    expect(box()).toHaveFocus()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('opens upward when there is little room below the control', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    vi.spyOn(box(), 'getBoundingClientRect').mockReturnValue({
      top: 600,
      bottom: 636,
      left: 0,
      right: 300,
      width: 300,
      height: 36,
      x: 0,
      y: 600,
      toJSON: () => ({}),
    })
    await user.click(box())
    const list = screen.getByRole('listbox')
    expect(list.className).toMatch(/up/)
    expect(list.style.maxHeight).toBe('280px')
  })

  it('opens downward when there is room', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(box())
    expect(screen.getByRole('listbox').className).not.toMatch(/up/)
  })
})
