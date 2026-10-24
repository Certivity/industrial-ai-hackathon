import { Reveal } from '@/components/reveal'
import { Skeleton } from '@/components/ui/skeleton'
import { useCountUp } from './use-count-up'
import { useHomeStats } from './use-home-stats'

export function StatsStrip() {
  const { stats, failed } = useHomeStats()

  // Without real numbers the strip has nothing to show; hide it rather than fake it.
  if (failed || stats?.requirements === 0) return null

  return (
    <section aria-label="Requirement library in numbers" className="px-4 py-10 sm:px-6">
      <Reveal>
        <dl className="mx-auto grid max-w-4xl grid-cols-1 divide-y divide-border rounded-2xl border bg-card/60 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <Stat value={stats?.requirements ?? null} label="Requirements extracted" />
          <Stat value={stats?.regulations ?? null} label="Regulations covered" />
          <Stat value={stats?.products ?? null} label="Products available to browse" />
        </dl>
      </Reveal>
    </section>
  )
}

function Stat({ value, label }: { value: number | null; label: string }) {
  const { ref, value: shown } = useCountUp<HTMLElement>(value)
  return (
    <div className="flex flex-col items-center gap-1 px-6 py-6 text-center">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd ref={ref} className="order-first h-10 text-4xl font-semibold tracking-tight tabular-nums">
        {value === null ? (
          <Skeleton className="mx-auto h-9 w-16" />
        ) : (
          <>
            <span className="sr-only">{value}</span>
            <span aria-hidden className="text-gradient">
              {shown}
            </span>
          </>
        )}
      </dd>
    </div>
  )
}
