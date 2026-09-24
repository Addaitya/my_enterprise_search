import { NavLink } from 'react-router-dom'

import { userManager } from '../../auth/userManager'
import { useAuthStore } from '../../store/authStore'
import { Button } from '../ui/Button'

function initials(username: string) {
  const parts = username.split(/[^A-Za-z0-9]+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  const compact = username.replace(/[^A-Za-z0-9]/g, '')
  return (compact.slice(0, 2) || '?').toUpperCase()
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-full px-3 py-1 text-sm transition-colors ${
    isActive ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-100'
  }`

export function Navbar() {
  const username = useAuthStore((state) => state.username)
  const accessToken = useAuthStore((state) => state.accessToken)
  const roles = useAuthStore((state) => state.roles)
  const isAdmin = roles.includes('admin')
  const signedIn = Boolean(accessToken)

  return (
    <header className="sticky top-0 z-40 border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            ES
          </div>
          <div>
            <div className="text-sm font-bold text-gray-900">Enterprise Search</div>
            <div className="hidden text-xs text-gray-400 sm:block">
              Unified data discovery platform
            </div>
          </div>
        </div>
        <nav className="flex flex-1 flex-wrap items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            Search
          </NavLink>
          <NavLink to="/upload" className={linkClass}>
            Upload
          </NavLink>
          <NavLink to="/files" className={linkClass}>
            View files
          </NavLink>
          {isAdmin ? (
            <>
              <NavLink to="/dashboard" className={linkClass}>
                Dashboard
              </NavLink>
              <NavLink to="/admin" className={linkClass}>
                Access Control(Admin)
              </NavLink>
              <NavLink to="/configuration" className={linkClass}>
                Configuration
              </NavLink>
            </>
          ) : null}
        </nav>
        {signedIn ? (
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-indigo-100 text-xs font-medium text-indigo-700">
              {initials(username ?? '')}
            </span>
            <span className="hidden text-sm text-gray-600 sm:inline">{username}</span>
            <Button onClick={() => void userManager.signoutRedirect()}>Logout</Button>
          </div>
        ) : (
          <Button onClick={() => void userManager.signinRedirect()}>Login</Button>
        )}
      </div>
    </header>
  )
}
