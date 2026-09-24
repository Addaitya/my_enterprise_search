const SUGGESTIONS = [
  'quarterly report',
  'customer data',
  'Q4 financial',
  'employee handbook',
  'server logs',
]

const SOURCES: { icon: string; label: string; real: boolean }[] = [
  { icon: '📄', label: 'PDF', real: true },
  { icon: '📃', label: 'TXT', real: true },
  { icon: '📊', label: 'CSV', real: true },
  { icon: '🗄️', label: 'Databases', real: false },
  { icon: '📧', label: 'Emails', real: false },
  { icon: '☁️', label: 'S3 / Blob', real: false },
]

type EmptyStateProps = {
  onSuggest: (query: string) => void
  disabled: boolean
}

export function EmptyState({ onSuggest, disabled }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center py-12 text-center fade-in">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-100 text-3xl">
        🔍
      </div>
      <h2 className="mt-4 text-xl font-bold text-gray-900">Search your enterprise data</h2>
      <p className="mt-2 max-w-sm text-sm text-gray-500">
        Hybrid keyword and semantic search over files you are allowed to open.
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            type="button"
            disabled={disabled}
            onClick={() => onSuggest(text)}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 transition-colors hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50"
          >
            {text}
          </button>
        ))}
      </div>
      <div className="mx-auto mt-8 grid max-w-lg grid-cols-3 gap-3 sm:grid-cols-6">
        {SOURCES.map((source) => (
          <div
            key={source.label}
            className="rounded-xl border border-gray-200 bg-white p-3 text-center"
          >
            <div className="text-xl">{source.icon}</div>
            <div className="mt-1 text-xs text-gray-500">{source.label}</div>
            {source.real ? null : (
              <div className="mt-1 text-[10px] text-gray-400">Not available</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
