import type { AclJob, AdminFile } from '../../api/admin'
import { formatBytes, permissionLabel } from './styles'
import { SyncStatusBadge } from './JobTray'

type Props = {
  files: AdminFile[]
  selectedIds: Set<string>
  onToggle: (id: string) => void
  onToggleAll: (ids: string[]) => void
  onManage: (file: AdminFile) => void
  jobsByFileId: Record<string, AclJob | undefined>
  loading?: boolean
}

export function FileAccessTable({
  files,
  selectedIds,
  onToggle,
  onToggleAll,
  onManage,
  jobsByFileId,
  loading,
}: Props) {
  const allIds = files.map((f) => f.id)
  const allSelected = allIds.length > 0 && allIds.every((id) => selectedIds.has(id))

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th className="py-2 pr-2">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => onToggleAll(allIds)}
                aria-label="Select all files"
              />
            </th>
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Size</th>
            <th className="py-2 pr-3">Access summary</th>
            <th className="py-2 pr-3">Sync</th>
            <th className="py-2"> </th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => {
            const preview = file.access_preview ?? []
            const total = file.access_total ?? preview.length
            const more = Math.max(0, total - preview.length)
            return (
              <tr key={file.id} className="border-t border-slate-800">
                <td className="py-2 pr-2">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(file.id)}
                    onChange={() => onToggle(file.id)}
                    aria-label={`Select ${file.display_name}`}
                  />
                </td>
                <td className="py-2 pr-3 font-medium text-slate-100">{file.display_name}</td>
                <td className="py-2 pr-3 text-slate-300">{file.file_type}</td>
                <td className="py-2 pr-3 text-slate-300">{formatBytes(file.size_bytes)}</td>
                <td className="py-2 pr-3">
                  {total === 0 ? (
                    <span className="text-slate-500">No access</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {preview.map((g) => (
                        <span
                          key={`${g.principal_type}:${g.principal_id}`}
                          className="rounded border border-slate-700 px-1.5 py-0.5 text-xs text-slate-300"
                        >
                          {g.principal_name} · {permissionLabel(g.permission)}
                        </span>
                      ))}
                      {more > 0 ? (
                        <span className="text-xs text-slate-500">+{more} more</span>
                      ) : null}
                    </div>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <SyncStatusBadge job={jobsByFileId[file.id]} />
                </td>
                <td className="py-2">
                  <button
                    type="button"
                    className="text-sky-400 hover:text-sky-300"
                    onClick={() => onManage(file)}
                  >
                    Manage
                  </button>
                </td>
              </tr>
            )
          })}
          {!loading && files.length === 0 ? (
            <tr>
              <td colSpan={7} className="py-4 text-slate-500">
                No files match.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}
