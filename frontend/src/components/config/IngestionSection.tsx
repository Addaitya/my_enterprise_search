import { useCallback, useEffect, useState } from 'react'

import {
  createConnector,
  listConnectors,
  syncConnector,
  updateConnector,
  type Connector,
  type ConnectorPatch,
} from '../../api/connectors'
import { ApiError } from '../../api/client'
import {
  CONNECTOR_CATALOG,
  isSensitiveField,
  type ConnectorCatalogEntry,
  type ConnectorField,
} from '../../config/placeholders'
import { Field, TextInput, Toggle } from './primitives'

type Draft = {
  id: string | null
  type: string
  name: string
  enabled: boolean
  schedule: string
  cdc: boolean
  cdcTouched: boolean
  values: Record<string, string>
  originalName: string
  originalSchedule: string
}

function emptyValues(entry: ConnectorCatalogEntry, forCreate: boolean): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of entry.fields) {
    values[field.key] = forCreate && field.kind === 'toggle' ? 'false' : ''
  }
  return values
}

function pipelineErrorCopy(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return 'The pipeline URL is not configured.'
    if (err.status === 502) return 'The pipeline is unreachable.'
    return err.detail || `Request failed (${err.status})`
  }
  return err instanceof Error ? err.message : 'Request failed'
}

function configFromDraft(draft: Draft, entry: ConnectorCatalogEntry | undefined): Record<string, string> {
  const config: Record<string, string> = {}
  if (draft.id === null) {
    for (const field of entry?.fields ?? []) {
      config[field.key] = draft.values[field.key] ?? (field.kind === 'toggle' ? 'false' : '')
    }
    config.cdc = draft.cdc ? 'true' : 'false'
    return config
  }
  for (const field of entry?.fields ?? []) {
    const value = draft.values[field.key] ?? ''
    if (field.kind === 'toggle') {
      if (value === 'true' || value === 'false') config[field.key] = value
      continue
    }
    if (!value.trim()) continue
    config[field.key] = value
  }
  if (draft.cdcTouched) config.cdc = draft.cdc ? 'true' : 'false'
  return config
}

function patchFromDraft(draft: Draft, entry: ConnectorCatalogEntry | undefined): ConnectorPatch {
  const patch: ConnectorPatch = {}
  if (draft.name !== draft.originalName) patch.name = draft.name
  if (draft.schedule !== draft.originalSchedule) {
    const schedule = draft.schedule.trim()
    patch.schedule = schedule || null
  }
  const config = configFromDraft(draft, entry)
  if (Object.keys(config).length > 0) patch.config = config
  return patch
}

export function IngestionSection() {
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [editing, setEditing] = useState<Draft | null>(null)
  const [picking, setPicking] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setConnectors(await listConnectors())
    } catch (err) {
      setConnectors([])
      setError(pipelineErrorCopy(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!saved) return
    const timer = window.setTimeout(() => setSaved(false), 2000)
    return () => window.clearTimeout(timer)
  }, [saved])

  function flashSaved() {
    setNotice(null)
    setSaved(true)
  }

  function replaceRow(next: Connector) {
    setConnectors((rows) => rows.map((row) => (row.id === next.id ? next : row)))
  }

  async function setEnabled(row: Connector, enabled: boolean) {
    const previous = row.enabled
    replaceRow({ ...row, enabled })
    setBusyId(row.id)
    setError(null)
    try {
      const updated = await updateConnector(row.id, { enabled })
      replaceRow(updated)
      flashSaved()
    } catch (err) {
      replaceRow({ ...row, enabled: previous })
      setNotice(pipelineErrorCopy(err))
    } finally {
      setBusyId(null)
    }
  }

  async function syncRow(row: Connector) {
    setBusyId(row.id)
    setError(null)
    setNotice(null)
    try {
      await syncConnector(row.id)
      flashSaved()
      await load()
    } catch (err) {
      setNotice(pipelineErrorCopy(err))
      await load()
    } finally {
      setBusyId(null)
    }
  }

  function addType(entry: ConnectorCatalogEntry) {
    setEditing({
      id: null,
      type: entry.type,
      name: entry.label,
      enabled: false,
      schedule: '',
      cdc: false,
      cdcTouched: false,
      values: emptyValues(entry, true),
      originalName: entry.label,
      originalSchedule: '',
    })
    setPicking(false)
  }

  function editRow(row: Connector) {
    const entry = CONNECTOR_CATALOG.find((item) => item.type === row.type)
    setEditing({
      id: row.id,
      type: row.type,
      name: row.name,
      enabled: row.enabled,
      schedule: row.schedule ?? '',
      cdc: false,
      cdcTouched: false,
      values: entry ? emptyValues(entry, false) : {},
      originalName: row.name,
      originalSchedule: row.schedule ?? '',
    })
  }

  return (
    <div>
      <div className="mb-5 rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Connectors</h2>
          </div>
          {saved ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              Saved
            </span>
          ) : null}
        </div>
        {error ? (
          <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-sm text-rose-700">{error}</p>
        ) : null}
        {notice ? (
          <p className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-sm text-rose-700">{notice}</p>
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
              {loading ? (
                <tr className="border-t border-gray-100">
                  <td className="px-5 py-3 text-gray-400" colSpan={4}>
                    Loading…
                  </td>
                </tr>
              ) : connectors.length === 0 ? (
                <tr className="border-t border-gray-100">
                  <td className="px-5 py-3 text-gray-400" colSpan={4}>
                    No connectors
                  </td>
                </tr>
              ) : (
                connectors.map((row) => {
                  const entry = CONNECTOR_CATALOG.find((item) => item.type === row.type)
                  return (
                    <tr key={row.id} className="border-t border-gray-100">
                      <td className="px-5 py-2 text-gray-900">
                        {entry?.icon} {row.name}
                      </td>
                      <td className="px-5 py-2 text-gray-500">
                        <div>{row.status}</div>
                        {row.last_error ? (
                          <div className="mt-0.5 text-xs text-rose-600">{row.last_error}</div>
                        ) : null}
                      </td>
                      <td className="px-5 py-2">
                        <Toggle
                          label={`Enable ${row.name}`}
                          on={row.enabled}
                          onChange={(enabled) => {
                            if (busyId === row.id) return
                            void setEnabled(row, enabled)
                          }}
                        />
                      </td>
                      <td className="px-5 py-2">
                        <button
                          type="button"
                          className="mr-3 text-indigo-600 hover:text-indigo-700 disabled:text-gray-300"
                          disabled={busyId === row.id}
                          onClick={() => editRow(row)}
                        >
                          Configure
                        </button>
                        <button
                          type="button"
                          className="text-indigo-600 hover:text-indigo-700 disabled:text-gray-300"
                          disabled={busyId === row.id}
                          onClick={() => void syncRow(row)}
                        >
                          Sync Now
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
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
      {editing ? (
        <ConnectorModal
          draft={editing}
          onClose={() => setEditing(null)}
          onSaved={(row) => {
            if (editing.id) replaceRow(row)
            else setConnectors((rows) => [row, ...rows])
            setEditing(null)
            flashSaved()
          }}
          onError={(message) => setNotice(message)}
        />
      ) : null}
      {picking ? <AddConnectorPicker onClose={() => setPicking(false)} onPick={addType} /> : null}
    </div>
  )
}

function ConnectorModal({
  draft,
  onClose,
  onSaved,
  onError,
}: {
  draft: Draft
  onClose: () => void
  onSaved: (row: Connector) => void
  onError: (message: string) => void
}) {
  const [local, setLocal] = useState(draft)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const entry = CONNECTOR_CATALOG.find((item) => item.type === local.type)
  const isNew = local.id === null

  function setField(field: ConnectorField, value: string) {
    setLocal({ ...local, values: { ...local.values, [field.key]: value } })
  }

  async function save() {
    const name = local.name.trim()
    if (!name) {
      setFormError('Name is required.')
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      if (isNew) {
        const created = await createConnector({
          type: local.type,
          name,
          enabled: local.enabled,
          schedule: local.schedule.trim() || null,
          config: configFromDraft({ ...local, name }, entry),
        })
        onSaved(created)
        return
      }
      const patch = patchFromDraft({ ...local, name }, entry)
      if (Object.keys(patch).length === 0) {
        onClose()
        return
      }
      onSaved(await updateConnector(local.id as string, patch))
    } catch (err) {
      const message = pipelineErrorCopy(err)
      setFormError(message)
      onError(message)
    } finally {
      setSaving(false)
    }
  }

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
        {isNew ? null : (
          <p className="mt-1 text-xs text-gray-400">
            Saved connection fields are not shown again. Leave a field blank to keep the pipeline&apos;s current
            value, or fill it to replace it.
          </p>
        )}
        {formError ? (
          <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {formError}
          </p>
        ) : null}
        <Field label="Name">
          <TextInput value={local.name} onChange={(name) => setLocal({ ...local, name })} />
        </Field>
        {entry?.fields.map((field) => (
          <Field key={field.key} label={field.label}>
            {field.kind === 'toggle' ? (
              <Toggle
                label={field.label}
                on={local.values[field.key] === 'true'}
                onChange={(on) => setField(field, on ? 'true' : 'false')}
              />
            ) : field.kind === 'textarea' ? (
              <textarea
                rows={3}
                value={local.values[field.key] ?? ''}
                onChange={(event) => setField(field, event.target.value)}
                className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
              />
            ) : (
              <TextInput
                secret={isSensitiveField(field.key)}
                value={local.values[field.key] ?? ''}
                onChange={(value) => setField(field, value)}
              />
            )}
          </Field>
        ))}
        <Field label="Sync schedule" hint="Cron expression">
          <TextInput value={local.schedule} onChange={(schedule) => setLocal({ ...local, schedule })} />
        </Field>
        <Field label="CDC">
          <Toggle
            label="CDC"
            on={local.cdc}
            onChange={(cdc) => setLocal({ ...local, cdc, cdcTouched: true })}
          />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="rounded-lg px-3 py-1.5 text-sm text-gray-600" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            disabled={saving}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-indigo-300"
            onClick={() => void save()}
          >
            {saving ? 'Saving…' : 'Save'}
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
