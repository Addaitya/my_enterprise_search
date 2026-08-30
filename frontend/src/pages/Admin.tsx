import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  createGroup,
  createRole,
  createUser,
  deleteGroup,
  deleteRole,
  getAclJob,
  getFileAcl,
  listAdminFiles,
  listGroups,
  listRoles,
  listUsers,
  replaceFileAcl,
  retryAclJob,
  updateRole,
  updateUser,
  type AclGrantInput,
  type AclJob,
  type AdminFile,
  type AdminGroup,
  type AdminRole,
  type AdminUser,
} from '../api/admin'
import { ApiError } from '../api/client'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'

type Tab = 'users' | 'roles' | 'groups' | 'files'

const inputClass =
  'mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none'
const labelClass = 'block text-xs font-medium uppercase tracking-wide text-slate-400'
const tabClass = (active: boolean) =>
  `rounded-md px-3 py-1.5 text-sm font-medium ${
    active ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
  }`

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function Admin() {
  const [tab, setTab] = useState<Tab>('users')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [users, setUsers] = useState<AdminUser[]>([])
  const [roles, setRoles] = useState<AdminRole[]>([])
  const [groups, setGroups] = useState<AdminGroup[]>([])
  const [loading, setLoading] = useState(true)

  const [userQuery, setUserQuery] = useState('')
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [userList, roleList, groupList] = await Promise.all([
        listUsers(100, 0, userQuery || undefined),
        listRoles(false),
        listGroups(false),
      ])
      setUsers(userList.items)
      setRoles(roleList.items)
      setGroups(groupList.items)
    } catch (err) {
      setError(errMessage(err))
    } finally {
      setLoading(false)
    }
  }, [userQuery])

  useEffect(() => {
    void load()
  }, [load])

  function flash(message: string) {
    setNotice(message)
    setError(null)
  }

  return (
    <AppShell>
      <section className="space-y-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-white">Admin</h1>
            <p className="mt-1 text-slate-400">
              Manage users, roles, groups, and file ACL (Keycloak + Postgres + OpenSearch sync).
            </p>
          </div>
          <Button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
          <button type="button" className={tabClass(tab === 'users')} onClick={() => setTab('users')}>
            Users
          </button>
          <button type="button" className={tabClass(tab === 'roles')} onClick={() => setTab('roles')}>
            Roles
          </button>
          <button type="button" className={tabClass(tab === 'groups')} onClick={() => setTab('groups')}>
            Groups
          </button>
          <button type="button" className={tabClass(tab === 'files')} onClick={() => setTab('files')}>
            Files (ACL)
          </button>
        </div>

        {error ? <p className="text-sm text-rose-400">{error}</p> : null}
        {notice ? <p className="text-sm text-emerald-400">{notice}</p> : null}

        {tab === 'users' ? (
          <UsersPanel
            users={users}
            roles={roles}
            groups={groups}
            userQuery={userQuery}
            setUserQuery={setUserQuery}
            editingUser={editingUser}
            setEditingUser={setEditingUser}
            onReload={() => void load()}
            onError={(msg) => {
              setError(msg)
              setNotice(null)
            }}
            onNotice={flash}
          />
        ) : null}

        {tab === 'roles' ? (
          <RolesPanel
            roles={roles}
            onReload={() => void load()}
            onError={(msg) => {
              setError(msg)
              setNotice(null)
            }}
            onNotice={flash}
          />
        ) : null}

        {tab === 'groups' ? (
          <GroupsPanel
            groups={groups}
            onReload={() => void load()}
            onError={(msg) => {
              setError(msg)
              setNotice(null)
            }}
            onNotice={flash}
          />
        ) : null}

        {tab === 'files' ? (
          <FilesAclPanel
            roles={roles}
            groups={groups}
            onError={(msg) => {
              setError(msg)
              setNotice(null)
            }}
            onNotice={flash}
          />
        ) : null}
      </section>
    </AppShell>
  )
}

function UsersPanel({
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
}: {
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
}) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [roleNames, setRoleNames] = useState<string[]>(['search-user'])
  const [groupNames, setGroupNames] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

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

  function toggleName(list: string[], name: string, setList: (v: string[]) => void) {
    setList(list.includes(name) ? list.filter((n) => n !== name) : [...list, name])
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
    <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-3">
        <h2 className="text-lg font-medium text-white">
          {editingUser ? `Edit ${editingUser.username}` : 'Create user'}
        </h2>
        {!editingUser ? (
          <label className={labelClass}>
            Username
            <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} required />
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
        <fieldset>
          <legend className={labelClass}>Roles</legend>
          <div className="mt-2 flex flex-wrap gap-3">
            {roles.map((role) => (
              <label key={role.id} className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={roleNames.includes(role.name)}
                  onChange={() => toggleName(roleNames, role.name, setRoleNames)}
                />
                {role.name}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500">Must include search-user and/or admin.</p>
        </fieldset>
        <fieldset>
          <legend className={labelClass}>Groups</legend>
          <div className="mt-2 flex flex-wrap gap-3">
            {groups.map((group) => (
              <label key={group.id} className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={groupNames.includes(group.name)}
                  onChange={() => toggleName(groupNames, group.name, setGroupNames)}
                />
                {group.name}
              </label>
            ))}
            {groups.length === 0 ? <span className="text-sm text-slate-500">No groups yet</span> : null}
          </div>
        </fieldset>
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
                <th className="py-2 pr-3">User</th>
                <th className="py-2 pr-3">Roles</th>
                <th className="py-2 pr-3">Groups</th>
                <th className="py-2"> </th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-slate-800">
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
  )
}

function RolesPanel({
  roles,
  onReload,
  onError,
  onNotice,
}: {
  roles: AdminRole[]
  onReload: () => void
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [editing, setEditing] = useState<AdminRole | null>(null)
  const [editDescription, setEditDescription] = useState('')
  const [busy, setBusy] = useState(false)

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await createRole(name.trim(), description.trim() || null)
      onNotice(`Created role ${name.trim()}`)
      setName('')
      setDescription('')
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onSaveDescription(event: FormEvent) {
    event.preventDefault()
    if (!editing) return
    setBusy(true)
    try {
      await updateRole(editing.id, editDescription.trim() || null)
      onNotice(`Updated role ${editing.name}`)
      setEditing(null)
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(role: AdminRole) {
    if (!window.confirm(`Delete role ${role.name}?`)) return
    setBusy(true)
    try {
      await deleteRole(role.id)
      onNotice(`Deleted role ${role.name}`)
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
      <form onSubmit={(e) => void onCreate(e)} className="space-y-3">
        <h2 className="text-lg font-medium text-white">Create role</h2>
        <label className={labelClass}>
          Name (immutable after create)
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className={labelClass}>
          Description
          <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Create role'}
        </Button>
      </form>

      <div className="space-y-4">
        {editing ? (
          <form onSubmit={(e) => void onSaveDescription(e)} className="space-y-3 rounded-md border border-slate-800 p-4">
            <h3 className="text-sm font-medium text-white">Edit description — {editing.name}</h3>
            <input
              className={inputClass}
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
            <div className="flex gap-2">
              <Button type="submit" disabled={busy}>
                Save
              </Button>
              <Button type="button" onClick={() => setEditing(null)} disabled={busy}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2 pr-3">Name</th>
              <th className="py-2 pr-3">Description</th>
              <th className="py-2"> </th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id} className="border-t border-slate-800">
                <td className="py-2 pr-3 font-medium text-slate-100">{role.name}</td>
                <td className="py-2 pr-3 text-slate-300">{role.description || '—'}</td>
                <td className="space-x-3 py-2">
                  <button
                    type="button"
                    className="text-sky-400 hover:text-sky-300"
                    onClick={() => {
                      setEditing(role)
                      setEditDescription(role.description ?? '')
                    }}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="text-rose-400 hover:text-rose-300"
                    onClick={() => void onDelete(role)}
                    disabled={busy}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function GroupsPanel({
  groups,
  onReload,
  onError,
  onNotice,
}: {
  groups: AdminGroup[]
  onReload: () => void
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await createGroup(name.trim())
      onNotice(`Created group ${name.trim()}`)
      setName('')
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(group: AdminGroup) {
    if (!window.confirm(`Delete group ${group.name}?`)) return
    setBusy(true)
    try {
      await deleteGroup(group.id)
      onNotice(`Deleted group ${group.name}`)
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
      <form onSubmit={(e) => void onCreate(e)} className="space-y-3">
        <h2 className="text-lg font-medium text-white">Create group</h2>
        <label className={labelClass}>
          Name (immutable)
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Create group'}
        </Button>
      </form>

      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Path</th>
            <th className="py-2"> </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.id} className="border-t border-slate-800">
              <td className="py-2 pr-3 font-medium text-slate-100">{group.name}</td>
              <td className="py-2 pr-3 text-slate-300">{group.path || '—'}</td>
              <td className="py-2">
                <button
                  type="button"
                  className="text-rose-400 hover:text-rose-300"
                  onClick={() => void onDelete(group)}
                  disabled={busy}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type DraftGrant = {
  key: string
  principal_type: 'role' | 'group'
  principal_id: string
  permission: 'viewer' | 'editor'
}

function FilesAclPanel({
  roles,
  groups,
  onError,
  onNotice,
}: {
  roles: AdminRole[]
  groups: AdminGroup[]
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}) {
  const [files, setFiles] = useState<AdminFile[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string>('')
  const [drafts, setDrafts] = useState<DraftGrant[]>([])
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<AclJob | null>(null)

  const selected = files.find((f) => f.id === selectedId) ?? null

  async function loadFiles() {
    setLoading(true)
    try {
      const list = await listAdminFiles(100, 0)
      setFiles(list.items)
      setSelectedId((prev) => prev || list.items[0]?.id || '')
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadFiles()
    // initial inventory load only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedId) {
      setDrafts([])
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const acl = await getFileAcl(selectedId)
        if (cancelled) return
        setDrafts(
          acl.grants.map((g) => ({
            key: g.id,
            principal_type: g.principal_type,
            principal_id: g.principal_id,
            permission: g.permission === 'editor' ? 'editor' : 'viewer',
          })),
        )
        setJob(null)
      } catch (err) {
        if (!cancelled) onError(errMessage(err))
      }
    })()
    return () => {
      cancelled = true
    }
    // reload grants when file selection changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  useEffect(() => {
    if (!job || (job.status !== 'queued' && job.status !== 'running')) return
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await getAclJob(job.id)
          setJob(next)
          if (next.status === 'succeeded') {
            onNotice(
              `OpenSearch sync succeeded (${next.updated_chunks ?? 0}/${next.total_chunks ?? '?'} chunks)`,
            )
          } else if (next.status === 'failed') {
            onError(next.error || 'ACL sync job failed')
          }
        } catch (err) {
          onError(errMessage(err))
        }
      })()
    }, 1000)
    return () => window.clearInterval(timer)
    // poll while job is active
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status])

  function addGrant() {
    const firstRole = roles[0]
    const firstGroup = groups[0]
    if (!firstRole && !firstGroup) {
      onError('No roles or groups available for grants')
      return
    }
    if (firstRole) {
      setDrafts((prev) => [
        ...prev,
        {
          key: `new-${Date.now()}`,
          principal_type: 'role',
          principal_id: firstRole.id,
          permission: 'viewer',
        },
      ])
    } else if (firstGroup) {
      setDrafts((prev) => [
        ...prev,
        {
          key: `new-${Date.now()}`,
          principal_type: 'group',
          principal_id: firstGroup.id,
          permission: 'viewer',
        },
      ])
    }
  }

  async function onSave(event: FormEvent) {
    event.preventDefault()
    if (!selectedId) return
    setBusy(true)
    try {
      const grants: AclGrantInput[] = drafts.map((d) => ({
        principal_type: d.principal_type,
        principal_id: d.principal_id,
        permission: d.permission,
      }))
      const result = await replaceFileAcl(selectedId, grants)
      setDrafts(
        result.grants.map((g) => ({
          key: g.id,
          principal_type: g.principal_type,
          principal_id: g.principal_id,
          permission: g.permission === 'editor' ? 'editor' : 'viewer',
        })),
      )
      onNotice('ACL saved — syncing OpenSearch…')
      if (result.acl_job_id) {
        const j = await getAclJob(result.acl_job_id)
        setJob(j)
      }
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onRetry() {
    if (!job || job.status !== 'failed') return
    setBusy(true)
    try {
      const j = await retryAclJob(job.id)
      setJob(j)
      onNotice('Retry queued')
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-medium text-white">All files</h2>
          <Button type="button" onClick={() => void loadFiles()} disabled={loading}>
            {loading ? 'Loading…' : 'Reload'}
          </Button>
        </div>
        <p className="text-xs text-slate-500">Inventory is not ACL-filtered (admin only).</p>
        <ul className="max-h-[28rem] space-y-1 overflow-y-auto text-sm">
          {files.map((file) => (
            <li key={file.id}>
              <button
                type="button"
                className={`w-full rounded-md px-3 py-2 text-left ${
                  file.id === selectedId
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-300 hover:bg-slate-800'
                }`}
                onClick={() => setSelectedId(file.id)}
              >
                <span className="block truncate font-medium">{file.display_name}</span>
                <span className="text-xs text-slate-500">
                  {file.file_type} · {(file.size_bytes / 1024).toFixed(1)} KB
                </span>
              </button>
            </li>
          ))}
          {!loading && files.length === 0 ? (
            <li className="text-slate-500">No files uploaded yet.</li>
          ) : null}
        </ul>
      </div>

      <form onSubmit={(e) => void onSave(e)} className="space-y-4">
        <h2 className="text-lg font-medium text-white">
          Grants{selected ? ` — ${selected.display_name}` : ''}
        </h2>
        {!selected ? (
          <p className="text-sm text-slate-500">Select a file to edit ACL.</p>
        ) : (
          <>
            <div className="space-y-3">
              {drafts.map((draft, index) => (
                <div
                  key={draft.key}
                  className="grid gap-2 sm:grid-cols-[7rem_1fr_7rem_auto] sm:items-end"
                >
                  <label className={labelClass}>
                    Type
                    <select
                      className={inputClass}
                      value={draft.principal_type}
                      onChange={(e) => {
                        const principal_type = e.target.value as 'role' | 'group'
                        const principal_id =
                          principal_type === 'role' ? roles[0]?.id ?? '' : groups[0]?.id ?? ''
                        setDrafts((prev) =>
                          prev.map((d, i) =>
                            i === index ? { ...d, principal_type, principal_id } : d,
                          ),
                        )
                      }}
                    >
                      <option value="role">role</option>
                      <option value="group">group</option>
                    </select>
                  </label>
                  <label className={labelClass}>
                    Principal
                    <select
                      className={inputClass}
                      value={draft.principal_id}
                      onChange={(e) =>
                        setDrafts((prev) =>
                          prev.map((d, i) =>
                            i === index ? { ...d, principal_id: e.target.value } : d,
                          ),
                        )
                      }
                    >
                      {(draft.principal_type === 'role' ? roles : groups).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={labelClass}>
                    Permission
                    <select
                      className={inputClass}
                      value={draft.permission}
                      onChange={(e) =>
                        setDrafts((prev) =>
                          prev.map((d, i) =>
                            i === index
                              ? {
                                  ...d,
                                  permission: e.target.value as 'viewer' | 'editor',
                                }
                              : d,
                          ),
                        )
                      }
                    >
                      <option value="viewer">viewer</option>
                      <option value="editor">editor</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    className="mb-1 text-sm text-rose-400 hover:text-rose-300"
                    onClick={() => setDrafts((prev) => prev.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button type="button" onClick={addGrant} disabled={busy}>
                Add grant
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? 'Saving…' : 'Save ACL'}
              </Button>
            </div>

            {job ? (
              <div className="rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-300">
                <p>
                  Sync job <span className="font-mono text-xs text-slate-400">{job.id}</span>:{' '}
                  <span className="font-medium text-white">{job.status}</span>
                  {job.total_chunks != null ? (
                    <span>
                      {' '}
                      — {job.updated_chunks ?? 0}/{job.total_chunks} chunks
                    </span>
                  ) : null}
                </p>
                {job.error ? <p className="mt-1 text-rose-400">{job.error}</p> : null}
                {job.status === 'failed' ? (
                  <button
                    type="button"
                    className="mt-2 text-sky-400 hover:text-sky-300"
                    onClick={() => void onRetry()}
                    disabled={busy}
                  >
                    Retry sync
                  </button>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </form>
    </div>
  )
}
