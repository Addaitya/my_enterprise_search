import { useMemo, useState } from 'react'

import {
  addGroupMembers,
  addRoleMembers,
  type AdminGroup,
  type AdminRole,
  type AdminUser,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import {
  buildAddMembersImpact,
  ImpactPreview,
} from './ImpactPreview'
import { GroupPicker } from './GroupPicker'
import { RolePicker } from './RolePicker'

type Props = {
  kind: 'role' | 'group'
  users: AdminUser[]
  roles: AdminRole[]
  groups: AdminGroup[]
  onClose: () => void
  onDone: (added: number, failed: { user_id: string; error: string }[], targetName: string) => void
  onError: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function BulkAddToPrincipalModal({
  kind,
  users,
  roles,
  groups,
  onClose,
  onDone,
  onError,
}: Props) {
  const [selectedNames, setSelectedNames] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const target = useMemo(() => {
    const name = selectedNames[0]
    if (!name) return null
    if (kind === 'role') {
      const role = roles.find((r) => r.name === name)
      return role ? { id: role.id, name: role.name } : null
    }
    const group = groups.find((g) => g.name === name)
    return group ? { id: group.id, name: group.name } : null
  }, [kind, selectedNames, roles, groups])

  async function onConfirm() {
    if (!target || busy) return
    setBusy(true)
    try {
      const ids = users.map((u) => u.id)
      const result =
        kind === 'role'
          ? await addRoleMembers(target.id, ids)
          : await addGroupMembers(target.id, ids)
      onDone(result.results.length, result.failed, target.name)
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
          Add {users.length} user{users.length === 1 ? '' : 's'} to a {kind}
        </h2>
        <div className="mt-3 flex flex-wrap gap-1">
          {users.slice(0, 6).map((u) => (
            <span
              key={u.id}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-400"
            >
              {u.username}
            </span>
          ))}
          {users.length > 6 ? (
            <span className="text-xs text-slate-500">+{users.length - 6} more</span>
          ) : null}
        </div>
        <div className="mt-4 space-y-4">
          {kind === 'role' ? (
            <RolePicker
              roles={roles}
              value={selectedNames}
              onChange={setSelectedNames}
              disabled={busy}
              single
              label="Role"
            />
          ) : (
            <GroupPicker
              groups={groups}
              value={selectedNames}
              onChange={setSelectedNames}
              disabled={busy}
              single
              label="Group"
            />
          )}
          <ImpactPreview
            text={
              target
                ? buildAddMembersImpact(kind, target.name, users.length)
                : `Select a ${kind} to assign.`
            }
          />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void onConfirm()}
            disabled={busy || !target}
          >
            {busy ? 'Working…' : 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}
