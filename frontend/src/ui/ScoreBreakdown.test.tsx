import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScoreBreakdown } from './ScoreBreakdown'

describe('ScoreBreakdown', () => {
  it('describes each active term with its raw score, weight and contribution', () => {
    render(
      <ScoreBreakdown
        breakdown={{
          semantic: { raw: 0.8, weight: 0.5, contribution: 0.4 },
          bpm: { raw: 0.5, weight: 0.1, contribution: 0.05 },
        }}
      />,
    )
    expect(
      screen.getByText('Matches the description: score 0.80, weight 0.50, adds 0.40'),
    ).toBeInTheDocument()
    expect(screen.getByText('Tempo: score 0.50, weight 0.10, adds 0.05')).toBeInTheDocument()
    expect(screen.getByText('+0.40')).toBeInTheDocument()
  })

  it('marks an inactive term as not used', () => {
    render(<ScoreBreakdown breakdown={{ energy: { raw: null, weight: 0, contribution: 0 } }} />)
    expect(screen.getByText('Energy: not used in this search')).toBeInTheDocument()
    expect(screen.getByText('not used')).toBeInTheDocument()
  })

  it('lists the known terms first, in a fixed order, and keeps unknown ones', () => {
    render(
      <ScoreBreakdown
        breakdown={{
          energy: { raw: 0.1, weight: 0.1, contribution: 0.01 },
          novelty: { raw: 0.2, weight: 0.1, contribution: 0.02 },
          semantic: { raw: 0.9, weight: 0.5, contribution: 0.45 },
        }}
      />,
    )
    const rows = screen.getAllByRole('listitem').map((li) => li.textContent ?? '')
    expect(rows[0]).toContain('Matches the description')
    expect(rows[1]).toContain('Energy')
    expect(rows[2]).toContain('novelty')
  })
})
