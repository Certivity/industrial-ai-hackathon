import { useEffect, useState } from 'react'
import { loadRequirements, type Requirement } from '@/lib/cases'

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; requirements: Requirement[] }

export function useRequirements(caseId: string | undefined): State {
  const [result, setResult] = useState<{ caseId: string; state: State }>()

  useEffect(() => {
    if (!caseId) return
    let cancelled = false
    loadRequirements(caseId)
      .then((requirements) => {
        if (!cancelled) setResult({ caseId, state: { status: 'ready', requirements } })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        const message = e instanceof Error ? e.message : String(e)
        setResult({ caseId, state: { status: 'error', message } })
      })
    return () => {
      cancelled = true
    }
  }, [caseId])

  if (!caseId) return { status: 'error', message: 'No cases found in cases/' }
  return result?.caseId === caseId ? result.state : { status: 'loading' }
}
