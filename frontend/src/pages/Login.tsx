import { AppShell } from '../components/layout/AppShell'
import { Button } from '../components/ui/Button'
import { userManager } from '../auth/userManager'

export function Login() {
  return (
    <AppShell>
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold text-white">Sign in</h1>
        <p className="text-slate-400">Use your company account to search files.</p>
        <Button onClick={() => void userManager.signinRedirect()}>Login</Button>
      </section>
    </AppShell>
  )
}
