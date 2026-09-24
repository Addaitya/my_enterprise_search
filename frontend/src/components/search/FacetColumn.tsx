const SECTIONS = ['Domain', 'File Type', 'Source', 'Language']

export function FacetColumn() {
  return (
    <aside className="w-full shrink-0 sm:w-60">
      <div className="rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-3 py-2 text-sm font-semibold text-gray-900">
          Filters
        </div>
        {SECTIONS.map((name) => (
          <div key={name} className="border-b border-gray-100 px-3 py-2 last:border-b-0">
            <div className="text-xs font-medium text-gray-700">{name}</div>
            <p className="mt-1 text-xs text-gray-400">Not available</p>
          </div>
        ))}
      </div>
    </aside>
  )
}
