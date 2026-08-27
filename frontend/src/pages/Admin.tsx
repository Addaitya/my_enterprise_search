import { AppShell } from '../components/layout/AppShell'

export function Admin() {
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold text-white">Admin</h1>
      <p className="mt-2 text-slate-400">User, role, group, and file ACL management will live here.</p>
    </AppShell>
  )
}
