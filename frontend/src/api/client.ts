import { claimsFromAccessToken, userManager } from '../auth/userManager'
import { config } from '../config/env'
import { useAuthStore } from '../store/authStore'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

type ApiFetchOptions = {
  method?: string
  headers?: HeadersInit
  body?: BodyInit | null
  json?: unknown
}

function detailFromBody(text: string): string {
  if (!text) return 'Request failed'
  try {
    const parsed = JSON.parse(text) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
    if (parsed.detail != null) return JSON.stringify(parsed.detail)
  } catch {
    // not JSON
  }
  return text
}

async function refreshSessionOrRedirect(): Promise<boolean> {
  try {
    const user = await userManager.signinSilent()
    if (user?.access_token) {
      const { roles, groups } = claimsFromAccessToken(user.access_token)
      useAuthStore.getState().setSession({
        accessToken: user.access_token,
        username: user.profile.preferred_username ?? user.profile.sub ?? '',
        roles,
        groups,
      })
      return true
    }
  } catch {
    // fall through
  }
  useAuthStore.getState().clearSession()
  window.location.assign('/login')
  return false
}

/** Low-level fetch with Bearer auth + one silent refresh on 401. */
export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {},
  retried = false,
): Promise<Response> {
  const headers = new Headers(options.headers)
  const token = useAuthStore.getState().accessToken
  if (token && path !== '/health') {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let body = options.body ?? null
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  }

  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body,
  })

  if (response.status === 401 && path !== '/health' && !retried) {
    const refreshed = await refreshSessionOrRedirect()
    if (refreshed) {
      return apiFetch(path, options, true)
    }
    throw new ApiError(401, 'Not authenticated')
  }

  return response
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await apiFetch(path)
  if (!response.ok) {
    throw new ApiError(response.status, detailFromBody(await response.text()))
  }
  return (await response.json()) as T
}

export async function apiPostJson<T>(path: string, json: unknown): Promise<T> {
  const response = await apiFetch(path, { method: 'POST', json })
  if (!response.ok) {
    throw new ApiError(response.status, detailFromBody(await response.text()))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export async function apiPutJson<T>(path: string, json: unknown): Promise<T> {
  const response = await apiFetch(path, { method: 'PUT', json })
  if (!response.ok) {
    throw new ApiError(response.status, detailFromBody(await response.text()))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export async function apiPatchJson<T>(path: string, json: unknown): Promise<T> {
  const response = await apiFetch(path, { method: 'PATCH', json })
  if (!response.ok) {
    throw new ApiError(response.status, detailFromBody(await response.text()))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export async function apiDelete(path: string): Promise<void> {
  const response = await apiFetch(path, { method: 'DELETE' })
  if (!response.ok && response.status !== 204) {
    throw new ApiError(response.status, detailFromBody(await response.text()))
  }
}

export { detailFromBody }
