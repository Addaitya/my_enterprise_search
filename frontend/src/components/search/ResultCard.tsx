import type { SearchHit } from '../../api/search'
import { fileTypeEmoji, scorePillClass } from './fileType'

type ResultCardProps = {
  hit: SearchHit
  onSelect: (hit: SearchHit) => void
}

export function ResultCard({ hit, onSelect }: ResultCardProps) {
  const title = hit.display_name || hit.chunk_id
  return (
    <button
      type="button"
      onClick={() => onSelect(hit)}
      className="w-full rounded-xl border border-gray-200 bg-white p-4 text-left transition-all hover:border-indigo-300 hover:shadow-md fade-in"
    >
      <div className="flex gap-3">
        <span className="mt-0.5 shrink-0 text-2xl">{fileTypeEmoji(hit.meta_file_type)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h2 className="truncate text-sm font-semibold text-gray-900">{title}</h2>
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${scorePillClass(hit.score)}`}>
              {hit.score.toFixed(3)}
            </span>
          </div>
          <p className="mt-2 line-clamp-2 whitespace-pre-wrap text-sm text-gray-600">{hit.snippet}</p>
        </div>
      </div>
    </button>
  )
}
