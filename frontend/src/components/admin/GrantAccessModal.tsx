import { useState } from 'react'

import { bulkFileAcl, type AdminFile, type AdminGroup, type AdminRole } from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { buildGrantImpact, ImpactPreview } from './ImpactPreview'
import { PermissionSelect } from './PermissionSelect'
import { PrincipalPicker, type PrincipalRef } from './PrincipalPicker'

type Props = {
  files: AdminFile[]
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

export function GrantAccessModal({ files, roles, groups, onClose, onDone, onError }: Props) {
  const [principals, setPrincipals] = useState<PrincipalRef[]>([])
  const [permission, setPermission] = useState<'viewer' | 'editor'>('viewer')
  const [mode, setMode] = useState<'upsert' | 'replace'>('upsert')
  const [confirmReplace, setConfirmReplace] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)

  const canConfirm =
    principals.length > 0 && (mode !== 'replace' || confirmReplace) && !busy

  async function onConfirm() {
    if (!canConfirm) return
    setBusy(true)
    try {
      const result = await bulkFileAcl({
        file_ids: files.map((f) => f.id),
        mode,
        confirm_replace: mode === 'replace' ? true : false,
        grants: principals.map((p) => ({
          principal_type: p.principal_type,
          principal_id: p.principal_id,
          permission,
        })),
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

  const impact = buildGrantImpact(
    mode,
    permission,
    principals.map((p) => p.name),
    files.length,
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-slate-700 bg-slate-950 p-5 shadow-xl">
        <h2 className="text-lg font-medium text-white">
          Grant access to {files.length} file{files.length === 1 ? '' : 's'}
        </h2>

        <div className="mt-3">
          <button
            type="button"
            className="text-sm text-sky-400 hover:text-sky-300"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Hide' : 'Show'} file list ({files.length})
          </button>
          {expanded ? (
            <ul className="mt-2 max-h-32 overflow-y-auto text-sm text-slate-300">
              {files.map((f) => (
                <li key={f.id} className="truncate">
                  {f.display_name}
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-2 flex flex-wrap gap-1">
              {files.slice(0, 4).map((f) => (
                <span
                  key={f.id}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-400"
                >
                  {f.display_name}
                </span>
              ))}
              {files.length > 4 ? (
                <span className="text-xs text-slate-500">+{files.length - 4} more</span>
              ) : null}
            </div>
          )}
        </div>

        <div className="mt-4 space-y-4">
          <PrincipalPicker
            roles={roles}
            groups={groups}
            value={principals}
            onChange={setPrincipals}
            disabled={busy}
          />
          <PermissionSelect value={permission} onChange={setPermission} disabled={busy} />

          <fieldset className="space-y-2">
            <legend className="text-xs font-medium uppercase tracking-wide text-slate-400">
              Mode
            </legend>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="grant-mode"
                checked={mode === 'upsert'}
                onChange={() => setMode('upsert')}
                disabled={busy}
              />
              Add or update access
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="grant-mode"
                checked={mode === 'replace'}
                onChange={() => setMode('replace')}
                disabled={busy}
              />
              Replace all access
            </label>
            {mode === 'replace' ? (
              <div className="space-y-2 rounded-md border border-amber-900/50 bg-amber-950/30 p-3">
                <p className="text-sm text-amber-200">
                  This removes other grants on each selected file.
                </p>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={confirmReplace}
                    onChange={(e) => setConfirmReplace(e.target.checked)}
                    disabled={busy}
                  />
                  I understand this removes other grants on each file
                </label>
              </div>
            ) : null}
          </fieldset>

          <ImpactPreview text={impact} />
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
