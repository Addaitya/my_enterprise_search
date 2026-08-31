import { useState } from 'react'

import {
  addGroupMembers,
  addRoleMembers,
  type AdminUser,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import {
  buildAddMembersImpact,
  ImpactPreview,
} from './ImpactPreview'
import { UserPicker } from './UserPicker'

type Props = {
  kind: 'role' | 'group'
  principalId: string
  principalName: string
  onClose: () => void
  onDone: (added: number, failed: { user_id: string; error: string }[]) => void
  onError: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function AddMembersModal({
  kind,
  principalId,
  principalName,
  onClose,
  onDone,
  onError,
}: Props) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [busy, setBusy] = useState(false)

  async function onConfirm() {
    if (users.length === 0 || busy) return
    setBusy(true)
    try {
      const ids = users.map((u) => u.id)
      const result =
        kind === 'role'
          ? await addRoleMembers(principalId, ids)
          : await addGroupMembers(principalId, ids)
      onDone(result.results.length, result.failed)
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
          Add members to {kind} {principalName}
        </h2>
        <div className="mt-4 space-y-4">
          <UserPicker value={users} onChange={setUsers} disabled={busy} />
          <ImpactPreview text={buildAddMembersImpact(kind, principalName, users.length)} />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void onConfirm()}
            disabled={busy || users.length === 0}
          >
            {busy ? 'Working…' : 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}
