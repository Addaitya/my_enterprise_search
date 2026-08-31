import { useState } from 'react'

import { bulkFileAcl, type AdminFile, type AdminGroup, type AdminRole } from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { buildRevokeImpact, ImpactPreview } from './ImpactPreview'
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

export function RevokeAccessModal({ files, roles, groups, onClose, onDone, onError }: Props) {
  const [principals, setPrincipals] = useState<PrincipalRef[]>([])
  const [busy, setBusy] = useState(false)

  const canConfirm = principals.length > 0 && !busy

  async function onConfirm() {
    if (!canConfirm) return
    setBusy(true)
    try {
      const result = await bulkFileAcl({
        file_ids: files.map((f) => f.id),
        mode: 'revoke',
        grants: principals.map((p) => ({
          principal_type: p.principal_type,
          principal_id: p.principal_id,
          permission: 'viewer',
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-slate-700 bg-slate-950 p-5 shadow-xl">
        <h2 className="text-lg font-medium text-white">
          Revoke access from {files.length} file{files.length === 1 ? '' : 's'}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Remove these roles/groups from selected files
        </p>

        <div className="mt-4 space-y-4">
          <PrincipalPicker
            roles={roles}
            groups={groups}
            value={principals}
            onChange={setPrincipals}
            disabled={busy}
          />
          <ImpactPreview
            text={buildRevokeImpact(
              principals.map((p) => p.name),
              files.length,
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
