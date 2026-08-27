import { create } from 'zustand'

type AuthState = {
  accessToken: string | null
  username: string | null
  roles: string[]
  groups: string[]
  setSession: (session: {
    accessToken: string
    username: string
    roles: string[]
    groups: string[]
  }) => void
  clearSession: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  username: null,
  roles: [],
  groups: [],
  setSession: (session) => set(session),
  clearSession: () =>
    set({ accessToken: null, username: null, roles: [], groups: [] }),
}))
