import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  listAdminFiles,
  type AclJob,
  type AdminFile,
  type AdminGroup,
  type AdminRole,
} from '../../api/admin'
import { ApiError } from '../../api/client'
import { FileAccessTable } from '../../components/admin/FileAccessTable'
import { GrantAccessModal } from '../../components/admin/GrantAccessModal'
import { JobTray } from '../../components/admin/JobTray'
import { ManageAccessPanel } from '../../components/admin/ManageAccessPanel'
import { RevokeAccessModal } from '../../components/admin/RevokeAccessModal'
import { inputClass, labelClass } from '../../components/admin/styles'
import { Button } from '../../components/ui/Button'

type Props = {
  roles: AdminRole[]
  groups: AdminGroup[]
  onError: (msg: string) => void
  onNotice: (msg: string) => void
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || `Request failed (${err.status})`
  if (err instanceof Error) return err.message
  return 'Request failed'
}

export function AccessPanel({ roles, groups, onError, onNotice }: Props) {
  const [files, setFiles] = useState<AdminFile[]>([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [hasAcl, setHasAcl] = useState<'all' | 'yes' | 'no'>('all')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [manageFile, setManageFile] = useState<AdminFile | null>(null)
  const [grantOpen, setGrantOpen] = useState(false)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [jobIds, setJobIds] = useState<string[]>([])
  const [jobsByFileId, setJobsByFileId] = useState<Record<string, AclJob>>({})

  const loadFiles = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listAdminFiles({
        limit: 100,
        offset: 0,
        q: q || undefined,
        has_acl: hasAcl === 'all' ? null : hasAcl === 'yes',
      })
      setFiles(list.items)
    } catch (err) {
      onError(errMessage(err))
    } finally {
      setLoading(false)
    }
    // onError is stable enough for UI; omit to avoid reload loops from inline parent callbacks
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, hasAcl])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles])

  const selectedFiles = useMemo(
    () => files.filter((f) => selectedIds.has(f.id)),
    [files, selectedIds],
  )

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll(ids: string[]) {
    setSelectedIds((prev) => {
      const allSelected = ids.length > 0 && ids.every((id) => prev.has(id))
      if (allSelected) return new Set()
      return new Set(ids)
    })
  }

  function handleBulkDone(newJobIds: string[], failed: { file_id: string; error: string }[]) {
    if (newJobIds.length) {
      setJobIds((prev) => [...new Set([...prev, ...newJobIds])])
    }
    if (failed.length) {
      onError(
        `${failed.length} file${failed.length === 1 ? '' : 's'} failed: ${failed
          .map((f) => f.error)
          .join('; ')}`,
      )
    } else {
      onNotice(
        `Updated access on ${selectedFiles.length || 'selected'} file(s) — syncing search index…`,
      )
    }
    setSelectedIds(new Set())
    void loadFiles()
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className={`${labelClass} min-w-[12rem] flex-1`}>
          Search files
          <input
            className={inputClass}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search files…"
          />
        </label>
        <label className={labelClass}>
          Has access
          <select
            className={inputClass}
            value={hasAcl}
            onChange={(e) => setHasAcl(e.target.value as 'all' | 'yes' | 'no')}
          >
            <option value="all">All</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        <Button type="button" onClick={() => void loadFiles()} disabled={loading}>
          {loading ? 'Loading…' : 'Reload'}
        </Button>
      </div>

      {selectedIds.size > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" onClick={() => setGrantOpen(true)}>
            Grant access…
          </Button>
          <Button type="button" onClick={() => setRevokeOpen(true)}>
            Revoke access…
          </Button>
          <span className="text-sm text-slate-400">{selectedIds.size} selected</span>
          <button
            type="button"
            className="text-sm text-slate-400 hover:text-slate-200"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </button>
        </div>
      ) : null}

      <div className={`grid gap-6 ${manageFile ? 'lg:grid-cols-[1.4fr_1fr]' : ''}`}>
        <FileAccessTable
          files={files}
          selectedIds={selectedIds}
          onToggle={toggle}
          onToggleAll={toggleAll}
          onManage={(file) => setManageFile(file)}
          jobsByFileId={jobsByFileId}
          loading={loading}
        />
        {manageFile ? (
          <ManageAccessPanel
            file={manageFile}
            roles={roles}
            groups={groups}
            onClose={() => setManageFile(null)}
            onSaved={(jobId) => {
              if (jobId) setJobIds((prev) => [...new Set([...prev, jobId])])
              void loadFiles()
            }}
            onError={onError}
            onNotice={onNotice}
          />
        ) : null}
      </div>

      <JobTray
        jobIds={jobIds}
        onJobsChange={(jobs) => {
          const map: Record<string, AclJob> = {}
          for (const job of jobs) map[job.file_id] = job
          setJobsByFileId((prev) => ({ ...prev, ...map }))
        }}
        onNotice={onNotice}
        onError={onError}
      />

      {grantOpen ? (
        <GrantAccessModal
          files={selectedFiles}
          roles={roles}
          groups={groups}
          onClose={() => setGrantOpen(false)}
          onDone={handleBulkDone}
          onError={onError}
        />
      ) : null}

      {revokeOpen ? (
        <RevokeAccessModal
          files={selectedFiles}
          roles={roles}
          groups={groups}
          onClose={() => setRevokeOpen(false)}
          onDone={handleBulkDone}
          onError={onError}
        />
      ) : null}
    </div>
  )
}
