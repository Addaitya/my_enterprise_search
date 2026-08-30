import { useState, type SubmitEvent } from 'react'

import { ApiError } from '../api/client'
import { downloadFileContent } from '../api/files'
import { searchFiles, type SearchHit, type SearchResponse } from '../api/search'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'
import { useHealth } from '../hooks/useHealth'

function formatScore(score: number): string {
  return score.toFixed(3)
}

function hitTitle(hit: SearchHit): string {
  return hit.display_name || hit.chunk_id
}

export function Search() {
  const { health, error: healthError } = useHealth()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)

  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const q = query.trim()
    if (!q) {
      setError('Enter a search query.')
      setResult(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const response = await searchFiles(q, 10)
      setResult(response)
    } catch (err) {
      setResult(null)
      if (err instanceof ApiError) {
        if (err.status === 400) {
          setError(err.detail || 'Invalid query.')
        } else if (err.status === 502) {
          setError(`Search backend error: ${err.detail}`)
        } else if (err.status === 503) {
          setError(`Search unavailable: ${err.detail}`)
        } else {
          setError(err.detail || `Request failed (${err.status})`)
        }
      } else {
        setError(err instanceof Error ? err.message : 'Search failed')
      }
    } finally {
      setLoading(false)
    }
  }

  async function onOpen(hit: SearchHit) {
    if (!hit.file_id) {
      setError('This hit has no file_id to open.')
      return
    }
    // proof-* fixtures use synthetic file_ids — skip MinIO open
    if (hit.file_id.startsWith('file-proof-') || hit.chunk_id.startsWith('proof-')) {
      setError('Proof fixture hits cannot be downloaded (no MinIO object).')
      return
    }
    setOpeningId(hit.chunk_id)
    setError(null)
    try {
      await downloadFileContent(hit.file_id, hit.display_name)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 403) setError('You do not have access to open this file.')
        else if (err.status === 404) setError('File not found for download.')
        else setError(err.detail || `Open failed (${err.status})`)
      } else {
        setError(err instanceof Error ? err.message : 'Open failed')
      }
    } finally {
      setOpeningId(null)
    }
  }

  return (
    <AppShell>
      <section id="search" className="space-y-4">
        <h1 className="text-2xl font-semibold text-white">Search company files</h1>
        <p className="text-slate-400">
          Hybrid keyword + semantic search with role and group access control.
        </p>
        <form className="flex gap-2" onSubmit={onSubmit}>
          <input
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            placeholder="Search files…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
            aria-label="Search query"
          />
          <Button type="submit" disabled={loading}>
            {loading ? 'Searching…' : 'Search'}
          </Button>
        </form>

        {error ? <p className="text-sm text-rose-400">{error}</p> : null}

        {result ? (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              {result.total} hit{result.total === 1 ? '' : 's'} for “{result.q}” · {result.took_ms}{' '}
              ms
            </p>
            {result.hits.length === 0 ? (
              <p className="text-sm text-slate-400">No results.</p>
            ) : (
              <ul className="space-y-3">
                {result.hits.map((hit) => (
                  <li
                    key={hit.chunk_id}
                    className="rounded-md border border-slate-800 bg-slate-950/60 px-3 py-3"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <h2 className="text-sm font-medium text-slate-100">{hitTitle(hit)}</h2>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="text-xs text-slate-500">score {formatScore(hit.score)}</span>
                        {hit.file_id ? (
                          <Button
                            type="button"
                            disabled={openingId === hit.chunk_id}
                            onClick={() => void onOpen(hit)}
                          >
                            {openingId === hit.chunk_id ? 'Opening…' : 'Open'}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-slate-300">{hit.snippet}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {hit.meta_file_type ?? 'chunk'} · {hit.chunk_id}
                      {hit.file_id ? ` · file ${hit.file_id}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        <p className="text-xs text-slate-500">
          {health
            ? `API ${health.status} · realm ${health.realm} · index ${health.opensearch_index}`
            : healthError
              ? `API unreachable (${healthError}). Start the backend on :8000.`
              : 'Checking API…'}
        </p>
      </section>
    </AppShell>
  )
}
