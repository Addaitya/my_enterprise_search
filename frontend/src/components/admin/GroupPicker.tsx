import { useState } from 'react'

import type { AdminGroup } from '../../api/admin'
import { inputClass, labelClass } from './styles'

type Props = {
  groups: AdminGroup[]
  value: string[]
  onChange: (names: string[]) => void
  disabled?: boolean
  /** Single-select mode for bulk Add to group. */
  single?: boolean
  label?: string
}

export function GroupPicker({
  groups,
  value,
  onChange,
  disabled,
  single = false,
  label = 'Groups',
}: Props) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  // Exclude system / _empty from assignment pickers.
  const product = groups.filter((g) => !g.is_system && g.name !== '_empty')
  const opts = product.filter((g) => !q || g.name.toLowerCase().includes(q))

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
          placeholder="Search groups"
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
              className="rounded-md border border-sky-800 bg-sky-950/40 px-2 py-1 text-sm text-sky-200 hover:border-sky-600"
              onClick={() => toggle(name)}
            >
              {name} ×
            </button>
          ))}
        </div>
      ) : null}
      <div className="max-h-40 overflow-y-auto rounded-md border border-slate-800">
        {opts.map((group) => (
          <button
            key={group.id}
            type="button"
            disabled={disabled}
            className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
              value.includes(group.name)
                ? 'bg-slate-700 text-white'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
            onClick={() => toggle(group.name)}
          >
            <span>{group.name}</span>
            <span className="text-xs text-slate-500">Group</span>
          </button>
        ))}
        {opts.length === 0 ? <p className="px-3 py-2 text-sm text-slate-500">No matches</p> : null}
      </div>
    </div>
  )
}
