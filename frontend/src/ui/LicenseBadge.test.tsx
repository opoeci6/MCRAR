import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LicenseBadge } from './LicenseBadge'

describe('LicenseBadge', () => {
  it.each([
    ['green', 'Safe'],
    ['amber', 'Check terms'],
    ['red', 'Restricted'],
    ['unknown', 'Unknown'],
  ] as const)('shows the %s risk as text, with the licence code', (risk, word) => {
    render(<LicenseBadge risk={risk} code="CC BY 4.0" />)
    expect(screen.getByText(word)).toBeInTheDocument()
    expect(screen.getByText('CC BY 4.0')).toBeInTheDocument()
  })

  it('says when there is no licence code', () => {
    render(<LicenseBadge risk="unknown" code={null} />)
    expect(screen.getByText('No licence')).toBeInTheDocument()
  })

  it('is plain text, not a button, when there is nothing more to show', () => {
    render(<LicenseBadge risk="green" code="CC0" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('opens the credit line and links from the keyboard', async () => {
    const user = userEvent.setup()
    render(
      <LicenseBadge
        risk="amber"
        code="CC BY-SA 4.0"
        attribution="Song by Jane (CC BY-SA 4.0)"
        licenseUrl="https://example.org/license"
        commercialLicenseUrl="https://example.org/buy"
      />,
    )
    const button = screen.getByRole('button', { name: /licence/i })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Song by Jane (CC BY-SA 4.0)')).not.toBeInTheDocument()

    await user.tab()
    expect(button).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Song by Jane (CC BY-SA 4.0)')).toBeInTheDocument()

    const licence = screen.getByRole('link', { name: /read the licence/i })
    expect(licence).toHaveAttribute('href', 'https://example.org/license')
    expect(licence).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
    expect(screen.getByRole('link', { name: /commercial licence/i })).toHaveAttribute(
      'href',
      'https://example.org/buy',
    )

    await user.keyboard('{Escape}')
    expect(screen.queryByText('Song by Jane (CC BY-SA 4.0)')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
  })

  describe('credit line', () => {
    const CREDIT =
      '"CSboss" by X (https://www.jamendo.com/track/1036941), licensed under CC BY-SA 2.5 AR (https://creativecommons.org/licenses/by-sa/2.5/ar/)'

    function setClipboard(clipboard: unknown) {
      Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
    }

    afterEach(() => {
      vi.useRealTimers()
      // @ts-expect-error back to jsdom's default: no clipboard
      delete navigator.clipboard
    })

    async function openBadge(user: ReturnType<typeof userEvent.setup>) {
      render(<LicenseBadge risk="amber" code="CC BY-SA 2.5" attribution={CREDIT} />)
      await user.click(screen.getByRole('button', { name: /licence/i }))
    }

    it('links the URLs in the credit line and keeps them clickable in the popover', async () => {
      const user = userEvent.setup()
      setClipboard(undefined)
      await openBadge(user)
      const links = screen.getAllByRole('link')
      expect(links.map((link) => link.getAttribute('href'))).toEqual([
        'https://www.jamendo.com/track/1036941',
        'https://creativecommons.org/licenses/by-sa/2.5/ar/',
      ])
      for (const link of links) {
        expect(link).toHaveAttribute('target', '_blank')
        expect(link).toHaveAttribute('rel', 'noreferrer noopener')
      }
      // A click inside the panel does not close it.
      await user.click(links[0])
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('copies the credit line and says "Copied", then clears it', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined)
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      vi.useFakeTimers({ shouldAdvanceTime: true })
      setClipboard({ writeText })
      await openBadge(user)

      await user.click(screen.getByRole('button', { name: 'Copy credit' }))
      expect(writeText).toHaveBeenCalledExactlyOnceWith(CREDIT)
      expect(await screen.findByText('Copied')).toBeInTheDocument()
      expect(screen.getByRole('status')).toHaveTextContent('Copied')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100)
      })
      expect(screen.queryByText('Copied')).not.toBeInTheDocument()
    })

    it('says so quietly when the copy is refused', async () => {
      const user = userEvent.setup()
      setClipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) })
      await openBadge(user)

      await user.click(screen.getByRole('button', { name: 'Copy credit' }))
      expect(await screen.findByText("Couldn't copy")).toBeInTheDocument()
      expect(screen.queryByText('Copied')).not.toBeInTheDocument()
    })

    it('has no copy button without a clipboard', async () => {
      const user = userEvent.setup()
      setClipboard(undefined)
      await openBadge(user)
      expect(screen.queryByRole('button', { name: 'Copy credit' })).not.toBeInTheDocument()
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
  })
})
