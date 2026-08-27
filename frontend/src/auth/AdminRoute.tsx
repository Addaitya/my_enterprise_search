import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { AppShell } from '../components/layout/AppShell'
import { useAuthStore } from '../store/authStore'

type AdminRouteProps = {
  children: ReactNode
}

export function AdminRoute({ children }: AdminRouteProps) {
  const accessToken = useAuthStore((state) => state.accessToken)
  const roles = useAuthStore((state) => state.roles)
  const location = useLocation()

  if (!accessToken) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  if (!roles.includes('admin')) {
    return (
      <AppShell>
        <h1 className="text-2xl font-semibold text-white">Forbidden</h1>
        <p className="mt-2 text-slate-400">Admin role required.</p>
      </AppShell>
    )
  }
  return children
}
