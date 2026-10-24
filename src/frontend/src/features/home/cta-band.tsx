import { ArrowRight } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { Button } from '@/components/ui/button'
import type { Route } from '@/lib/use-route'

export function CtaBand({ onNavigate }: { onNavigate: (route: Route) => void }) {
  return (
    <section aria-labelledby="cta" className="px-4 py-20 sm:px-6">
      <Reveal className="relative isolate mx-auto max-w-5xl overflow-hidden rounded-3xl border bg-card px-6 py-14 text-center sm:px-12">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <div className="animate-blob absolute -top-20 -left-10 size-72 rounded-full bg-brand/20 blur-3xl" />
          <div
            className="animate-blob absolute -right-10 -bottom-24 size-72 rounded-full bg-brand-2/20 blur-3xl"
            style={{ animationDelay: '-6s' }}
          />
        </div>
        <h2 id="cta" className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          Check your documentation <span className="text-gradient">against the regulations</span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base text-pretty text-muted-foreground">
          Submit a component's files and see the unmet requirements, or explore the full requirement
          list first.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button
            size="lg"
            className="group h-11 w-full px-6 text-base sm:w-auto"
            onClick={() => onNavigate('assess')}
          >
            Assess a product
            <ArrowRight
              className="transition-transform group-hover:translate-x-0.5"
              data-icon="inline-end"
              aria-hidden
            />
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="h-11 w-full bg-background/60 px-6 text-base sm:w-auto"
            onClick={() => onNavigate('requirements')}
          >
            Browse requirements
          </Button>
        </div>
      </Reveal>
    </section>
  )
}
