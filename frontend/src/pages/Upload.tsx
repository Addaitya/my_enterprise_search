import { useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  MAX_UPLOAD_BYTES,
  resumableUpload,
  validateUploadFile,
  type UploadPhase,
  type UploadProgress,
} from '../api/uploads'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'

type FileUploadItem = {
  key: string
  file: File
  progress: UploadProgress
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / (1024 * 1024)).toFixed(2)} MiB`
}

function phaseLabel(phase: UploadPhase): string {
  switch (phase) {
    case 'idle':
      return 'Ready'
    case 'initiating':
      return 'Starting…'
    case 'uploading':
      return 'Uploading…'
    case 'completing':
      return 'Processing…'
    case 'completed':
      return 'Complete'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
  }
}

function idleProgress(sizeBytes = 0): UploadProgress {
  return {
    phase: 'idle',
    bytesReceived: 0,
    sizeBytes,
    uploadId: null,
    result: null,
    error: null,
  }
}

function makeItems(fileList: FileList | File[]): FileUploadItem[] {
  return Array.from(fileList).map((file, index) => {
    const error = validateUploadFile(file)
    return {
      key: `${file.name}:${file.size}:${file.lastModified}:${index}`,
      file,
      progress: error
        ? {
            ...idleProgress(file.size),
            phase: 'failed',
            error,
          }
        : idleProgress(file.size),
    }
  })
}

function isBusyPhase(phase: UploadPhase): boolean {
  return phase === 'initiating' || phase === 'uploading' || phase === 'completing'
}

function itemPercent(progress: UploadProgress): number {
  if (progress.sizeBytes <= 0) return 0
  return Math.min(100, Math.round((progress.bytesReceived / progress.sizeBytes) * 100))
}

export function Upload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [items, setItems] = useState<FileUploadItem[]>([])
  const [batchBusy, setBatchBusy] = useState(false)

  const updateItem = (key: string, progress: UploadProgress) => {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, progress } : item)))
  }

  const selectable = !batchBusy
  const uploadable = items.filter(
    (item) =>
      (item.progress.phase === 'idle' ||
        item.progress.phase === 'failed' ||
        item.progress.phase === 'cancelled') &&
      !validateUploadFile(item.file),
  )
  const canUpload = selectable && uploadable.length > 0
  const completedCount = items.filter((i) => i.progress.phase === 'completed').length
  const failedCount = items.filter((i) => i.progress.phase === 'failed').length

  const onFileChange = (list: FileList | null) => {
    if (batchBusy || !list?.length) return
    setItems(makeItems(list))
  }

  const removeItem = (key: string) => {
    if (batchBusy) return
    setItems((prev) => prev.filter((item) => item.key !== key))
  }

  const startUpload = async () => {
    if (!canUpload) return

    const controller = new AbortController()
    abortRef.current = controller
    setBatchBusy(true)

    const queue = items.filter(
      (item) =>
        (item.progress.phase === 'idle' ||
          item.progress.phase === 'failed' ||
          item.progress.phase === 'cancelled') &&
        !validateUploadFile(item.file),
    )

    try {
      for (const item of queue) {
        if (controller.signal.aborted) break
        try {
          await resumableUpload({
            file: item.file,
            signal: controller.signal,
            onProgress: (progress) => updateItem(item.key, progress),
          })
        } catch (e) {
          if (e instanceof DOMException && e.name === 'AbortError') {
            break
          }
          const message =
            e instanceof ApiError
              ? e.detail
              : e instanceof Error
                ? e.message
                : 'Upload failed'
          updateItem(item.key, {
            phase: 'failed',
            bytesReceived: 0,
            sizeBytes: item.file.size,
            uploadId: null,
            result: null,
            error: message,
          })
        }
      }
    } finally {
      abortRef.current = null
      setBatchBusy(false)
    }
  }

  const cancel = () => {
    abortRef.current?.abort()
  }

  const reset = () => {
    if (batchBusy) return
    setItems([])
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <AppShell>
      <section className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Upload files</h1>
          <p className="mt-2 text-sm text-gray-500">
            Select one or more PDF, TXT, or CSV files (each up to{' '}
            {MAX_UPLOAD_BYTES / (1024 * 1024)} MiB). Each file is uploaded with a
            resumable byte-range session, then chunked and indexed.
          </p>
        </div>

        <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-4">
          <label className="block text-sm text-gray-700" htmlFor="upload-files">
            Files
          </label>
          <input
            id="upload-files"
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.txt,.csv,application/pdf,text/plain,text/csv"
            disabled={batchBusy}
            className="block w-full text-sm text-gray-700 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-3 file:py-1.5 file:text-sm file:text-white hover:file:bg-indigo-700 disabled:opacity-50"
            onChange={(e) => onFileChange(e.target.files)}
          />
          {items.length > 0 ? (
            <p className="text-xs text-gray-400">
              {items.length} selected
              {completedCount > 0 ? ` · ${completedCount} complete` : ''}
              {failedCount > 0 ? ` · ${failedCount} failed` : ''}
            </p>
          ) : (
            <p className="text-sm text-gray-400">No files selected.</p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void startUpload()} disabled={!canUpload}>
            {batchBusy
              ? 'Uploading…'
              : uploadable.length > 1
                ? `Upload ${uploadable.length} files`
                : 'Upload'}
          </Button>
          {batchBusy ? <Button onClick={cancel}>Cancel</Button> : null}
          {!batchBusy && items.length > 0 ? <Button onClick={reset}>Clear</Button> : null}
        </div>

        {items.length > 0 ? (
          <ul className="space-y-3">
            {items.map((item) => {
              const { progress, file, key } = item
              const percent = itemPercent(progress)
              const busy = isBusyPhase(progress.phase)
              return (
                <li key={key} className="space-y-2 rounded-xl border border-gray-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-900">{file.name}</p>
                      <p className="text-xs text-gray-400">
                        {formatBytes(file.size)} · {phaseLabel(progress.phase)}
                        {busy || progress.phase === 'completed'
                          ? ` · ${formatBytes(progress.bytesReceived)} / ${formatBytes(progress.sizeBytes)} (${percent}%)`
                          : null}
                      </p>
                    </div>
                    {!batchBusy && progress.phase !== 'completed' ? (
                      <button
                        type="button"
                        className="shrink-0 text-xs text-rose-600 hover:text-rose-700"
                        onClick={() => removeItem(key)}
                      >
                        Remove
                      </button>
                    ) : null}
                  </div>

                  {(busy || progress.phase === 'completed') && (
                    <div className="h-1.5 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className={`h-full transition-[width] duration-150 ${
                          progress.phase === 'completed' ? 'bg-emerald-600' : 'bg-indigo-600'
                        }`}
                        style={{
                          width: `${progress.phase === 'initiating' ? 2 : percent}%`,
                        }}
                      />
                    </div>
                  )}

                  {progress.error ? (
                    <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700" role="alert">
                      {progress.error}
                    </p>
                  ) : null}

                  {progress.result ? (
                    <div className="space-y-1 text-xs text-gray-500">
                      <p>
                        File id{' '}
                        <span className="font-mono text-gray-700">{progress.result.id}</span>
                        {' · '}
                        {progress.result.chunk_count} chunk
                        {progress.result.chunk_count === 1 ? '' : 's'}
                      </p>
                      <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700">
                        No ACL assigned — not searchable until an admin grants access.
                      </p>
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ul>
        ) : null}
      </section>
    </AppShell>
  )
}
