import { claimsFromAccessToken, userManager } from '../auth/userManager'
import { config } from '../config/env'
import { useAuthStore } from '../store/authStore'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, false)
}

async function apiRequest<T>(path: string, retried: boolean): Promise<T> {
  const headers = new Headers()
  const token = useAuthStore.getState().accessToken
  if (token && path !== '/health') {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(`${config.apiBaseUrl}${path}`, { headers })
  if (response.status === 401 && path !== '/health' && !retried) {
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
      }
      return apiRequest<T>(path, true)
    } catch {
      useAuthStore.getState().clearSession()
      window.location.assign('/login')
      throw new ApiError(401, 'Not authenticated')
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, await response.text())
  }
  return (await response.json()) as T
}
