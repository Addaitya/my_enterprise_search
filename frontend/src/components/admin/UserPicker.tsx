import { useEffect, useState } from 'react'

import { listUsers, type AdminUser } from '../../api/admin'
import { inputClass, labelClass } from './styles'

type Props = {
  value: AdminUser[]
  onChange: (next: AdminUser[]) => void
  disabled?: boolean
  excludeIds?: Set<string>
}

export function UserPicker({ value, onChange, disabled, excludeIds }: Props) {
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const handle = window.setTimeout(() => {
      setLoading(true)
      void listUsers(30, 0, query.trim() || undefined)
        .then((list) => {
          if (!cancelled) setOptions(list.items)
        })
        .catch(() => {
          if (!cancelled) setOptions([])
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [query])

  function isSelected(id: string) {
    return value.some((u) => u.id === id)
  }

  function toggle(user: AdminUser) {
    if (isSelected(user.id)) {
      onChange(value.filter((u) => u.id !== user.id))
    } else {
      onChange([...value, user])
    }
  }

  const visible = options.filter((u) => !excludeIds?.has(u.id))

  return (
    <div className="space-y-2">
      <label className={labelClass}>
        Users
        <input
          className={inputClass}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search username or email"
          disabled={disabled}
        />
      </label>
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {value.map((u) => (
            <button
              key={u.id}
              type="button"
              disabled={disabled}
              className="rounded-md border border-sky-800 bg-sky-950/40 px-2 py-1 text-sm text-sky-200 hover:border-sky-600"
              onClick={() => toggle(u)}
            >
              {u.username} ×
            </button>
          ))}
        </div>
      ) : null}
      <div className="max-h-40 overflow-y-auto rounded-md border border-slate-800">
        {loading ? <p className="px-3 py-2 text-sm text-slate-500">Searching…</p> : null}
        {!loading &&
          visible.map((user) => (
            <button
              key={user.id}
              type="button"
              disabled={disabled}
              className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
                isSelected(user.id)
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
              onClick={() => toggle(user)}
            >
              <span>{user.username}</span>
              <span className="truncate text-xs text-slate-500">{user.email || '—'}</span>
            </button>
          ))}
        {!loading && visible.length === 0 ? (
          <p className="px-3 py-2 text-sm text-slate-500">No matches</p>
        ) : null}
      </div>
    </div>
  )
}
