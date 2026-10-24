import { useEffect, useState } from 'react'
import { prefersReducedMotion } from '@/lib/motion'

/** Counts from 0 to `target` on mount (ease-out). Returns the target straight away if the user prefers reduced motion. */
export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0)
  const reduced = prefersReducedMotion()

  useEffect(() => {
    if (reduced) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      setValue(target * (1 - Math.pow(1 - t, 3)))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration, reduced])

  return reduced ? target : value
}
