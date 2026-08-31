import { useEffect, useState, type FormEvent } from 'react'

import {
  getAclJob,
  getFileAcl,
  replaceFileAcl,
  type AclGrantInput,
  type AclJob,
  type AdminFile,
  type AdminGroup,
  type AdminRole,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { PermissionSelect } from './PermissionSelect'
import { PrincipalPicker, type PrincipalRef } from './PrincipalPicker'
import { SyncStatusBadge } from './JobTray'

type DraftGrant = {
  key: string
  principal_type: 'role' | 'group'
  principal_id: string
  principal_name: string
  permission: 'viewer' | 'editor'
}

type Props = {
  file: AdminFile
  roles: AdminRole[]
  groups: AdminGroup[]
  onClose: () => void
  onSaved: (jobId: string | null) => void
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

function nameFor(
  type: 'role' | 'group',
  id: string,
  roles: AdminRole[],
  groups: AdminGroup[],
): string {
  if (type === 'role') return roles.find((r) => r.id === id)?.name ?? id.slice(0, 8)
  return groups.find((g) => g.id === id)?.name ?? id.slice(0, 8)
}

export function ManageAccessPanel({
  file,
  roles,
  groups,
  onClose,
  onSaved,
  onError,
  onNotice,
}: Props) {
  const [drafts, setDrafts] = useState<DraftGrant[]>([])
  const [addPrincipals, setAddPrincipals] = useState<PrincipalRef[]>([])
  const [addPermission, setAddPermission] = useState<'viewer' | 'editor'>('viewer')
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<AclJob | null>(null)
  const [loading, setLoading] = useState(true)

  async function reloadGrants() {
    setLoading(true)
    try {
      const acl = await getFileAcl(file.id)
      setDrafts(
        acl.grants.map((g) => ({
          key: g.id,
          principal_type: g.principal_type,
          principal_id: g.principal_id,
          principal_name: g.principal_name,
          permission: g.permission === 'editor' ? 'editor' : 'viewer',
        })),
      )
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reloadGrants()
    setJob(null)
    setAddPrincipals([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file.id])

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
            onError(next.error || 'Access sync job failed')
          }
        } catch (err) {
          onError(errMessage(err))
        }
      })()
    }, 1000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status])

  function addToDraft() {
    if (addPrincipals.length === 0) {
      onError('Select at least one role or group')
      return
    }
    setDrafts((prev) => {
      const next = [...prev]
      for (const p of addPrincipals) {
        const idx = next.findIndex(
          (d) => d.principal_type === p.principal_type && d.principal_id === p.principal_id,
        )
        if (idx >= 0) {
          next[idx] = { ...next[idx], permission: addPermission }
        } else {
          next.push({
            key: `new-${p.principal_type}-${p.principal_id}-${Date.now()}`,
            principal_type: p.principal_type,
            principal_id: p.principal_id,
            principal_name: p.name,
            permission: addPermission,
          })
        }
      }
      return next
    })
    setAddPrincipals([])
  }

  async function onSave(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const grants: AclGrantInput[] = drafts.map((d) => ({
        principal_type: d.principal_type,
        principal_id: d.principal_id,
        permission: d.permission,
      }))
      const result = await replaceFileAcl(file.id, grants)
      setDrafts(
        result.grants.map((g) => ({
          key: g.id,
          principal_type: g.principal_type,
          principal_id: g.principal_id,
          principal_name: g.principal_name,
          permission: g.permission === 'editor' ? 'editor' : 'viewer',
        })),
      )
      onNotice('Access saved — syncing search index…')
      onSaved(result.acl_job_id)
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

  return (
    <form onSubmit={(e) => void onSave(e)} className="space-y-4 rounded-md border border-slate-800 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-white">{file.display_name}</h2>
          <p className="text-sm text-slate-400">Roles & groups with access</p>
        </div>
        <button type="button" className="text-sm text-slate-400 hover:text-slate-200" onClick={onClose}>
          Close
        </button>
      </div>

      {loading ? <p className="text-sm text-slate-500">Loading…</p> : null}

      {!loading && drafts.length === 0 ? (
        <p className="text-sm text-slate-500">No roles or groups can search this file yet.</p>
      ) : null}

      <ul className="space-y-2">
        {drafts.map((draft, index) => (
          <li
            key={draft.key}
            className="grid gap-2 sm:grid-cols-[1fr_7rem_auto] sm:items-end"
          >
            <div>
              <span className="font-medium text-slate-100">
                {draft.principal_name ||
                  nameFor(draft.principal_type, draft.principal_id, roles, groups)}
              </span>
              <span className="ml-2 rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-400">
                {draft.principal_type === 'role' ? 'Role' : 'Group'}
              </span>
            </div>
            <PermissionSelect
              value={draft.permission}
              onChange={(permission) =>
                setDrafts((prev) => prev.map((d, i) => (i === index ? { ...d, permission } : d)))
              }
              disabled={busy}
            />
            <button
              type="button"
              className="mb-1 text-sm text-rose-400 hover:text-rose-300"
              onClick={() => setDrafts((prev) => prev.filter((_, i) => i !== index))}
              disabled={busy}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="space-y-3 border-t border-slate-800 pt-4">
        <PrincipalPicker
          roles={roles}
          groups={groups}
          value={addPrincipals}
          onChange={setAddPrincipals}
          disabled={busy}
        />
        <div className="flex flex-wrap items-end gap-3">
          <PermissionSelect value={addPermission} onChange={setAddPermission} disabled={busy} />
          <Button type="button" onClick={addToDraft} disabled={busy}>
            Add to draft
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save access'}
        </Button>
        <Button
          type="button"
          disabled={busy}
          onClick={() => {
            void reloadGrants()
            onNotice('Draft reloaded')
          }}
        >
          Cancel
        </Button>
      </div>

      {job ? (
        <div className="rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-300">
          <p>
            Sync: <SyncStatusBadge job={job} />
            {job.total_chunks != null ? (
              <span className="ml-2 text-xs text-slate-500">
                {job.updated_chunks ?? 0}/{job.total_chunks} chunks
              </span>
            ) : null}
          </p>
          {job.error ? <p className="mt-1 text-rose-400">{job.error}</p> : null}
        </div>
      ) : null}
    </form>
  )
}
