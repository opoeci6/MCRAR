import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { linkify } from './linkify'

function renderText(text: string) {
  return render(<p data-testid="out">{linkify(text)}</p>)
}

function hrefs(): (string | null)[] {
  return screen.getAllByRole('link').map((link) => link.getAttribute('href'))
}

describe('linkify', () => {
  it('keeps text without a URL as it is', () => {
    renderText('Song by Jane (CC BY 4.0)')
    expect(screen.getByTestId('out')).toHaveTextContent('Song by Jane (CC BY 4.0)')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('links every URL and leaves the text around it alone', () => {
    renderText(
      '"CSboss" by X (https://www.jamendo.com/track/1036941), licensed under CC BY-SA 2.5 AR (https://creativecommons.org/licenses/by-sa/2.5/ar/)',
    )
    const links = screen.getAllByRole('link')
    expect(hrefs()).toEqual([
      'https://www.jamendo.com/track/1036941',
      'https://creativecommons.org/licenses/by-sa/2.5/ar/',
    ])
    for (const link of links) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noreferrer noopener')
    }
    // The closing parentheses and the comma stay outside the links.
    expect(links.map((link) => link.textContent)).toEqual([
      'https://www.jamendo.com/track/1036941 (opens in a new tab)',
      'https://creativecommons.org/licenses/by-sa/2.5/ar/ (opens in a new tab)',
    ])
    expect(screen.getByTestId('out').textContent).toMatch(/\(opens in a new tab\)\), licensed/)
    expect(screen.getByTestId('out').textContent).toMatch(/\(opens in a new tab\)\)$/)
  })

  it('leaves a trailing full stop or comma out of the link', () => {
    renderText('See https://example.org/a. Or https://example.org/b, please.')
    expect(hrefs()).toEqual(['https://example.org/a', 'https://example.org/b'])
  })

  it('links plain http, and a URL at the start of the text', () => {
    renderText('http://example.org/x and https://example.org/y')
    expect(hrefs()).toEqual(['http://example.org/x', 'https://example.org/y'])
  })

  it('gives the link a name that says it opens in a new tab', () => {
    renderText('https://example.org')
    expect(screen.getByRole('link', { name: /example\.org.*opens in a new tab/ })).toBeVisible()
  })

  it('never links other schemes', () => {
    renderText('javascript:alert(1) data:text/html,x ftp://example.org mailto:a@b.c')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('does not turn markup in the text into elements', () => {
    renderText('<img src=x onerror=alert(1)> https://example.org')
    expect(screen.getByTestId('out').querySelector('img')).toBeNull()
    expect(screen.getAllByRole('link')).toHaveLength(1)
  })

  it('returns nothing for an empty string', () => {
    expect(linkify('')).toEqual([])
  })
})
