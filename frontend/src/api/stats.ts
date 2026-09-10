import { apiGet } from './client'

export type AdminStatsPlaceholders = {
  active_connectors: boolean
  ingestion_rate_docs_per_hour: boolean
  last_sync: boolean
}

export type AdminStats = {
  avg_query_time_ms: number | null
  total_data_ingested_bytes: number
  total_docs_indexed: number
  active_connectors: number
  ingestion_rate_docs_per_hour: number
  last_sync: string
  placeholders: AdminStatsPlaceholders
}

export async function getAdminStats(): Promise<AdminStats> {
  return apiGet<AdminStats>('/admin/stats')
}
