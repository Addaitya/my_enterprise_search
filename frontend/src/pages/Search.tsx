import { useState, type SubmitEvent } from 'react'

import { ApiError } from '../api/client'
import { downloadFileContent } from '../api/files'
import { searchFiles, type SearchHit, type SearchResponse } from '../api/search'
import { AppShell } from '../components/layout/AppShell'
import { EmptyState } from '../components/search/EmptyState'
import { FacetColumn } from '../components/search/FacetColumn'
import { HitDetails } from '../components/search/HitDetails'
import { ResultCard } from '../components/search/ResultCard'
import { Button } from '../components/ui/Button'
import { useHealth } from '../hooks/useHealth'

export function Search() {
  const { health, error: healthError } = useHealth()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)
  const [selected, setSelected] = useState<SearchHit | null>(null)
  const [showAsk, setShowAsk] = useState(false)

  async function runSearch(raw: string) {
    const q = raw.trim()
    if (!q) {
      setError('Enter a search query.')
      setResult(null)
      setSelected(null)
      return
    }

    setLoading(true)
    setError(null)
    setSelected(null)
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

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    void runSearch(query)
  }

  function onSuggest(text: string) {
    setQuery(text)
    void runSearch(text)
  }

  async function onOpen(hit: SearchHit) {
    if (!hit.file_id) {
      setError('This hit has no file_id to open.')
      return
    }
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
        <form className="flex gap-2" onSubmit={onSubmit}>
          <input
            className="search-glow w-full rounded-xl border-2 border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-indigo-400"
            placeholder="Search files…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
            aria-label="Search query"
          />
          <Button type="submit" disabled={loading || query.trim() === ''}>
            {loading ? 'Searching…' : 'Search'}
          </Button>
        </form>

        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-indigo-600 px-3 py-1 text-sm text-white">⚡ Hybrid</span>
          <button
            type="button"
            disabled
            className="cursor-not-allowed rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-400"
          >
            🔤 Keyword
          </button>
          <button
            type="button"
            disabled
            className="cursor-not-allowed rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-400"
          >
            🧠 Semantic
          </button>
          {result ? (
            <button
              type="button"
              onClick={() => setShowAsk((open) => !open)}
              className="rounded-full border border-gray-200 bg-white px-3 py-1 text-sm text-gray-700 hover:border-indigo-300"
            >
              {showAsk ? '🤖 Hide AI' : '🤖 Ask AI'}
            </button>
          ) : null}
        </div>

        {showAsk && result ? (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 text-sm text-gray-700 fade-in">
            Answer generation is not connected.
          </div>
        ) : null}

        {error ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex flex-col items-center gap-4 py-16">
            <div className="spinner" />
            <p className="text-sm text-gray-400">Running hybrid search…</p>
          </div>
        ) : null}

        {!loading && !result ? <EmptyState onSuggest={onSuggest} disabled={loading} /> : null}

        {!loading && result ? (
          <div className="flex flex-col gap-6 sm:flex-row">
            <FacetColumn />
            <div className="min-w-0 flex-1 space-y-3">
              <p className="text-sm text-gray-600">
                {result.total} hits · {result.took_ms} ms
              </p>
              {result.hits.length === 0 ? (
                <div className="py-16 text-center">
                  <div className="text-4xl">🔎</div>
                  <p className="mt-2 font-medium text-gray-600">No results found</p>
                  <p className="mt-1 text-sm text-gray-400">Try a different query.</p>
                </div>
              ) : (
                <ul className="space-y-3">
                  {result.hits.map((hit) => (
                    <li key={hit.chunk_id}>
                      <ResultCard hit={hit} onSelect={setSelected} />
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center gap-3 text-sm text-gray-500">
                <button type="button" disabled className="cursor-not-allowed rounded-lg border border-gray-200 px-3 py-1 opacity-50">
                  ← Prev
                </button>
                <span>
                  showing {result.hits.length} of {result.total}
                </span>
                <button type="button" disabled className="cursor-not-allowed rounded-lg border border-gray-200 px-3 py-1 opacity-50">
                  Next →
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <p className="text-xs text-gray-400">
          {health
            ? `API ${health.status} · realm ${health.realm} · index ${health.opensearch_index}`
            : healthError
              ? `API unreachable (${healthError}). Start the backend on :8000.`
              : 'Checking API…'}
        </p>
      </section>

      {selected ? (
        <HitDetails
          hit={selected}
          opening={openingId === selected.chunk_id}
          onClose={() => setSelected(null)}
          onOpen={(hit) => void onOpen(hit)}
        />
      ) : null}
    </AppShell>
  )
}
