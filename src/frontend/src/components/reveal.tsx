import { useEffect, useRef, type ComponentProps } from 'react'
import { cn } from '@/lib/utils'

interface Props extends ComponentProps<'div'> {
  /** Stagger siblings by passing increasing delays, in ms. */
  delay?: number
}

/** Fades and slides its children in the first time they scroll into view. */
export function Reveal({ delay = 0, className, style, ...props }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        el.setAttribute('data-revealed', '')
        observer.disconnect()
      },
      { threshold: 0.15 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      data-reveal
      className={cn(className)}
      style={{ ...style, '--reveal-delay': `${delay}ms` } as React.CSSProperties}
      {...props}
    />
  )
}
