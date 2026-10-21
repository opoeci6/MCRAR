import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Combobox } from './Combobox'
import type { ComboboxOption } from './Combobox'

const OPTIONS: ComboboxOption[] = [
  { value: 'gpt-6-luna', label: null },
  { value: 'gpt-6-mini', label: 'GPT 6 Mini' },
  { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5' },
]

function Harness({
  options = OPTIONS,
  initial = '',
  onValue,
}: {
  options?: ComboboxOption[]
  initial?: string
  onValue?: (value: string) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <Combobox
      label="Model"
      hint="Pick one."
      value={value}
      options={options}
      onValueChange={(next) => {
        setValue(next)
        onValue?.(next)
      }}
      listLabel="Models"
      toggleLabel="Show models"
      emptyText="No matching models"
    />
  )
}

const input = () => screen.getByLabelText('Model')
const optionNames = () => screen.queryAllByRole('option').map((o) => o.textContent)

describe('Combobox', () => {
  it('stays closed until used and has the combobox semantics', () => {
    render(<Harness />)
    expect(input()).toHaveAttribute('role', 'combobox')
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    expect(input()).toHaveAttribute('aria-autocomplete', 'list')
    expect(input()).toHaveAttribute('aria-describedby')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('marks the option an empty field stands for', async () => {
    const user = userEvent.setup()
    render(
      <Combobox
        label="Model"
        value=""
        emptyValue="gpt-6-mini"
        options={OPTIONS}
        onValueChange={() => {}}
        listLabel="Models"
        toggleLabel="Show models"
        emptyText="No matching models"
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Show models' }))
    const selected = screen.getAllByRole('option').filter((o) => o.getAttribute('aria-selected') === 'true')
    expect(selected.map((o) => o.textContent)).toEqual(['gpt-6-mini GPT 6 Mini'])
  })

  it('filters the options by the typed text, ignoring case', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(input(), 'GPT')
    expect(screen.getByRole('listbox', { name: 'Models' })).toBeInTheDocument()
    expect(optionNames()).toEqual(['gpt-6-luna', 'gpt-6-mini GPT 6 Mini'])
    expect(input()).toHaveAttribute('aria-expanded', 'true')
    await user.clear(input())
    await user.type(input(), 'haiku')
    expect(optionNames()).toEqual(['claude-haiku-5-5 Claude Haiku 5.5'])
  })

  it('shows every option from the toggle, even after a value was chosen', async () => {
    const user = userEvent.setup()
    render(<Harness initial="gpt-6-luna" />)
    await user.click(screen.getByRole('button', { name: 'Show models' }))
    expect(input()).toHaveFocus()
    expect(optionNames()).toHaveLength(3)
    const current = screen.getByRole('option', { name: 'gpt-6-luna' })
    expect(current).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByRole('button', { name: 'Show models' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('shows every option when the input is clicked or opened with an arrow key', async () => {
    const user = userEvent.setup()
    render(<Harness initial="claude" />)
    await user.click(input())
    expect(optionNames()).toHaveLength(3)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await user.keyboard('{Alt>}{ArrowDown}{/Alt}')
    expect(optionNames()).toHaveLength(3)
    await user.keyboard('{Escape}')
    await user.keyboard('{ArrowDown}')
    expect(optionNames()).toHaveLength(3)
  })

  it('selects the active option with ArrowDown and Enter', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.click(input())
    expect(input()).not.toHaveAttribute('aria-activedescendant')
    await user.keyboard('{ArrowDown}')
    const first = screen.getByRole('option', { name: 'gpt-6-luna' })
    expect(input()).toHaveAttribute('aria-activedescendant', first.id)
    await user.keyboard('{ArrowDown}')
    const second = screen.getByRole('option', { name: /gpt-6-mini/ })
    expect(input()).toHaveAttribute('aria-activedescendant', second.id)
    await user.keyboard('{End}')
    expect(input()).toHaveAttribute('aria-activedescendant', screen.getAllByRole('option')[2]!.id)
    await user.keyboard('{Home}{ArrowUp}')
    expect(input()).toHaveAttribute('aria-activedescendant', screen.getAllByRole('option')[2]!.id)
    await user.keyboard('{Enter}')
    expect(onValue).toHaveBeenLastCalledWith('claude-haiku-5-5')
    expect(input()).toHaveValue('claude-haiku-5-5')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    expect(input()).not.toHaveAttribute('aria-activedescendant')
  })

  it('does not swallow Enter when nothing is active', async () => {
    const user = userEvent.setup()
    const submit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault())
    render(
      <form onSubmit={submit}>
        <Harness />
      </form>,
    )
    await user.type(input(), 'gpt{Enter}')
    expect(submit).toHaveBeenCalledTimes(1)
    expect(input()).toHaveValue('gpt')
  })

  it('closes on Escape without letting it bubble, and on Tab', async () => {
    const user = userEvent.setup()
    const outer = vi.fn()
    render(
      <div onKeyDown={(event) => event.key === 'Escape' && outer()}>
        <Harness />
      </div>,
    )
    await user.click(input())
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(outer).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(outer).toHaveBeenCalledTimes(1)
    await user.click(input())
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.tab()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('selects an option with the mouse and keeps the focus in the input', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.click(screen.getByRole('button', { name: 'Show models' }))
    await user.click(screen.getByRole('option', { name: /gpt-6-mini/ }))
    expect(onValue).toHaveBeenCalledWith('gpt-6-mini')
    expect(input()).toHaveValue('gpt-6-mini')
    expect(input()).toHaveFocus()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes when the focus leaves', async () => {
    const user = userEvent.setup()
    render(
      <>
        <Harness />
        <button type="button">Elsewhere</button>
      </>,
    )
    await user.click(input())
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('keeps free text that is not in the options', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.type(input(), 'my-finetune')
    expect(onValue).toHaveBeenLastCalledWith('my-finetune')
    expect(input()).toHaveValue('my-finetune')
    await user.tab()
    expect(input()).toHaveValue('my-finetune')
  })

  it('shows a single non-selectable row when nothing matches', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.type(input(), 'zzz')
    expect(optionNames()).toEqual(['No matching models'])
    const row = screen.getByRole('option')
    expect(row).toHaveAttribute('aria-disabled', 'true')
    await user.keyboard('{ArrowDown}{Enter}')
    expect(input()).not.toHaveAttribute('aria-activedescendant')
    expect(input()).toHaveValue('zzz')
    await user.click(row)
    expect(input()).toHaveValue('zzz')
  })

  it('is a plain text input without options', async () => {
    const user = userEvent.setup()
    render(<Harness options={[]} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(input()).not.toHaveAttribute('aria-expanded')
    expect(screen.getByRole('textbox', { name: 'Model' })).toBe(input())
    await user.type(input(), 'abc{ArrowDown}')
    expect(input()).toHaveValue('abc')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('never opens while disabled', async () => {
    const user = userEvent.setup()
    render(
      <Combobox
        label="Model"
        value=""
        options={OPTIONS}
        onValueChange={() => {}}
        listLabel="Models"
        toggleLabel="Show models"
        emptyText="No matching models"
        disabled
      />,
    )
    expect(screen.getByRole('button', { name: 'Show models' })).toBeDisabled()
    await user.click(input())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('opens upward when there is little room below the input', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    vi.spyOn(input(), 'getBoundingClientRect').mockReturnValue({
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
    await user.click(input())
    const list = screen.getByRole('listbox')
    expect(list.className).toMatch(/up/)
    expect(list.style.maxHeight).toBe('280px')
  })

  it('opens downward when there is room', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(input())
    expect(screen.getByRole('listbox').className).not.toMatch(/up/)
  })
})
