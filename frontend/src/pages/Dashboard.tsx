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
  icon: string
  placeholder: boolean
}

const CONNECTOR_ROWS = [
  { name: 'PostgreSQL CRM', docs: '18,240' },
  { name: 'SharePoint', docs: '42,110' },
  { name: 'Email', docs: '9,804' },
  { name: 'Amazon S3', docs: '27,553' },
  { name: 'Salesforce', docs: '6,120' },
  { name: 'Oracle', docs: '11,002' },
  { name: 'Box', docs: '3,441' },
  { name: 'SAP', docs: '8,776' },
]

const INDEX_BARS = [
  { name: 'documents-v2', width: '66%' },
  { name: 'structured-v2', width: '22%' },
  { name: 'vector-v2', width: '12%' },
]

function PlaceholderBadge() {
  return (
    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      Placeholder
    </span>
  )
}

export function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncNotice, setSyncNotice] = useState<string | null>(null)

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
          title: 'Avg OpenSearch query time (last 24 hours)',
          value: formatAvgMs(stats.avg_query_time_ms),
          icon: '⏱️',
          placeholder: false,
        },
        {
          title: 'Total data ingested',
          value: formatBytes(stats.total_data_ingested_bytes),
          icon: '💾',
          placeholder: false,
        },
        {
          title: 'Total no. of docs indexed',
          value: stats.total_docs_indexed.toLocaleString(),
          icon: '📄',
          placeholder: false,
        },
        {
          title: 'Active connectors',
          value: stats.active_connectors.toLocaleString(),
          icon: '🔌',
          placeholder: stats.placeholders.active_connectors,
        },
        {
          title: 'Ingestion rate',
          value: formatDocsPerHour(stats.ingestion_rate_docs_per_hour),
          icon: '📥',
          placeholder: stats.placeholders.ingestion_rate_docs_per_hour,
        },
        {
          title: 'Last sync',
          value: stats.last_sync,
          icon: '🔄',
          placeholder: stats.placeholders.last_sync,
        },
        {
          title: 'p99 latency',
          value: '187 ms',
          icon: '📈',
          placeholder: true,
        },
        {
          title: 'Searches today',
          value: '3,841',
          icon: '🔍',
          placeholder: true,
        },
        {
          title: 'Total sources',
          value: '12',
          icon: '🗂️',
          placeholder: true,
        },
      ]
    : []

  return (
    <AppShell>
      <section className="space-y-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Dashboard</h1>
            <p className="mt-1 text-sm text-gray-500">Ops overview for this realm.</p>
          </div>
          <Button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        ) : null}

        {loading && !stats ? (
          <div className="flex flex-col items-center gap-4 py-16">
            <div className="spinner" />
            <p className="text-sm text-gray-400">Loading…</p>
          </div>
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {cards.map((card) => (
              <li key={card.title} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-base">
                    {card.icon}
                  </span>
                  {card.placeholder ? <PlaceholderBadge /> : null}
                </div>
                <p className="mt-3 text-xl font-bold text-gray-900">{card.value}</p>
                <p className="mt-1 text-xs text-gray-400">{card.title}</p>
              </li>
            ))}
          </ul>
        )}

        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-900">Connector status</h2>
            <PlaceholderBadge />
          </div>
          {syncNotice ? (
            <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-700">{syncNotice}</p>
          ) : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-gray-400">
                <tr>
                  <th className="px-4 py-2 font-medium">Connector</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Last sync</th>
                  <th className="px-4 py-2 font-medium">Indexed docs</th>
                  <th className="px-4 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {CONNECTOR_ROWS.map((row) => (
                  <tr key={row.name} className="border-t border-gray-100">
                    <td className="px-4 py-2 text-gray-900">{row.name}</td>
                    <td className="px-4 py-2 text-gray-500">Placeholder</td>
                    <td className="px-4 py-2 text-gray-500">—</td>
                    <td className="px-4 py-2 text-gray-500">{row.docs}</td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        className="text-sm text-indigo-600 hover:text-indigo-700"
                        onClick={() => setSyncNotice(`Sync is not connected for ${row.name}.`)}
                      >
                        Sync Now
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-gray-900">Index distribution</h2>
            <PlaceholderBadge />
          </div>
          <div className="space-y-3">
            {INDEX_BARS.map((bar) => (
              <div key={bar.name}>
                <div className="mb-1 flex justify-between text-xs text-gray-500">
                  <span>{bar.name}</span>
                  <span>{bar.width}</span>
                </div>
                <div className="h-2 rounded-full bg-gray-100">
                  <div className="h-2 rounded-full bg-indigo-600" style={{ width: bar.width }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </AppShell>
  )
}
