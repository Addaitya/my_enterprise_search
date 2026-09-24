import type { ReactNode } from 'react'
import { Navbar } from './Navbar'

type AppShellProps = {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-gray-50 text-gray-900">
      <Navbar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{children}</main>
      <footer className="mt-12 border-t border-gray-200 bg-white py-4">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 text-xs text-gray-400 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>Enterprise Data Search Platform · v1.0.0</span>
          <span>OpenSearch · Keycloak · FastAPI · Postgres · MinIO</span>
        </div>
      </footer>
    </div>
  )
}
