import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  createGroup,
  deleteFileAcl,
  deleteGroup,
  listGroupFileGrants,
  type AdminGroup,
  type AdminRole,
  type FileGrantItem,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { GrantFilesModal } from '../../components/admin/GrantFilesModal'
import { JobTray } from '../../components/admin/JobTray'
import { MembersSection } from '../../components/admin/MembersSection'
import { inputClass, labelClass, permissionLabel } from '../../components/admin/styles'
import { Button } from '../../components/ui/Button'

type Props = {
  groups: AdminGroup[]
  roles: AdminRole[]
  onReload: () => void
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function GroupsPanel({ groups, roles, onReload, onError, onNotice }: Props) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<AdminGroup | null>(null)
  const [grants, setGrants] = useState<FileGrantItem[]>([])
  const [grantsTotal, setGrantsTotal] = useState(0)
  const [grantOpen, setGrantOpen] = useState(false)
  const [jobIds, setJobIds] = useState<string[]>([])

  const loadGrants = useCallback(
    async (group: AdminGroup) => {
      try {
        const list = await listGroupFileGrants(group.id, 50, 0)
        setGrants(list.items)
        setGrantsTotal(list.total)
      } catch (err) {
        onError(errMessage(err))
      }
    },
    [onError],
  )

  useEffect(() => {
    if (!selected) {
      setGrants([])
      setGrantsTotal(0)
      return
    }
    void loadGrants(selected)
  }, [selected, loadGrants])

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
      if (selected?.id === group.id) setSelected(null)
      onReload()
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function onRemoveGrant(item: FileGrantItem) {
    if (!selected) return
    if (!window.confirm(`Remove access to ${item.display_name}?`)) return
    setBusy(true)
    try {
      const result = await deleteFileAcl(item.file_id, item.acl_id)
      if (result.acl_job_id) {
        setJobIds((prev) => [...new Set([...prev, result.acl_job_id!])])
      }
      onNotice(`Removed access to ${item.display_name}`)
      await loadGrants(selected)
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
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
              <tr
                key={group.id}
                className={`border-t border-slate-800 ${
                  selected?.id === group.id ? 'bg-slate-900/80' : ''
                }`}
              >
                <td className="py-2 pr-3">
                  <button
                    type="button"
                    className="font-medium text-slate-100 hover:text-sky-300"
                    onClick={() => setSelected(group)}
                  >
                    {group.name}
                  </button>
                </td>
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

      {selected ? (
        <div className="space-y-6">
          <MembersSection
            kind="group"
            principalId={selected.id}
            principalName={selected.name}
            manageable={!selected.is_system && selected.name !== '_empty'}
            onError={onError}
            onNotice={onNotice}
          />
          <section className="space-y-3 rounded-md border border-slate-800 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-medium text-white">
                File access — {selected.name}
              </h2>
              <Button type="button" onClick={() => setGrantOpen(true)} disabled={busy}>
                Grant files…
              </Button>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">File</th>
                  <th className="py-2 pr-3">Type</th>
                  <th className="py-2 pr-3">Permission</th>
                  <th className="py-2"> </th>
                </tr>
              </thead>
              <tbody>
                {grants.map((item) => (
                  <tr key={item.acl_id} className="border-t border-slate-800">
                    <td className="py-2 pr-3 text-slate-100">{item.display_name}</td>
                    <td className="py-2 pr-3 text-slate-300">{item.file_type}</td>
                    <td className="py-2 pr-3 text-slate-300">{permissionLabel(item.permission)}</td>
                    <td className="py-2">
                      <button
                        type="button"
                        className="text-rose-400 hover:text-rose-300"
                        onClick={() => void onRemoveGrant(item)}
                        disabled={busy}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
                {grants.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-3 text-slate-500">
                      No files granted yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
            {grantsTotal > grants.length ? (
              <p className="text-xs text-slate-500">Showing {grants.length} of {grantsTotal}</p>
            ) : null}
            <JobTray jobIds={jobIds} onNotice={onNotice} onError={onError} />
          </section>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Select a group to view members and file access.</p>
      )}

      {grantOpen && selected ? (
        <GrantFilesModal
          lockedPrincipal={{
            principal_type: 'group',
            principal_id: selected.id,
            name: selected.name,
          }}
          roles={roles}
          groups={groups}
          onClose={() => setGrantOpen(false)}
          onDone={(ids, failed) => {
            if (ids.length) setJobIds((prev) => [...new Set([...prev, ...ids])])
            if (failed.length) {
              onError(failed.map((f) => f.error).join('; '))
            } else {
              onNotice('Files granted — syncing…')
            }
            void loadGrants(selected)
          }}
          onError={onError}
        />
      ) : null}
    </div>
  )
}
