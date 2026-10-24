import { ArrowRight, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Route } from '@/lib/use-route'
import { ProductVisual } from './product-visual'

const stagger = (ms: number) => ({ animationDelay: `${ms}ms` })

export function HeroSection({ onNavigate }: { onNavigate: (route: Route) => void }) {
  return (
    <section className="relative isolate overflow-hidden px-4 pt-32 pb-16 sm:px-6 sm:pt-40">
      <HeroBackground />

      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <Badge
          variant="outline"
          className="animate-fade-up h-7 gap-1.5 bg-background/60 px-3 text-sm backdrop-blur"
          style={stagger(0)}
        >
          <Sparkles className="text-brand" aria-hidden />
          Regulatory checks for vehicle components
        </Badge>

        <h1
          className="animate-fade-up mt-6 text-4xl font-semibold tracking-tight text-balance sm:text-5xl md:text-6xl"
          style={stagger(100)}
        >
          Know what your documentation <span className="text-gradient">is missing</span> before
          approval does
        </h1>

        <p
          className="animate-fade-up mt-6 max-w-2xl text-base text-pretty text-foreground/70 sm:text-lg"
          style={stagger(200)}
        >
          Upload a component's technical documentation. regal.ai checks it against UN regulations
          and returns the unmet requirements, each with its reasoning and a citation to the exact
          paragraph.
        </p>

        <div
          className="animate-fade-up mt-8 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row"
          style={stagger(300)}
        >
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
            className="h-11 w-full bg-background/60 px-6 text-base backdrop-blur sm:w-auto"
            onClick={() => onNavigate('requirements')}
          >
            Browse requirements
          </Button>
        </div>
      </div>

      <div className="animate-fade-up mt-14 sm:mt-20" style={stagger(450)}>
        <ProductVisual />
      </div>
    </section>
  )
}

function HeroBackground() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
      <div className="absolute inset-0 bg-[radial-gradient(color-mix(in_oklab,var(--foreground)_14%,transparent)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_70%_60%_at_50%_30%,black,transparent)]" />
      <div className="animate-blob absolute -top-24 left-1/2 size-[28rem] -translate-x-[90%] rounded-full bg-brand/25 blur-3xl" />
      <div
        className="animate-blob absolute top-10 left-1/2 size-[26rem] translate-x-[-5%] rounded-full bg-brand-2/25 blur-3xl"
        style={{ animationDelay: '-5s' }}
      />
      <div
        className="animate-blob absolute top-72 left-1/2 hidden size-80 -translate-x-1/2 rounded-full bg-brand/15 blur-3xl md:block"
        style={{ animationDelay: '-9s' }}
      />
    </div>
  )
}
