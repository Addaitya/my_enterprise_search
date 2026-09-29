import { apiGet, apiPatchJson, apiPostJson } from './client'

export type ConnectorStatus = 'pending' | 'idle' | 'syncing' | 'success' | 'failed'

export type Connector = {
  id: string
  type: string
  name: string
  enabled: boolean
  schedule: string | null
  pipeline_connector_id: string | null
  status: ConnectorStatus
  last_sync_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export type ConnectorWrite = {
  type: string
  name: string
  enabled: boolean
  schedule: string | null
  config: Record<string, string>
}

export type ConnectorPatch = {
  name?: string
  enabled?: boolean
  schedule?: string | null
  config?: Record<string, string>
}

export type ConnectorSyncAccepted = {
  sync_id: string
  status: string
}

export function listConnectors(): Promise<Connector[]> {
  return apiGet<Connector[]>('/admin/connectors')
}

export function createConnector(body: ConnectorWrite): Promise<Connector> {
  return apiPostJson<Connector>('/admin/connectors', body)
}

export function updateConnector(id: string, body: ConnectorPatch): Promise<Connector> {
  return apiPatchJson<Connector>(`/admin/connectors/${id}`, body)
}

export function syncConnector(id: string): Promise<ConnectorSyncAccepted> {
  return apiPostJson<ConnectorSyncAccepted>(`/admin/connectors/${id}/sync`, {})
}
