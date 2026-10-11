import { useEffect, useState } from 'react'

type Health = { status: string; version: string }
type BackendState = 'checking' | 'offline' | Health

export default function App() {
  const [backend, setBackend] = useState<BackendState>('checking')

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<Health>
      })
      .then(setBackend)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setBackend('offline')
        }
      })
    return () => controller.abort()
  }, [])

  let status: string
  if (backend === 'checking') {
    status = 'checking backend...'
  } else if (backend === 'offline') {
    status = 'backend offline'
  } else {
    status = `backend ${backend.status} (v${backend.version})`
  }

  return (
    <main>
      <h1>MCRAR</h1>
      <p data-testid="backend-status">{status}</p>
    </main>
  )
}
