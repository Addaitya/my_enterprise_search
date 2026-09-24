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
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {error}
        </p>
      </div>
    )
  }
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50 p-6">
      <div className="spinner" />
      <p className="text-sm text-gray-400">Signing in…</p>
    </div>
  )
}
