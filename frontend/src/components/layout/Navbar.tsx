import { Link } from 'react-router-dom'

import { userManager } from '../../auth/userManager'
import { useAuthStore } from '../../store/authStore'
import { Button } from '../ui/Button'

export function Navbar() {
  const username = useAuthStore((state) => state.username)
  const accessToken = useAuthStore((state) => state.accessToken)
  const roles = useAuthStore((state) => state.roles)
  const isAdmin = roles.includes('admin')
  const signedIn = Boolean(accessToken)

  return (
    <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
      <div className="text-sm font-semibold tracking-wide text-sky-400">
        Enterprise Search
      </div>
      <nav className="flex items-center gap-4 text-sm text-slate-300">
        <Link to="/">Search</Link>
        <Link to="/files">View files</Link>
        {isAdmin ? <Link to="/admin">Admin</Link> : null}
        {signedIn ? (
          <>
            <span className="text-slate-500">{username}</span>
            <Button onClick={() => void userManager.signoutRedirect()}>Logout</Button>
          </>
        ) : (
          <Button onClick={() => void userManager.signinRedirect()}>Login</Button>
        )}
      </nav>
    </header>
  )
}
