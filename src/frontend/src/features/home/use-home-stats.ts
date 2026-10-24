import { useEffect, useState } from 'react'
import { listCases, loadRequirements } from '@/lib/cases'

export interface HomeStats {
  requirements: number
  regulations: number
  products: number
}

export interface HomeStatsState {
  /** `null` while loading. */
  stats: HomeStats | null
  failed: boolean
}

/** Real numbers derived from the cases/ folder. */
export function useHomeStats(): HomeStatsState {
  const [stats, setStats] = useState<HomeStats | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const cases = listCases()
    Promise.all(cases.map((c) => loadRequirements(c.id)))
      .then((lists) => {
        if (cancelled) return
        const all = lists.flat()
        setStats({
          requirements: all.length,
          regulations: new Set(all.map((r) => r.source.regulation)).size,
          products: cases.length,
        })
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { stats, failed }
}
