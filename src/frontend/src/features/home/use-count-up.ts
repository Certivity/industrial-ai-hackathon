import { useEffect, useRef, useState } from 'react'
import { prefersReducedMotion } from '@/lib/motion'

const DURATION_MS = 1400

/**
 * Counts from 0 to `target` the first time the returned ref scrolls into view.
 * Stays at 0 while `target` is null (data still loading). Skips the animation
 * when the user prefers reduced motion.
 */
export function useCountUp<T extends HTMLElement>(target: number | null) {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(false)
  const [value, setValue] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        setInView(true)
        observer.disconnect()
      },
      { threshold: 0.4 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (target === null || !inView) return
    if (prefersReducedMotion()) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min((now - start) / DURATION_MS, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(Math.round(target * eased))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, inView])

  // With reduced motion the final number is shown straight away, no animation.
  const settled = target !== null && inView && prefersReducedMotion()
  return { ref, value: settled ? target : value }
}
