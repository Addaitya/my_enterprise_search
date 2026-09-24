import type { SearchHit } from '../../api/search'
import { Button } from '../ui/Button'
import { fileTypeEmoji, scorePillClass } from './fileType'

type HitDetailsProps = {
  hit: SearchHit
  opening: boolean
  onClose: () => void
  onOpen: (hit: SearchHit) => void
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="mt-1 break-all text-sm text-gray-900">{value}</div>
    </div>
  )
}

export function HitDetails({ hit, opening, onClose, onOpen }: HitDetailsProps) {
  const title = hit.display_name || hit.chunk_id
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="scrollbar-thin max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl fade-in"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-start gap-3">
          <span className="text-3xl">{fileTypeEmoji(hit.meta_file_type)}</span>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-bold text-gray-900">{title}</h2>
            <span className={`mt-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${scorePillClass(hit.score)}`}>
              {hit.score.toFixed(3)}
            </span>
          </div>
          <button type="button" className="text-gray-400 hover:text-gray-700" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Field label="Score" value={hit.score.toFixed(3)} />
          <Field label="Uploaded" value={hit.uploaded_at ?? '—'} />
          <Field label="Type" value={hit.meta_file_type ?? '—'} />
          <Field label="Chunk id" value={hit.chunk_id} />
          <Field label="File id" value={hit.file_id ?? '—'} />
        </div>
        <p className="mt-4 whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-sm text-gray-700">
          {hit.snippet}
        </p>
        {hit.file_id ? (
          <div className="mt-4">
            <Button type="button" disabled={opening} onClick={() => onOpen(hit)}>
              {opening ? 'Opening…' : 'Open'}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
