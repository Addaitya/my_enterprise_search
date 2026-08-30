import { ApiError, apiPostJson } from './client'

export type SearchHit = {
  file_id: string | null
  chunk_id: string
  chunk_seq: number | null
  score: number
  snippet: string
  meta_file_type: string | null
  object_store_path: string | null
  display_name: string | null
  uploaded_at: string | null
}

export type SearchResponse = {
  q: string
  took_ms: number
  total: number
  hits: SearchHit[]
}

export async function searchFiles(q: string, size = 10): Promise<SearchResponse> {
  return apiPostJson<SearchResponse>('/search', { q, size })
}
