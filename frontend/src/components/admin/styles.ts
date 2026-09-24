export const inputClass =
  'mt-1 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-400 focus:outline-none'

export const labelClass = 'block text-xs font-medium uppercase tracking-wide text-gray-500'

export function permissionLabel(permission: string): string {
  return permission === 'editor' ? 'Editor' : 'Viewer'
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
