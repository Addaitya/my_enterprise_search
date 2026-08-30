import { config } from '../config/env'
import { useAuthStore } from '../store/authStore'
import { ApiError, apiDelete, apiGet, apiPostJson, detailFromBody } from './client'

/** Drive convention: non-final parts are multiples of 256 KiB. */
export const UPLOAD_PART_SIZE = 256 * 1024

/** Matches backend `ingest_max_upload_bytes` (25 MiB). */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

const ALLOWED_EXTENSIONS = new Set(['.pdf', '.txt', '.csv'])

const CONTENT_TYPE_BY_EXT: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.csv': 'text/csv',
}

export type InitiateUploadResponse = {
  upload_id: string
  upload_url: string
  status: string
  size_bytes: number
  bytes_received: number
  expires_at: string
}

export type UploadStatusResponse = {
  upload_id: string
  status: string
  file_type: string
  size_bytes: number
  bytes_received: number
  file_id: string | null
  chunk_count: number | null
  error: string | null
  expires_at: string
}

export type CompleteUploadResponse = {
  upload_id: string
  status: string
  id: string
  file_type: string
  size_bytes: number
  object_store_path: string
  ingestion_type: string
  original_source: string | null
  chunk_count: number
  uploaded_at: string
}

export type UploadPhase =
  | 'idle'
  | 'initiating'
  | 'uploading'
  | 'completing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type UploadProgress = {
  phase: UploadPhase
  bytesReceived: number
  sizeBytes: number
  uploadId: string | null
  result: CompleteUploadResponse | null
  error: string | null
}

function extensionOf(filename: string): string {
  const base = filename.replace(/^.*[/\\]/, '')
  const dot = base.lastIndexOf('.')
  if (dot < 0) return ''
  return base.slice(dot).toLowerCase()
}

export function validateUploadFile(file: File): string | null {
  const ext = extensionOf(file.name)
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return 'Only PDF, TXT, and CSV files are supported.'
  }
  if (file.size < 1) {
    return 'File is empty.'
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `File exceeds the ${MAX_UPLOAD_BYTES / (1024 * 1024)} MiB limit.`
  }
  return null
}

function contentTypeFor(file: File): string {
  const ext = extensionOf(file.name)
  if (file.type && file.type !== 'application/octet-stream') {
    return file.type
  }
  return CONTENT_TYPE_BY_EXT[ext] ?? 'application/octet-stream'
}

export async function initiateUpload(file: File): Promise<InitiateUploadResponse> {
  return apiPostJson<InitiateUploadResponse>('/files/uploads', {
    filename: file.name.replace(/^.*[/\\]/, ''),
    size_bytes: file.size,
    content_type: contentTypeFor(file),
  })
}

export async function getUploadStatus(uploadId: string): Promise<UploadStatusResponse> {
  return apiGet<UploadStatusResponse>(`/files/uploads/${uploadId}`)
}

export async function completeUpload(uploadId: string): Promise<CompleteUploadResponse> {
  return apiPostJson<CompleteUploadResponse>(`/files/uploads/${uploadId}/complete`, {})
}

export async function cancelUpload(uploadId: string): Promise<void> {
  await apiDelete(`/files/uploads/${uploadId}`)
}

/**
 * PUT one byte range via XHR.
 *
 * Fetch + `redirect: 'manual'` turns Drive-style HTTP 308 (Resume Incomplete)
 * into an opaque redirect (status 0, no body). XHR exposes 308 normally.
 */
function xhrPutUploadRange(
  uploadId: string,
  start: number,
  end: number,
  total: number,
  chunk: Blob,
): Promise<{ status: number; bytesReceived: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `${config.apiBaseUrl}/files/uploads/${uploadId}`)
    xhr.setRequestHeader('Content-Range', `bytes ${start}-${end}/${total}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    const token = useAuthStore.getState().accessToken
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }

    xhr.onload = () => {
      const text = xhr.responseText
      if (xhr.status !== 200 && xhr.status !== 308) {
        reject(new ApiError(xhr.status, detailFromBody(text)))
        return
      }

      let bytesReceived = end + 1
      try {
        const parsed = JSON.parse(text) as { bytes_received?: number }
        if (typeof parsed.bytes_received === 'number') {
          bytesReceived = parsed.bytes_received
        }
      } catch {
        // keep end+1 fallback
      }

      resolve({ status: xhr.status, bytesReceived })
    }

    xhr.onerror = () => {
      reject(new ApiError(0, 'Network error during upload'))
    }

    xhr.send(chunk)
  })
}

async function putUploadRange(
  uploadId: string,
  start: number,
  end: number,
  total: number,
  chunk: Blob,
): Promise<{ status: number; bytesReceived: number }> {
  try {
    return await xhrPutUploadRange(uploadId, start, end, total, chunk)
  } catch (err) {
    // One silent-refresh path via existing apiGet, then retry the part once.
    if (err instanceof ApiError && err.status === 401) {
      await getUploadStatus(uploadId)
      return xhrPutUploadRange(uploadId, start, end, total, chunk)
    }
    throw err
  }
}

export type ResumableUploadOptions = {
  file: File
  onProgress: (progress: UploadProgress) => void
  signal?: AbortSignal
}

/**
 * Drive-style resumable upload: initiate → sequential 256 KiB PUTs → complete.
 * Sequential `start == bytes_received` (backend v1). Resumes from GET status if needed.
 */
export async function resumableUpload(
  options: ResumableUploadOptions,
): Promise<CompleteUploadResponse> {
  const { file, onProgress, signal } = options
  const validationError = validateUploadFile(file)
  if (validationError) {
    onProgress({
      phase: 'failed',
      bytesReceived: 0,
      sizeBytes: file.size,
      uploadId: null,
      result: null,
      error: validationError,
    })
    throw new ApiError(400, validationError)
  }

  const emit = (partial: Partial<UploadProgress> & Pick<UploadProgress, 'phase'>) => {
    onProgress({
      bytesReceived: 0,
      sizeBytes: file.size,
      uploadId: null,
      result: null,
      error: null,
      ...partial,
    })
  }

  const throwIfAborted = async (uploadId: string | null) => {
    if (!signal?.aborted) return
    if (uploadId) {
      try {
        await cancelUpload(uploadId)
      } catch {
        // best-effort cancel
      }
    }
    emit({ phase: 'cancelled', uploadId, error: 'Upload cancelled' })
    throw new DOMException('Upload cancelled', 'AbortError')
  }

  emit({ phase: 'initiating' })
  await throwIfAborted(null)

  const initiated = await initiateUpload(file)
  const uploadId = initiated.upload_id
  emit({
    phase: 'uploading',
    uploadId,
    bytesReceived: initiated.bytes_received,
  })

  let offset = initiated.bytes_received
  const total = file.size

  // If resuming an interrupted session, trust server bytes_received
  if (offset > 0 && offset < total) {
    const status = await getUploadStatus(uploadId)
    offset = status.bytes_received
  }

  try {
    while (offset < total) {
      await throwIfAborted(uploadId)

      const end = Math.min(total, offset + UPLOAD_PART_SIZE) - 1
      const chunk = file.slice(offset, end + 1)
      const { bytesReceived } = await putUploadRange(uploadId, offset, end, total, chunk)
      offset = bytesReceived
      emit({
        phase: 'uploading',
        uploadId,
        bytesReceived: offset,
      })
    }

    await throwIfAborted(uploadId)
    emit({
      phase: 'completing',
      uploadId,
      bytesReceived: total,
    })

    const result = await completeUpload(uploadId)
    emit({
      phase: 'completed',
      uploadId,
      bytesReceived: total,
      result,
    })
    return result
  } catch (err) {
    if (!(err instanceof DOMException && err.name === 'AbortError')) {
      emit({
        phase: 'failed',
        uploadId,
        bytesReceived: offset,
        error: err instanceof ApiError ? err.detail : err instanceof Error ? err.message : 'Upload failed',
      })
    }
    throw err
  }
}
