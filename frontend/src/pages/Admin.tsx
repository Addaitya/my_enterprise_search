import { useCallback, useEffect, useState } from 'react'

import { listGroups, listRoles, listUsers, type AdminGroup, type AdminRole, type AdminUser } from '../api/admin'
import { ApiError } from '../api/client'
import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'
import { AccessPanel } from './admin/AccessPanel'
import { GroupsPanel } from './admin/GroupsPanel'
import { RolesPanel } from './admin/RolesPanel'
import { UsersPanel } from './admin/UsersPanel'

type Tab = 'users' | 'roles' | 'groups' | 'access'

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
              Manage users, roles, groups, and file access (Keycloak + Postgres + OpenSearch sync).
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
          <button type="button" className={tabClass(tab === 'access')} onClick={() => setTab('access')}>
            Access
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
            groups={groups}
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
            roles={roles}
            onReload={() => void load()}
            onError={(msg) => {
              setError(msg)
              setNotice(null)
            }}
            onNotice={flash}
          />
        ) : null}

        {tab === 'access' ? (
          <AccessPanel
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
