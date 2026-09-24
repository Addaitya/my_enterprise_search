import type { ReactNode } from 'react'

export function Toggle({
  on,
  onChange,
  label,
}: {
  on: boolean
  onChange: (next: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-5 w-10 rounded-full transition-colors ${on ? 'bg-indigo-600' : 'bg-gray-300'}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${on ? 'translate-x-5' : ''}`}
      />
    </button>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-2 border-b border-gray-100 py-3 sm:grid-cols-3 sm:gap-4">
      <div>
        <div className="text-sm text-gray-700">{label}</div>
        {hint ? <div className="text-xs text-gray-400">{hint}</div> : null}
      </div>
      <div className="sm:col-span-2">{children}</div>
    </div>
  )
}

export function TextInput({
  value,
  onChange,
  secret,
}: {
  value: string
  onChange: (value: string) => void
  secret?: boolean
}) {
  return (
    <input
      type={secret ? 'password' : 'text'}
      value={value}
      autoComplete="off"
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
    />
  )
}

export function SaveBar({ saved, onSave }: { saved: boolean; onSave: () => void }) {
  return (
    <div className="mt-2 mb-6 flex justify-end">
      <button
        type="button"
        onClick={onSave}
        className={`rounded-lg px-3 py-1.5 text-sm font-medium text-white ${saved ? 'bg-emerald-600' : 'bg-indigo-600 hover:bg-indigo-700'}`}
      >
        {saved ? 'Saved locally' : 'Save'}
      </button>
    </div>
  )
}
