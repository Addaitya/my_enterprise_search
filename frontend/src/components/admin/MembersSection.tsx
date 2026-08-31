import { useCallback, useEffect, useState } from 'react'

import {
  listGroupMembers,
  listRoleMembers,
  removeGroupMembers,
  removeRoleMembers,
  type AdminUser,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { AddMembersModal } from './AddMembersModal'
import { TOKEN_REFRESH_NOTICE } from './ImpactPreview'
import { inputClass } from './styles'

type Props = {
  kind: 'role' | 'group'
  principalId: string
  principalName: string
  /** When false, hide manage actions (system / _empty groups). */
  manageable?: boolean
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function MembersSection({
  kind,
  principalId,
  principalName,
  manageable = true,
  onError,
  onNotice,
}: Props) {
  const [members, setMembers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [addOpen, setAddOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const list =
        kind === 'role'
          ? await listRoleMembers(principalId, 50, 0, appliedQuery || undefined)
          : await listGroupMembers(principalId, 50, 0, appliedQuery || undefined)
      setMembers(list.items)
      setTotal(list.total)
      setSelectedIds(new Set())
    } catch (err) {
      onError(errMessage(err))
    }
  }, [kind, principalId, appliedQuery, onError])

  useEffect(() => {
    void load()
  }, [load])

  function reload() {
    const next = query.trim()
    if (next === appliedQuery) {
      void load()
    } else {
      setAppliedQuery(next)
    }
  }

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (selectedIds.size === members.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(members.map((m) => m.id)))
    }
  }

  async function removeUsers(ids: string[]) {
    if (ids.length === 0) return
    const names = members
      .filter((m) => ids.includes(m.id))
      .map((m) => m.username)
      .join(', ')
    if (!window.confirm(`Remove ${names || ids.length + ' user(s)'} from ${principalName}?`)) {
      return
    }
    setBusy(true)
    try {
      const result =
        kind === 'role'
          ? await removeRoleMembers(principalId, ids)
          : await removeGroupMembers(principalId, ids)
      const n = result.results.length
      const k = result.failed.length
      onNotice(
        `Removed ${n} user${n === 1 ? '' : 's'} from ${principalName}. Failed: ${k}. ${
          n > 0 ? TOKEN_REFRESH_NOTICE : ''
        }`.trim(),
      )
      if (k > 0) {
        onError(result.failed.map((f) => f.error).join('; '))
      }
      await load()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-md border border-slate-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium text-white">Members — {principalName}</h2>
        {manageable ? (
          <Button type="button" onClick={() => setAddOpen(true)} disabled={busy}>
            Add members…
          </Button>
        ) : null}
      </div>

      {!manageable ? (
        <p className="text-sm text-slate-500">Members of this system group cannot be managed here.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <input
              className={`${inputClass} max-w-xs`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search members"
            />
            <Button type="button" onClick={() => reload()} disabled={busy}>
              Reload
            </Button>
            {selectedIds.size > 0 ? (
              <Button
                type="button"
                onClick={() => void removeUsers([...selectedIds])}
                disabled={busy}
              >
                Remove selected… ({selectedIds.size})
              </Button>
            ) : null}
          </div>

          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-2">
                  <input
                    type="checkbox"
                    checked={members.length > 0 && selectedIds.size === members.length}
                    onChange={toggleAll}
                    disabled={busy || members.length === 0}
                  />
                </th>
                <th className="py-2 pr-3">Username</th>
                <th className="py-2 pr-3">Email</th>
                <th className="py-2 pr-3">Enabled</th>
                <th className="py-2 pr-3">Roles</th>
                <th className="py-2 pr-3">Groups</th>
                <th className="py-2"> </th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-t border-slate-800">
                  <td className="py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(m.id)}
                      onChange={() => toggle(m.id)}
                      disabled={busy}
                    />
                  </td>
                  <td className="py-2 pr-3 text-slate-100">{m.username}</td>
                  <td className="py-2 pr-3 text-slate-300">{m.email || '—'}</td>
                  <td className="py-2 pr-3 text-slate-300">{m.enabled ? 'yes' : 'no'}</td>
                  <td className="py-2 pr-3 text-slate-300">{m.role_names.join(', ') || '—'}</td>
                  <td className="py-2 pr-3 text-slate-300">{m.group_names.join(', ') || '—'}</td>
                  <td className="py-2">
                    <button
                      type="button"
                      className="text-rose-400 hover:text-rose-300"
                      disabled={busy}
                      onClick={() => void removeUsers([m.id])}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {members.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-3 text-slate-500">
                    No members yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          {total > members.length ? (
            <p className="text-xs text-slate-500">
              Showing {members.length} of {total}
            </p>
          ) : null}
        </>
      )}

      {addOpen && manageable ? (
        <AddMembersModal
          kind={kind}
          principalId={principalId}
          principalName={principalName}
          onClose={() => setAddOpen(false)}
          onDone={(added, failed) => {
            onNotice(
              `Added ${added} users to ${principalName}. Failed: ${failed.length}. ${
                added > 0 ? TOKEN_REFRESH_NOTICE : ''
              }`.trim(),
            )
            if (failed.length) {
              onError(failed.map((f) => f.error).join('; '))
            }
            void load()
          }}
          onError={onError}
        />
      ) : null}
    </section>
  )
}
