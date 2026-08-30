import { ApiError, apiFetch, apiGet } from './client'

export type FileListItem = {
  id: string
  display_name: string
  file_type: string
  size_bytes: number
  ingestion_type: string
  object_store_path: string
  uploaded_at: string
  updated_at: string
}

export type FileListResponse = {
  items: FileListItem[]
  total: number
  limit: number
  offset: number
}

export async function listFiles(limit = 50, offset = 0): Promise<FileListResponse> {
  return apiGet<FileListResponse>(`/files?limit=${limit}&offset=${offset}`)
}

export async function getFile(fileId: string): Promise<FileListItem> {
  return apiGet<FileListItem>(`/files/${fileId}`)
}

/** Authenticated download via blob URL (plain <a href> would omit Bearer). */
export async function downloadFileContent(
  fileId: string,
  displayName?: string | null,
): Promise<void> {
  const response = await apiFetch(`/files/${fileId}/content`)
  if (!response.ok) {
    const text = await response.text()
    let detail = text || `Download failed (${response.status})`
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (typeof parsed.detail === 'string') detail = parsed.detail
    } catch {
      // keep text
    }
    throw new ApiError(response.status, detail)
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = displayName?.trim() || `file-${fileId}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
