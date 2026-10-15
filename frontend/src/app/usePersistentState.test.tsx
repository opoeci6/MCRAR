import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { clearPersistentState, usePersistentState } from './usePersistentState'

function Box() {
  const [text, setText] = usePersistentState('test.box', 'start')
  return <input aria-label="box" value={text} onChange={(event) => setText(event.target.value)} />
}

describe('usePersistentState', () => {
  beforeEach(clearPersistentState)

  it('keeps the value when the component is unmounted and mounted again', async () => {
    const first = render(<Box />)
    expect(screen.getByLabelText('box')).toHaveValue('start')
    await userEvent.clear(screen.getByLabelText('box'))
    await userEvent.type(screen.getByLabelText('box'), 'rain')
    first.unmount()
    render(<Box />)
    expect(screen.getByLabelText('box')).toHaveValue('rain')
  })
})
