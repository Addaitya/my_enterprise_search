import { useEffect } from 'react'

import { handleSilentCallback } from './userManager'

export function SilentCallback() {
  useEffect(() => {
    void handleSilentCallback()
  }, [])
  return null
}
