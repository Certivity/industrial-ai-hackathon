import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Route } from '@/lib/use-route'

const tabs: { route: Route; label: string }[] = [
  { route: 'requirements', label: 'All Requirements' },
  { route: 'assess', label: 'Assess Product' },
]

interface Props {
  route: Route
  onNavigate: (route: Route) => void
}

export function AppHeader({ route, onNavigate }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-8 px-6">
        <a href="#/" className="text-lg font-semibold tracking-tight" aria-label="regal.ai home">
          regal<span className="text-primary/50">.ai</span>
        </a>
        <Tabs value={route} onValueChange={(value) => onNavigate(value as Route)} className="h-full gap-0">
          <TabsList variant="line" className="gap-4 group-data-horizontal/tabs:h-full">
            {tabs.map(({ route: r, label }) => (
              <TabsTrigger
                key={r}
                value={r}
                className="h-full px-1 after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-foreground after:opacity-0 data-active:after:opacity-100"
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
    </header>
  )
}
