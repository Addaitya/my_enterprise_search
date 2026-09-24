import { Button } from '../components/ui/Button'
import { userManager } from '../auth/userManager'

export function Login() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <section className="w-full max-w-sm rounded-2xl bg-white p-8 text-center shadow-2xl fade-in">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white">
          ES
        </div>
        <h1 className="mt-4 text-lg font-bold text-gray-900">Sign in</h1>
        <p className="mt-1 text-sm text-gray-500">Use your company account to search files.</p>
        <div className="mt-6">
          <Button onClick={() => void userManager.signinRedirect()}>Login</Button>
        </div>
      </section>
    </div>
  )
}
