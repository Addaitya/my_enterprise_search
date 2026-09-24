import { useEffect, useState } from 'react'

import {
  CONNECTOR_CATALOG,
  CONNECTOR_FIXTURES,
  isSensitiveField,
  type ConnectorCatalogEntry,
  type ConnectorFixture,
} from '../../config/placeholders'
import { Field, SaveBar, TextInput, Toggle } from './primitives'

type Draft = ConnectorFixture

export function IngestionSection() {
  const [connectors, setConnectors] = useState<ConnectorFixture[]>(CONNECTOR_FIXTURES)
  const [editing, setEditing] = useState<Draft | null>(null)
  const [picking, setPicking] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!saved) return
    const timer = window.setTimeout(() => setSaved(false), 2000)
    return () => window.clearTimeout(timer)
  }, [saved])

  function update(id: string, patch: Partial<ConnectorFixture>) {
    setConnectors((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }

  function saveDraft(draft: Draft) {
    setConnectors((rows) => {
      const exists = rows.some((row) => row.id === draft.id)
      return exists ? rows.map((row) => (row.id === draft.id ? draft : row)) : [...rows, draft]
    })
    setEditing(null)
  }

  function addType(entry: ConnectorCatalogEntry) {
    const id = `${entry.type}-${Date.now()}`
    const values: Record<string, string> = {}
    for (const field of entry.fields) values[field.key] = field.kind === 'toggle' ? 'false' : ''
    setEditing({
      id,
      type: entry.type,
      name: entry.label,
      enabled: false,
      schedule: '',
      cdc: false,
      values,
    })
    setPicking(false)
  }

  return (
    <div>
      <div className="mb-5 rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Connectors</h2>
            <p className="text-xs text-gray-400">Local placeholders. None of these are connected.</p>
          </div>
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
            Placeholder
          </span>
        </div>
        {notice ? (
          <p className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-700">{notice}</p>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-400">
              <tr>
                <th className="px-5 py-2 font-medium">Connector</th>
                <th className="px-5 py-2 font-medium">Status</th>
                <th className="px-5 py-2 font-medium">Enabled</th>
                <th className="px-5 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {connectors.map((row) => {
                const entry = CONNECTOR_CATALOG.find((item) => item.type === row.type)
                return (
                  <tr key={row.id} className="border-t border-gray-100">
                    <td className="px-5 py-2 text-gray-900">
                      {entry?.icon} {row.name}
                    </td>
                    <td className="px-5 py-2 text-gray-500">Not connected</td>
                    <td className="px-5 py-2">
                      <Toggle
                        label={`Enable ${row.name}`}
                        on={row.enabled}
                        onChange={(enabled) => update(row.id, { enabled })}
                      />
                    </td>
                    <td className="px-5 py-2">
                      <button
                        type="button"
                        className="mr-3 text-indigo-600 hover:text-indigo-700"
                        onClick={() => setEditing({ ...row, values: { ...row.values } })}
                      >
                        Configure
                      </button>
                      <button
                        type="button"
                        className="text-indigo-600 hover:text-indigo-700"
                        onClick={() => setNotice(`Sync is not connected for ${row.name}.`)}
                      >
                        Sync Now
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="border-t border-gray-100 p-4">
          <button
            type="button"
            onClick={() => setPicking(true)}
            className="w-full rounded-xl border border-dashed border-gray-300 px-3 py-3 text-sm text-gray-600 hover:border-indigo-300 hover:bg-indigo-50"
          >
            + Add connector
          </button>
        </div>
      </div>
      <SaveBar saved={saved} onSave={() => setSaved(true)} />
      {editing ? (
        <ConnectorModal
          draft={editing}
          onClose={() => setEditing(null)}
          onSave={saveDraft}
        />
      ) : null}
      {picking ? <AddConnectorPicker onClose={() => setPicking(false)} onPick={addType} /> : null}
    </div>
  )
}

function ConnectorModal({
  draft,
  onClose,
  onSave,
}: {
  draft: Draft
  onClose: () => void
  onSave: (draft: Draft) => void
}) {
  const [local, setLocal] = useState(draft)
  const entry = CONNECTOR_CATALOG.find((item) => item.type === local.type)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="scrollbar-thin max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Configure connector"
      >
        <h2 className="text-lg font-bold text-gray-900">Configure connector</h2>
        <p className="mt-1 text-xs text-gray-400">Stored in this page only. Not connected.</p>
        <Field label="Name">
          <TextInput value={local.name} onChange={(name) => setLocal({ ...local, name })} />
        </Field>
        {entry?.fields.map((field) => (
          <Field key={field.key} label={field.label}>
            {field.kind === 'toggle' ? (
              <Toggle
                label={field.label}
                on={local.values[field.key] === 'true'}
                onChange={(on) =>
                  setLocal({ ...local, values: { ...local.values, [field.key]: on ? 'true' : 'false' } })
                }
              />
            ) : field.kind === 'textarea' ? (
              <textarea
                rows={3}
                value={local.values[field.key] ?? ''}
                onChange={(event) =>
                  setLocal({ ...local, values: { ...local.values, [field.key]: event.target.value } })
                }
                className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
              />
            ) : (
              <TextInput
                secret={isSensitiveField(field.key)}
                value={local.values[field.key] ?? ''}
                onChange={(value) => setLocal({ ...local, values: { ...local.values, [field.key]: value } })}
              />
            )}
          </Field>
        ))}
        <Field label="Sync schedule" hint="Cron, stored locally">
          <TextInput value={local.schedule} onChange={(schedule) => setLocal({ ...local, schedule })} />
        </Field>
        <Field label="CDC">
          <Toggle label="CDC" on={local.cdc} onChange={(cdc) => setLocal({ ...local, cdc })} />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="rounded-lg px-3 py-1.5 text-sm text-gray-600" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            onClick={() => onSave(local)}
          >
            Save locally
          </button>
        </div>
      </div>
    </div>
  )
}

function AddConnectorPicker({
  onClose,
  onPick,
}: {
  onClose: () => void
  onPick: (entry: ConnectorCatalogEntry) => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Add connector"
      >
        <h2 className="text-lg font-bold text-gray-900">Add connector</h2>
        <div className="mt-4 grid max-h-96 grid-cols-2 gap-2 overflow-y-auto">
          {CONNECTOR_CATALOG.map((entry) => (
            <button
              key={entry.type}
              type="button"
              onClick={() => onPick(entry)}
              className="rounded-xl border border-gray-200 px-3 py-3 text-left text-sm hover:border-indigo-300 hover:bg-indigo-50"
            >
              <div className="text-2xl">{entry.icon}</div>
              <div className="mt-1 text-gray-700">{entry.label}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
