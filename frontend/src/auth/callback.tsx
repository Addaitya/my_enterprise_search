import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { handleRedirectCallback } from './userManager'

export function Callback() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    handleRedirectCallback()
      .then(() => navigate('/', { replace: true }))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Sign-in failed')
      })
  }, [navigate])

  if (error) {
    return <p className="p-6 text-sm text-red-400">{error}</p>
  }
  return <p className="p-6 text-sm text-slate-400">Signing in…</p>
}
