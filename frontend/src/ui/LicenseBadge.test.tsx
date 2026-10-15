import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
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
})
