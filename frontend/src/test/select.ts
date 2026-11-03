import { screen, within } from '@testing-library/react'
import type { BoundFunctions, queries } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'

type Scope = Pick<BoundFunctions<typeof queries>, 'findByRole'>

/** The closed control of a `ui/Select`, found by its accessible name (the label). */
export function selectBox(label: string | RegExp, container: Scope = screen): Promise<HTMLElement> {
  return container.findByRole('combobox', { name: label })
}

/** The list a select controls; only present while it is open. */
function listOf(box: HTMLElement): HTMLElement {
  const list = box.ownerDocument.getElementById(box.getAttribute('aria-controls') ?? '')
  if (!list) throw new Error('The select is not open')
  return list
}

/** Opens a `ui/Select` by clicking it and clicks the option with this name. */
export async function chooseOption(
  user: Pick<UserEvent, 'click' | 'keyboard'>,
  label: string | RegExp,
  optionName: string | RegExp,
  container: Scope = screen,
): Promise<void> {
  const box = await selectBox(label, container)
  await user.click(box)
  await user.click(within(listOf(box)).getByRole('option', { name: optionName }))
}

/** The option texts of a `ui/Select`, read by opening it and closing it again (Escape). */
export async function optionsOf(
  user: Pick<UserEvent, 'click' | 'keyboard'>,
  label: string | RegExp,
  container: Scope = screen,
): Promise<string[]> {
  const box = await selectBox(label, container)
  await user.click(box)
  const texts = within(listOf(box))
    .getAllByRole('option')
    .map((option) => option.textContent ?? '')
  await user.keyboard('{Escape}')
  return texts
}
