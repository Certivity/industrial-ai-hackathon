import type { ComponentType } from 'react'
import { ListChecks, Percent, Scale, ShieldAlert } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import type { RegulationCount } from './stats'
import { shareUnmet } from './stats'
import { useCountUp } from './use-count-up'

interface StatCardProps {
  label: string
  value: number
  decimals?: number
  suffix?: string
  hint: string
  icon: ComponentType<{ className?: string }>
  delay: number
}

function StatCard({ label, value, decimals = 0, suffix = '', hint, icon: Icon, delay }: StatCardProps) {
  const shown = useCountUp(value)
  return (
    <Card className="animate-fade-up" style={{ animationDelay: `${delay}ms` }}>
      <CardContent className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-3xl font-semibold tracking-tight tabular-nums">
            {/* The real value for assistive tech; the animated one is decorative */}
            <span className="sr-only">
              {value.toFixed(decimals)}
              {suffix}
            </span>
            <span aria-hidden="true">
              {shown.toFixed(decimals)}
              {suffix}
            </span>
          </p>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand">
          <Icon className="size-4" />
        </span>
      </CardContent>
    </Card>
  )
}

interface Props {
  unmetCount: number
  checked: number
  byRegulation: RegulationCount[]
}

export function SummaryCards({ unmetCount, checked, byRegulation }: Props) {
  const top = byRegulation[0]
  return (
    <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Unmet requirements"
        value={unmetCount}
        hint="Not satisfied by the documents"
        icon={ShieldAlert}
        delay={0}
      />
      <StatCard
        label="Regulations affected"
        value={byRegulation.length}
        hint={top ? `Most affected: ${top.regulation} (${top.count})` : '-'}
        icon={Scale}
        delay={70}
      />
      <StatCard
        label="Requirements checked"
        value={checked}
        hint="Across all regulations in scope"
        icon={ListChecks}
        delay={140}
      />
      <StatCard
        label="Share unmet"
        value={shareUnmet(unmetCount, checked)}
        decimals={1}
        suffix="%"
        hint={`${unmetCount} of ${checked} requirements`}
        icon={Percent}
        delay={210}
      />
    </section>
  )
}
