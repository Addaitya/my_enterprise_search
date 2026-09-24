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
            <h1 className="text-xl font-semibold text-gray-900">View files</h1>
            <p className="mt-1 text-sm text-gray-500">Files you can open via your role or group grants.</p>
          </div>
          <Button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
        ) : null}

        {loading && items.length === 0 ? (
          <div className="flex flex-col items-center gap-4 rounded-xl border border-gray-200 bg-white py-16">
            <div className="spinner" />
            <p className="text-sm text-gray-400">Loading files…</p>
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white py-16 text-center">
            <div className="text-4xl">📁</div>
            <p className="mt-2 font-medium text-gray-600">No files visible yet</p>
            <p className="mt-1 text-sm text-gray-400">An admin must grant access.</p>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-gray-400">
              {total} file{total === 1 ? '' : 's'}
            </p>
            <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-200 text-xs text-gray-400">
                  <tr>
                    <th className="px-4 py-3 font-medium">Name</th>
                    <th className="px-4 py-3 font-medium">Type</th>
                    <th className="px-4 py-3 font-medium">Size</th>
                    <th className="px-4 py-3 font-medium">Id</th>
                    <th className="px-4 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((file) => (
                    <tr key={file.id} className="border-t border-gray-100">
                      <td className="max-w-xs truncate px-4 py-3 font-medium text-gray-900">{file.display_name}</td>
                      <td className="px-4 py-3 text-gray-600">{file.file_type}</td>
                      <td className="px-4 py-3 text-gray-600">{formatBytes(file.size_bytes)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">{shortId(file.id)}</td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          type="button"
                          disabled={downloadingId === file.id}
                          onClick={() => void onOpen(file)}
                        >
                          {downloadingId === file.id ? 'Opening…' : 'Open'}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </AppShell>
  )
}
