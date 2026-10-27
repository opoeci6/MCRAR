import { vi } from 'vitest'

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type Reply = unknown | ((url: URL, init?: RequestInit) => unknown)

/** A route table key: `"GET /api/projects"`. The value is a body (200), a Response, or a function. */
export type Routes = Record<string, Reply>

/**
 * Replaces `fetch` with a stub that answers from `routes` (matched on method and path, without
 * the query). An unknown route is a 404 with a JSON `detail`. Returns the mock to inspect calls.
 */
export function stubApi(routes: Routes) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const key = `${init?.method ?? 'GET'} ${url.pathname}`
    if (!(key in routes)) return jsonResponse({ detail: `no stub for ${key}` }, 404)
    const reply = routes[key]
    const value = typeof reply === 'function' ? await reply(url, init) : reply
    return value instanceof Response ? value : jsonResponse(value)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

export const HEALTH = {
  status: 'ok',
  version: '0.1.0',
  catalog: { tracks: 42 },
  models_loaded: [],
  models: [],
  gpu: null,
}
