import { strings } from '../strings'

/**
 * A failed API call. `detail` is the `detail` string of the backend's JSON error body, or a
 * generic message when there is none. `status` is the HTTP status, or 0 when the backend could
 * not be reached at all.
 *
 * It never carries the request (URL query, headers or body): the settings page sends secrets,
 * and an error shown in a toast or logged must not be able to repeat one.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[]

export interface RequestOptions {
  /** JSON-encoded as the request body. */
  body?: unknown
  /** Sent as multipart form data (for uploads). Wins over `body`. */
  form?: FormData
  /** Appended to the path; `null` and `undefined` are skipped, arrays are repeated. */
  query?: Record<string, QueryValue>
  signal?: AbortSignal
}

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/** `?a=1&b=x&b=y` for the given values (empty string when nothing is set). */
export function buildQuery(query: Record<string, QueryValue> | undefined): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value == null) continue
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item))
    } else {
      params.append(key, String(value))
    }
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The message of an error response. A string `detail` is used as is. A list of validation
 * problems (FastAPI's own 422 shape) is reduced to "where: what"; the `input` echo that FastAPI
 * adds is deliberately dropped.
 */
export function errorDetail(status: number, body: unknown): string {
  if (isRecord(body)) {
    const { detail } = body
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const parts = detail.flatMap((entry: unknown) => {
        if (!isRecord(entry) || typeof entry.msg !== 'string') return []
        const where = Array.isArray(entry.loc)
          ? entry.loc.filter((p) => p !== 'body').join('.')
          : ''
        return [where ? `${where}: ${entry.msg}` : entry.msg]
      })
      if (parts.length > 0) return parts.join('; ')
    }
  }
  return strings.errors.generic(status)
}

/** The parsed JSON body; `undefined` when the body is empty; `invalid` when it is not JSON. */
async function readJson(response: Response): Promise<{ data: unknown; invalid: boolean }> {
  const text = await response.text()
  if (!text) return { data: undefined, invalid: false }
  try {
    return { data: JSON.parse(text) as unknown, invalid: false }
  } catch {
    return { data: undefined, invalid: true }
  }
}

/**
 * Calls the API and returns the parsed JSON. 204 (and an empty body) give `undefined`. A non-2xx
 * response throws {@link ApiError}; a network failure throws an `ApiError` with status 0. An
 * aborted request rejects with the browser's `AbortError`, untouched.
 */
export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(path + buildQuery(options.query), {
      method,
      headers,
      body,
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, strings.errors.network)
  }

  if (!response.ok) {
    const { data } = await readJson(response)
    throw new ApiError(response.status, errorDetail(response.status, data))
  }
  if (response.status === 204) return undefined as T
  const { data, invalid } = await readJson(response)
  // A 200 that is not JSON is not our API (for example a static server answering with a page).
  if (invalid) throw new ApiError(response.status, strings.errors.unexpectedResponse)
  return data as T
}

/** True for the `AbortError` of a cancelled request (not a real failure). */
export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
