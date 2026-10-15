import { describe, expect, it, vi } from 'vitest'
import { jsonResponse, stubApi } from '../test/fetch'
import { ApiError, buildQuery, errorDetail, request } from './client'
import {
  deleteRating,
  getHealth,
  listTracks,
  projectCreditsUrl,
  putProjectItem,
  search,
  setSecret,
  trackCreditsUrl,
  trackStreamUrl,
} from './endpoints'

describe('errorDetail', () => {
  it('uses a string detail as it is', () => {
    expect(errorDetail(404, { detail: 'no track with id 9' })).toBe('no track with id 9')
  })

  it('falls back to a generic message without a usable detail', () => {
    expect(errorDetail(500, undefined)).toBe('The request failed (HTTP 500)')
    expect(errorDetail(500, { detail: '   ' })).toBe('The request failed (HTTP 500)')
    expect(errorDetail(502, 'text')).toBe('The request failed (HTTP 502)')
  })

  it('reduces a list of validation errors to where and what, never the input', () => {
    const body = {
      detail: [{ loc: ['body', 'limit'], msg: 'must be at most 100', input: 'sk-secret-value' }],
    }
    const text = errorDetail(422, body)
    expect(text).toBe('limit: must be at most 100')
    expect(text).not.toContain('sk-secret-value')
  })
})

describe('request', () => {
  it('returns parsed JSON and sends JSON bodies with a content type', async () => {
    const mock = stubApi({ 'POST /api/search': { items: [] } })
    const result = await request<{ items: unknown[] }>('POST', '/api/search', {
      body: { text: 'rain' },
    })
    expect(result).toEqual({ items: [] })
    const [url, init] = mock.mock.calls[0] ?? []
    expect(url).toBe('/api/search')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe('{"text":"rain"}')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
  })

  it('returns undefined for 204', async () => {
    stubApi({ 'DELETE /api/projects/3': new Response(null, { status: 204 }) })
    await expect(request('DELETE', '/api/projects/3')).resolves.toBeUndefined()
  })

  it('throws an ApiError with the detail of a JSON error body', async () => {
    stubApi({ 'GET /api/tracks/9': jsonResponse({ detail: 'no track with id 9' }, 404) })
    const error = await request('GET', '/api/tracks/9').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, detail: 'no track with id 9', message: 'no track with id 9' })
  })

  it('throws a generic ApiError for a non-JSON error body', async () => {
    stubApi({ 'GET /api/health': new Response('<h1>Bad gateway</h1>', { status: 502 }) })
    const error = await request('GET', '/api/health').catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 502, detail: 'The request failed (HTTP 502)' })
  })

  it('treats a 200 that is not JSON as an unexpected response', async () => {
    stubApi({ 'GET /api/health': new Response('<!doctype html>', { status: 200 }) })
    const error = await request('GET', '/api/health').catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 200, detail: expect.stringContaining('could not read') })
  })

  it('turns a network failure into an ApiError with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = await request('GET', '/api/health').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 0, detail: "Couldn't reach the MCRAR backend" })
  })

  it('passes an abort through untouched', async () => {
    const abort = new DOMException('aborted', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort))
    await expect(request('GET', '/api/health')).rejects.toBe(abort)
  })
})

describe('buildQuery', () => {
  it('skips empty values and repeats arrays', () => {
    expect(buildQuery({ a: 1, b: undefined, c: null, d: ['x', 'y'], e: false })).toBe(
      '?a=1&d=x&d=y&e=false',
    )
    expect(buildQuery({})).toBe('')
    expect(buildQuery(undefined)).toBe('')
  })
})

describe('endpoints', () => {
  it('builds the URLs the pages link to', () => {
    expect(trackStreamUrl(7)).toBe('/api/tracks/7/stream')
    expect(trackCreditsUrl(7)).toBe('/api/tracks/7/credits?format=txt')
    expect(projectCreditsUrl(12)).toBe('/api/projects/12/credits?format=md')
    expect(projectCreditsUrl(12, 'json')).toBe('/api/projects/12/credits?format=json')
  })

  it('sends the right method, path and query', async () => {
    const mock = stubApi({
      'GET /api/health': { status: 'ok' },
      'GET /api/tracks': { items: [] },
      'POST /api/search': { items: [] },
      'PUT /api/projects/2/items/5': { note: null },
      'DELETE /api/ratings': new Response(null, { status: 204 }),
    })
    await getHealth()
    await listTracks({ source: 'local', limit: 10 })
    await search({ text: 'calm piano', filters: { max_risk: 'green' } })
    await putProjectItem(2, 5, 'for the intro')
    await deleteRating({ text: 'calm piano', track_id: 5 })
    const calls = mock.mock.calls.map(([url, init]) => `${init?.method} ${url}`)
    expect(calls).toEqual([
      'GET /api/health',
      'GET /api/tracks?source=local&limit=10',
      'POST /api/search',
      'PUT /api/projects/2/items/5',
      'DELETE /api/ratings',
    ])
    const putBody = mock.mock.calls[3]?.[1]?.body
    expect(putBody).toBe('{"note":"for the intro"}')
    expect(mock.mock.calls[4]?.[1]?.body).toBe('{"text":"calm piano","track_id":5}')
  })

  it('never puts a secret value in an error', async () => {
    stubApi({
      'PUT /api/secrets/jamendo_client_id': jsonResponse(
        { detail: 'value must be 1 to 4096 characters' },
        422,
      ),
    })
    const error = await setSecret('jamendo_client_id', 'abc123-secret').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const dump = JSON.stringify(error) + String((error as Error).message) + String((error as Error).stack)
    expect(dump).not.toContain('abc123-secret')
  })
})
