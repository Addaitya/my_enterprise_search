import type { ReactNode } from 'react'
import { Navbar } from './Navbar'

type AppShellProps = {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  )
}
