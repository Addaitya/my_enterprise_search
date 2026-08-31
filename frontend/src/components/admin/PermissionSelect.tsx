import { inputClass, labelClass } from './styles'

type Props = {
  value: 'viewer' | 'editor'
  onChange: (next: 'viewer' | 'editor') => void
  disabled?: boolean
  id?: string
}

export function PermissionSelect({ value, onChange, disabled, id }: Props) {
  return (
    <label className={labelClass}>
      Permission
      <select
        id={id}
        className={inputClass}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as 'viewer' | 'editor')}
      >
        <option value="viewer">Viewer</option>
        <option value="editor">Editor</option>
      </select>
    </label>
  )
}
