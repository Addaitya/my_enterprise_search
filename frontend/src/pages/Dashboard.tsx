import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { getAdminStats, type AdminStats } from '../api/stats'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatAvgMs(n: number | null): string {
  if (n == null) return '—'
  const rounded = Math.round(n * 10) / 10
  if (Number.isInteger(rounded)) return `${rounded} ms`
  return `${rounded.toFixed(1)} ms`
}

function formatDocsPerHour(n: number): string {
  return `${n.toLocaleString()} docs/hr`
}

type Card = {
  title: string
  value: string
}

export function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setStats(await getAdminStats())
    } catch (err) {
      setStats(null)
      if (err instanceof ApiError) {
        setError(err.detail || `Request failed (${err.status})`)
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load stats')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const cards: Card[] = stats
    ? [
        {
          title: 'Avg query time (last 24 hours)',
          value: formatAvgMs(stats.avg_query_time_ms),
        },
        {
          title: 'Total data ingested',
          value: formatBytes(stats.total_data_ingested_bytes),
        },
        {
          title: 'Total no. of docs indexed',
          value: stats.total_docs_indexed.toLocaleString(),
        },
        {
          title: 'Active connectors',
          value: stats.active_connectors.toLocaleString(),
        },
        {
          title: 'Ingestion rate',
          value: formatDocsPerHour(stats.ingestion_rate_docs_per_hour),
        },
        {
          title: 'Last sync',
          value: stats.last_sync,
        },
      ]
    : []

  return (
    <AppShell>
      <section className="space-y-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
            <p className="mt-1 text-slate-400">Ops overview for this realm.</p>
          </div>
          <Button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {error ? <p className="text-sm text-rose-400">{error}</p> : null}

        {loading && !stats ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {cards.map((card) => (
              <li
                key={card.title}
                className="rounded-md border border-slate-800 bg-slate-950/60 px-4 py-4"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {card.title}
                </p>
                <p className="mt-2 text-2xl font-semibold text-white">{card.value}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </AppShell>
  )
}
