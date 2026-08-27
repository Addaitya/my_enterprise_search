import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

import { config } from '../config/env'

export const userManager = new UserManager({
  authority: `${config.keycloakUrl}/realms/${config.keycloakRealm}`,
  client_id: config.keycloakClientId,
  redirect_uri: `${window.location.origin}/auth/callback`,
  silent_redirect_uri: `${window.location.origin}/auth/silent-callback`,
  post_logout_redirect_uri: `${window.location.origin}/`,
  response_type: 'code',
  scope: 'openid profile email',
  automaticSilentRenew: true,
  loadUserInfo: false,
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
})

let callbackPromise: Promise<User> | null = null
let silentPromise: Promise<void> | null = null

export function handleRedirectCallback() {
  if (!callbackPromise) {
    callbackPromise = userManager.signinRedirectCallback()
  }
  return callbackPromise
}

export function handleSilentCallback() {
  if (!silentPromise) {
    silentPromise = userManager.signinSilentCallback()
  }
  return silentPromise
}

const GROUPS_EMPTY_SENTINEL = '_empty'

export function claimsFromAccessToken(accessToken: string): {
  roles: string[]
  groups: string[]
} {
  const payload = accessToken.split('.')[1]
  if (!payload) {
    return { roles: [], groups: [] }
  }
  const padded = payload.replace(/-/g, '+').replace(/_/g, '/')
  const json = JSON.parse(atob(padded.padEnd(padded.length + ((4 - (padded.length % 4)) % 4), '='))) as {
    roles?: string | string[]
    groups?: string | string[]
  }
  return {
    roles: asStringList(json.roles),
    groups: asStringList(json.groups).filter((group) => group !== GROUPS_EMPTY_SENTINEL),
  }
}

function asStringList(value: string | string[] | undefined): string[] {
  if (!value) {
    return []
  }
  if (typeof value === 'string') {
    return value.split(',').map((part) => part.trim()).filter(Boolean)
  }
  return value.map((part) => String(part).trim()).filter(Boolean)
}
