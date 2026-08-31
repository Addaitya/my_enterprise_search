import { useState } from 'react'

import type { AdminGroup, AdminRole } from '../../api/admin'
import { inputClass, labelClass } from './styles'

export type PrincipalRef = {
  principal_type: 'role' | 'group'
  principal_id: string
  name: string
}

type Props = {
  roles: AdminRole[]
  groups: AdminGroup[]
  value: PrincipalRef[]
  onChange: (next: PrincipalRef[]) => void
  disabled?: boolean
  /** When set, picker is locked to this single principal (Grant files flow). */
  locked?: PrincipalRef | null
}

export function PrincipalPicker({
  roles,
  groups,
  value,
  onChange,
  disabled,
  locked,
}: Props) {
  const [query, setQuery] = useState('')

  if (locked) {
    return (
      <div>
        <p className={labelClass}>Role / group</p>
        <div className="mt-1 flex flex-wrap gap-2">
          <span className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200">
            {locked.name}{' '}
            <span className="text-xs text-slate-500">
              ({locked.principal_type === 'role' ? 'Role' : 'Group'})
            </span>
          </span>
        </div>
      </div>
    )
  }

  const q = query.trim().toLowerCase()
  const roleOpts = roles.filter((r) => !q || r.name.toLowerCase().includes(q))
  const groupOpts = groups.filter((g) => !q || g.name.toLowerCase().includes(q))

  function isSelected(type: 'role' | 'group', id: string) {
    return value.some((v) => v.principal_type === type && v.principal_id === id)
  }

  function toggle(ref: PrincipalRef) {
    if (isSelected(ref.principal_type, ref.principal_id)) {
      onChange(
        value.filter(
          (v) => !(v.principal_type === ref.principal_type && v.principal_id === ref.principal_id),
        ),
      )
    } else {
      onChange([...value, ref])
    }
  }

  return (
    <div className="space-y-2">
      <label className={labelClass}>
        Roles & groups
        <input
          className={inputClass}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search roles and groups"
          disabled={disabled}
        />
      </label>
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {value.map((v) => (
            <button
              key={`${v.principal_type}:${v.principal_id}`}
              type="button"
              disabled={disabled}
              className="rounded-md border border-sky-800 bg-sky-950/40 px-2 py-1 text-sm text-sky-200 hover:border-sky-600"
              onClick={() => toggle(v)}
            >
              {v.name} · {v.principal_type === 'role' ? 'Role' : 'Group'} ×
            </button>
          ))}
        </div>
      ) : null}
      <div className="max-h-40 overflow-y-auto rounded-md border border-slate-800">
        {roleOpts.map((role) => (
          <button
            key={`role:${role.id}`}
            type="button"
            disabled={disabled}
            className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
              isSelected('role', role.id)
                ? 'bg-slate-700 text-white'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
            onClick={() =>
              toggle({ principal_type: 'role', principal_id: role.id, name: role.name })
            }
          >
            <span>{role.name}</span>
            <span className="text-xs text-slate-500">Role</span>
          </button>
        ))}
        {groupOpts.map((group) => (
          <button
            key={`group:${group.id}`}
            type="button"
            disabled={disabled}
            className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm ${
              isSelected('group', group.id)
                ? 'bg-slate-700 text-white'
                : 'text-slate-300 hover:bg-slate-800'
            }`}
            onClick={() =>
              toggle({ principal_type: 'group', principal_id: group.id, name: group.name })
            }
          >
            <span>{group.name}</span>
            <span className="text-xs text-slate-500">Group</span>
          </button>
        ))}
        {roleOpts.length === 0 && groupOpts.length === 0 ? (
          <p className="px-3 py-2 text-sm text-slate-500">No matches</p>
        ) : null}
      </div>
    </div>
  )
}
