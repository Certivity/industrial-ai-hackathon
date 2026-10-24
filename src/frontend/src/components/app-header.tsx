import { cn } from '@/lib/utils'
import type { Route } from '@/lib/use-route'

const links: { route: Route; label: string }[] = [
  { route: 'home', label: 'Home' },
  { route: 'requirements', label: 'All Requirements' },
  { route: 'assess', label: 'Assess Product' },
]

interface Props {
  route: Route
  onNavigate: (route: Route) => void
}

/** Floating glass "island" navigation, fixed at the top centre of every page. */
export function AppHeader({ route, onNavigate }: Props) {
  return (
    <header className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center px-4">
      <nav
        aria-label="Main"
        className="glass pointer-events-auto flex items-center gap-2 rounded-full py-1.5 pr-1.5 pl-5 sm:gap-6"
      >
        <a
          href="#/home"
          onClick={(e) => {
            e.preventDefault()
            onNavigate('home')
          }}
          className="text-lg font-semibold tracking-tight"
          aria-label="regal.ai home"
        >
          regal<span className="text-brand">.ai</span>
        </a>
        <ul className="flex items-center gap-1">
          {links.map(({ route: r, label }) => (
            <li key={r}>
              <a
                href={`#/${r}`}
                onClick={(e) => {
                  e.preventDefault()
                  onNavigate(r)
                }}
                aria-current={route === r ? 'page' : undefined}
                className={cn(
                  'block rounded-full px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring sm:px-4',
                  route === r
                    ? 'bg-foreground text-background'
                    : 'text-foreground/65 hover:bg-foreground/8 hover:text-foreground',
                )}
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
