import { useEffect, useState } from 'react'

import {
  bulkFileAcl,
  listAdminFiles,
  type AdminFile,
  type AdminGroup,
  type AdminRole,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { buildGrantImpact, ImpactPreview } from './ImpactPreview'
import { PermissionSelect } from './PermissionSelect'
import type { PrincipalRef } from './PrincipalPicker'
import { PrincipalPicker } from './PrincipalPicker'
import { inputClass, labelClass } from './styles'

type Props = {
  lockedPrincipal: PrincipalRef
  roles: AdminRole[]
  groups: AdminGroup[]
  onClose: () => void
  onDone: (jobIds: string[], failed: { file_id: string; error: string }[]) => void
  onError: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function GrantFilesModal({
  lockedPrincipal,
  roles,
  groups,
  onClose,
  onDone,
  onError,
}: Props) {
  const [files, setFiles] = useState<AdminFile[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [q, setQ] = useState('')
  const [permission, setPermission] = useState<'viewer' | 'editor'>('viewer')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const list = await listAdminFiles({ limit: 100, offset: 0, q: q || undefined })
        if (!cancelled) setFiles(list.items)
      } catch (err) {
        if (!cancelled) onError(errMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedFiles = files.filter((f) => selected.has(f.id))
  const canConfirm = selectedFiles.length > 0 && !busy

  async function onConfirm() {
    if (!canConfirm) return
    setBusy(true)
    try {
      const result = await bulkFileAcl({
        file_ids: selectedFiles.map((f) => f.id),
        mode: 'upsert',
        grants: [
          {
            principal_type: lockedPrincipal.principal_type,
            principal_id: lockedPrincipal.principal_id,
            permission,
          },
        ],
      })
      const jobIds = result.results
        .map((r) => r.acl_job_id)
        .filter((id): id is string => Boolean(id))
      onDone(jobIds, result.failed)
      onClose()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-gray-200 bg-white p-5 shadow-2xl">
        <h2 className="text-lg font-medium text-gray-900">Grant files…</h2>
        <div className="mt-4 space-y-4">
          <PrincipalPicker
            roles={roles}
            groups={groups}
            value={[lockedPrincipal]}
            onChange={() => undefined}
            locked={lockedPrincipal}
          />
          <PermissionSelect value={permission} onChange={setPermission} disabled={busy} />
          <label className={labelClass}>
            Search files
            <input
              className={inputClass}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter by name"
              disabled={busy}
            />
          </label>
          <div className="max-h-48 overflow-y-auto rounded-md border border-gray-200">
            {loading ? <p className="px-3 py-2 text-sm text-gray-400">Loading…</p> : null}
            {files.map((file) => (
              <label
                key={file.id}
                className="flex cursor-pointer items-center gap-2 border-b border-gray-100 px-3 py-2 text-sm text-gray-600 last:border-0 hover:bg-white"
              >
                <input
                  type="checkbox"
                  checked={selected.has(file.id)}
                  onChange={() => toggle(file.id)}
                  disabled={busy}
                />
                <span className="truncate">{file.display_name}</span>
              </label>
            ))}
            {!loading && files.length === 0 ? (
              <p className="px-3 py-2 text-sm text-gray-400">No files</p>
            ) : null}
          </div>
          <ImpactPreview
            text={buildGrantImpact(
              'upsert',
              permission,
              [lockedPrincipal.name],
              selectedFiles.length || 0,
            )}
          />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void onConfirm()} disabled={!canConfirm}>
            {busy ? 'Working…' : 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}
