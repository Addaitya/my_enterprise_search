import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { downloadFileContent, listFiles, type FileListItem } from '../api/files'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${(n / (1024 * 1024)).toFixed(2)} MiB`
}

function shortId(id: string): string {
  return id.slice(0, 8)
}

export function Files() {
  const [items, setItems] = useState<FileListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await listFiles(50, 0)
      setItems(response.items)
      setTotal(response.total)
    } catch (err) {
      setItems([])
      setTotal(0)
      if (err instanceof ApiError) {
        setError(err.detail || `Request failed (${err.status})`)
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load files')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onOpen(file: FileListItem) {
    setDownloadingId(file.id)
    setError(null)
    try {
      await downloadFileContent(file.id, file.display_name)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 403) setError('You do not have access to this file.')
        else if (err.status === 404) setError('File not found.')
        else setError(err.detail || `Download failed (${err.status})`)
      } else {
        setError(err instanceof Error ? err.message : 'Download failed')
      }
    } finally {
      setDownloadingId(null)
    }
  }

  return (
    <AppShell>
      <section className="space-y-4">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-white">View files</h1>
            <p className="mt-1 text-slate-400">Files you can open via your role or group grants.</p>
          </div>
          <Button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {error ? <p className="text-sm text-rose-400">{error}</p> : null}

        {loading && items.length === 0 ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-400">No files visible yet. An admin must grant access.</p>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-slate-500">
              {total} file{total === 1 ? '' : 's'}
            </p>
            <ul className="divide-y divide-slate-800 rounded-md border border-slate-800">
              {items.map((file) => (
                <li
                  key={file.id}
                  className="flex flex-wrap items-center justify-between gap-3 px-3 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{file.display_name}</p>
                    <p className="text-xs text-slate-500">
                      {file.file_type} · {formatBytes(file.size_bytes)} · {shortId(file.id)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    disabled={downloadingId === file.id}
                    onClick={() => void onOpen(file)}
                  >
                    {downloadingId === file.id ? 'Opening…' : 'Open'}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </AppShell>
  )
}
