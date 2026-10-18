'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function LegacyAnalyseRedirect() {
  const router = useRouter()

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, '')
    if (hash.startsWith('holding-')) {
      router.replace(`/holding/${hash.slice('holding-'.length)}`)
      return
    }
    router.replace('/')
  }, [router])

  return (
    <main id="main-content" className="grid min-h-screen place-items-center bg-background px-6">
      <p className="text-sm text-muted-foreground" role="status">
        Opening your decision…
      </p>
    </main>
  )
}
