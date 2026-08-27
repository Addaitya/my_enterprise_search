import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'
import { useHealth } from '../hooks/useHealth'

export function Search() {
  const { health, error } = useHealth()

  return (
    <AppShell>
      <section id="search" className="space-y-4">
        <h1 className="text-2xl font-semibold text-white">Search company files</h1>
        <p className="text-slate-400">
          Hybrid keyword + semantic search with role and group access control.
        </p>
        <div className="flex gap-2">
          <input
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            placeholder="Search files…"
            disabled
          />
          <Button>Search</Button>
        </div>
        <p className="text-xs text-slate-500">
          {health
            ? `API ${health.status} · realm ${health.realm} · index ${health.opensearch_index}`
            : error
              ? `API unreachable (${error}). Start the backend on :8000.`
              : 'Checking API…'}
        </p>
      </section>
    </AppShell>
  )
}
