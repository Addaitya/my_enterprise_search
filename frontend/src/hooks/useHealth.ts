import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'

type Health = {
  status: string
  app_name: string
  realm: string
  opensearch_index: string
}

export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Health>('/health')
      .then(setHealth)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'health check failed')
      })
  }, [])

  return { health, error }
}
