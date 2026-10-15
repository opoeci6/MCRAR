import { describe, expect, it } from 'vitest'
import { hrefFor, parseHash } from './route'

describe('parseHash', () => {
  it('defaults to the search page', () => {
    for (const hash of ['', '#', '#/', '#/nonsense', '#/nonsense/12']) {
      expect(parseHash(hash)).toMatchObject({ page: 'search', subpath: [] })
    }
  })

  it('reads the page and passes on the rest of the path', () => {
    expect(parseHash('#/projects')).toMatchObject({ page: 'projects', subpath: [] })
    expect(parseHash('#/projects/12')).toMatchObject({ page: 'projects', subpath: ['12'] })
    expect(parseHash('#/library/jobs/ab%20cd')).toMatchObject({
      page: 'library',
      subpath: ['jobs', 'ab cd'],
    })
  })

  it('reads the query part', () => {
    const route = parseHash('#/search?q=rain%20piano&risk=green')
    expect(route.page).toBe('search')
    expect(route.params.get('q')).toBe('rain piano')
    expect(route.params.get('risk')).toBe('green')
  })
})

describe('hrefFor', () => {
  it('builds hashes that parse back', () => {
    expect(hrefFor('settings')).toBe('#/settings')
    expect(hrefFor('projects', [12])).toBe('#/projects/12')
    expect(hrefFor('search', [], { q: 'a b' })).toBe('#/search?q=a+b')
    expect(parseHash(hrefFor('projects', ['a b', 3]))).toMatchObject({ subpath: ['a b', '3'] })
  })
})
