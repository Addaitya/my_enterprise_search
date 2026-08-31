export const inputClass =
  'mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none'

export const labelClass = 'block text-xs font-medium uppercase tracking-wide text-slate-400'

export function permissionLabel(permission: string): string {
  return permission === 'editor' ? 'Editor' : 'Viewer'
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
