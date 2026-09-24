import { useState } from 'react'

import type { AdminRole } from '../../api/admin'
import { inputClass, labelClass } from './styles'

type Props = {
  roles: AdminRole[]
  value: string[]
  onChange: (names: string[]) => void
  disabled?: boolean
  /** Single-select mode for bulk Add to role. */
  single?: boolean
  label?: string
}

export function RolePicker({
  roles,
  value,
  onChange,
  disabled,
  single = false,
  label = 'Roles',
}: Props) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const opts = roles.filter((r) => !q || r.name.toLowerCase().includes(q))

  function toggle(name: string) {
    if (single) {
      onChange(value.includes(name) ? [] : [name])
      return
    }
    if (value.includes(name)) {
      onChange(value.filter((n) => n !== name))
    } else {
      onChange([...value, name])
    }
  }

  return (
    <div className="space-y-2">
      <label className={labelClass}>
        {label}
        <input
          className={inputClass}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search roles"
          disabled={disabled}
        />
      </label>
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {value.map((name) => (
            <button
              key={name}
              type="button"
              disabled={disabled}
              className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-sm text-indigo-700 hover:border-indigo-400"
              onClick={() => toggle(name)}
            >
              {name} ×
            </button>
          ))}
        </div>
      ) : null}
      <div className="max-h-40 overflow-y-auto rounded-md border border-gray-200">
        {opts.map((role) => (
          <button
            key={role.id}
            type="button"
            disabled={disabled}
            className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
              value.includes(role.name)
                ? 'bg-indigo-600 text-white'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
            onClick={() => toggle(role.name)}
          >
            <span>{role.name}</span>
            <span className="text-xs text-gray-400">Role</span>
          </button>
        ))}
        {opts.length === 0 ? <p className="px-3 py-2 text-sm text-gray-400">No matches</p> : null}
      </div>
    </div>
  )
}
