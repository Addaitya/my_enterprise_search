import { useEffect, useState, type ReactNode } from 'react'
import type { User } from 'oidc-client-ts'

import { useAuthStore } from '../store/authStore'
import { claimsFromAccessToken, userManager } from './userManager'

type AuthProviderProps = {
  children: ReactNode
}

function hydrateUser(user: User | null) {
  const { setSession, clearSession } = useAuthStore.getState()
  if (!user || user.expired || !user.access_token) {
    clearSession()
    return
  }
  const { roles, groups } = claimsFromAccessToken(user.access_token)
  setSession({
    accessToken: user.access_token,
    username: user.profile.preferred_username ?? user.profile.sub ?? '',
    roles,
    groups,
  })
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    userManager.getUser().then((user) => {
      if (cancelled) {
        return
      }
      hydrateUser(user)
      setReady(true)
    }).catch(() => {
      if (cancelled) {
        return
      }
      useAuthStore.getState().clearSession()
      setReady(true)
    })

    const onLoaded = (user: User) => hydrateUser(user)
    const onUnloaded = () => useAuthStore.getState().clearSession()
    const onSilentRenewError = () => {
      useAuthStore.getState().clearSession()
    }

    userManager.events.addUserLoaded(onLoaded)
    userManager.events.addUserUnloaded(onUnloaded)
    userManager.events.addSilentRenewError(onSilentRenewError)

    return () => {
      cancelled = true
      userManager.events.removeUserLoaded(onLoaded)
      userManager.events.removeUserUnloaded(onUnloaded)
      userManager.events.removeSilentRenewError(onSilentRenewError)
    }
  }, [])

  if (!ready) {
    return <p className="p-6 text-sm text-slate-400">Loading session…</p>
  }

  return children
}
