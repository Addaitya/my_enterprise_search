import { useEffect, useMemo, useState, type FormEvent } from 'react'

import {
  createUser,
  updateUser,
  type AdminGroup,
  type AdminRole,
  type AdminUser,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { BulkAddToPrincipalModal } from '../../components/admin/BulkAddToPrincipalModal'
import { GroupPicker } from '../../components/admin/GroupPicker'
import { TOKEN_REFRESH_NOTICE } from '../../components/admin/ImpactPreview'
import { RolePicker } from '../../components/admin/RolePicker'
import { inputClass, labelClass } from '../../components/admin/styles'
import { Button } from '../../components/ui/Button'

type Props = {
  users: AdminUser[]
  roles: AdminRole[]
  groups: AdminGroup[]
  userQuery: string
  setUserQuery: (q: string) => void
  editingUser: AdminUser | null
  setEditingUser: (u: AdminUser | null) => void
  onReload: () => void
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function UsersPanel({
  users,
  roles,
  groups,
  userQuery,
  setUserQuery,
  editingUser,
  setEditingUser,
  onReload,
  onError,
  onNotice,
}: Props) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [roleNames, setRoleNames] = useState<string[]>(['search-user'])
  const [groupNames, setGroupNames] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkKind, setBulkKind] = useState<'role' | 'group' | null>(null)

  useEffect(() => {
    if (!editingUser) {
      setUsername('')
      setEmail('')
      setPassword('')
      setEnabled(true)
      setRoleNames(['search-user'])
      setGroupNames([])
      return
    }
    setUsername(editingUser.username)
    setEmail(editingUser.email ?? '')
    setPassword('')
    setEnabled(editingUser.enabled)
    setRoleNames(editingUser.role_names.length ? editingUser.role_names : ['search-user'])
    setGroupNames(editingUser.group_names)
  }, [editingUser])

  const selectedUsers = useMemo(
    () => users.filter((u) => selectedIds.has(u.id)),
    [users, selectedIds],
  )

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (selectedIds.size === users.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(users.map((u) => u.id)))
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      if (editingUser) {
        const body: {
          email: string | null
          enabled: boolean
          role_names: string[]
          group_names: string[]
          password?: string
        } = {
          email: email.trim() || null,
          enabled,
          role_names: roleNames,
          group_names: groupNames,
        }
        if (password.trim()) body.password = password
        await updateUser(editingUser.id, body)
        onNotice(`Updated user ${editingUser.username}`)
        setEditingUser(null)
      } else {
        if (!username.trim() || !password.trim()) {
          onError('Username and password are required')
          return
        }
        await createUser({
          username: username.trim(),
          email: email.trim() || null,
          password,
          enabled,
          role_names: roleNames,
          group_names: groupNames,
        })
        onNotice(`Created user ${username.trim()}`)
        setUsername('')
        setEmail('')
        setPassword('')
        setRoleNames(['search-user'])
        setGroupNames([])
      }
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {selectedIds.size > 0 ? (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-md border border-slate-700 bg-slate-950/95 px-3 py-2">
          <span className="text-sm text-slate-400">{selectedIds.size} selected</span>
          <Button type="button" onClick={() => setBulkKind('role')} disabled={busy}>
            Add to role…
          </Button>
          <Button type="button" onClick={() => setBulkKind('group')} disabled={busy}>
            Add to group…
          </Button>
          <button
            type="button"
            className="text-sm text-slate-400 hover:text-slate-200"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
        </div>
      ) : null}

      <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
        <form onSubmit={(e) => void onSubmit(e)} className="space-y-3">
          <h2 className="text-lg font-medium text-white">
            {editingUser ? `Edit ${editingUser.username}` : 'Create user'}
          </h2>
          {!editingUser ? (
            <label className={labelClass}>
              Username
              <input
                className={inputClass}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
          ) : (
            <p className="text-sm text-slate-400">
              Username <span className="text-slate-200">{editingUser.username}</span> (immutable)
            </p>
          )}
          <label className={labelClass}>
            Email
            <input
              className={inputClass}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="optional"
            />
          </label>
          <label className={labelClass}>
            {editingUser ? 'New password (optional)' : 'Password'}
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={!editingUser}
              autoComplete="new-password"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Enabled
          </label>
          <RolePicker
            roles={roles}
            value={roleNames}
            onChange={setRoleNames}
            disabled={busy}
          />
          <p className="text-xs text-slate-500">Must include search-user and/or admin.</p>
          <GroupPicker
            groups={groups}
            value={groupNames}
            onChange={setGroupNames}
            disabled={busy}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? 'Saving…' : editingUser ? 'Save user' : 'Create user'}
            </Button>
            {editingUser ? (
              <Button type="button" onClick={() => setEditingUser(null)} disabled={busy}>
                Cancel
              </Button>
            ) : null}
          </div>
        </form>

        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              className={inputClass}
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              placeholder="Search username or email"
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={users.length > 0 && selectedIds.size === users.length}
                      onChange={toggleAll}
                      disabled={users.length === 0}
                    />
                  </th>
                  <th className="py-2 pr-3">User</th>
                  <th className="py-2 pr-3">Roles</th>
                  <th className="py-2 pr-3">Groups</th>
                  <th className="py-2"> </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} className="border-t border-slate-800">
                    <td className="py-2 pr-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(user.id)}
                        onChange={() => toggle(user.id)}
                      />
                    </td>
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-100">{user.username}</div>
                      <div className="text-xs text-slate-500">
                        {user.email || '—'} · {user.enabled ? 'enabled' : 'disabled'}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-slate-300">{user.role_names.join(', ') || '—'}</td>
                    <td className="py-2 pr-3 text-slate-300">{user.group_names.join(', ') || '—'}</td>
                    <td className="py-2">
                      <button
                        type="button"
                        className="text-sky-400 hover:text-sky-300"
                        onClick={() => setEditingUser(user)}
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {bulkKind ? (
        <BulkAddToPrincipalModal
          kind={bulkKind}
          users={selectedUsers}
          roles={roles}
          groups={groups}
          onClose={() => setBulkKind(null)}
          onDone={(added, failed, targetName) => {
            onNotice(
              `Added ${added} users to ${targetName}. Failed: ${failed.length}. ${
                added > 0 ? TOKEN_REFRESH_NOTICE : ''
              }`.trim(),
            )
            if (failed.length) {
              onError(failed.map((f) => f.error).join('; '))
            }
            setSelectedIds(new Set())
            onReload()
          }}
          onError={onError}
        />
      ) : null}
    </div>
  )
}
