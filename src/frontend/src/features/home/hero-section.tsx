import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import carImage from '@/assets/mercedes-in-motion.jpg'
import type { Route } from '@/lib/use-route'
import { CarHotspots } from './car-hotspots'

const stagger = (ms: number) => ({ animationDelay: `${ms}ms` })

// On wide screens the photo fades into the tinted text panel, like a split banner.
const fadeLeft = 'lg:[mask-image:linear-gradient(to_right,transparent,black_22%)]'

export function HeroSection({ onNavigate }: { onNavigate: (route: Route) => void }) {
  return (
    <section
      aria-labelledby="hero-title"
      className="relative isolate overflow-hidden bg-[color-mix(in_oklab,var(--brand-2)_9%,var(--background))]"
    >
      {/* Text panel: stacked above the photo on small screens, overlaid on its left on large ones. */}
      <div className="px-6 pt-28 pb-8 lg:absolute lg:inset-y-0 lg:left-0 lg:z-10 lg:flex lg:w-[44%] lg:flex-col lg:justify-center lg:px-12 lg:py-0 lg:pt-16 xl:px-20">
        <p
          className="animate-fade-up text-xs font-medium tracking-[0.2em] text-foreground/60 uppercase sm:text-sm"
          style={stagger(0)}
        >
          regal.ai · Regulatory intelligence
        </p>
        <h1
          id="hero-title"
          className="animate-fade-up mt-4 text-4xl font-semibold tracking-tight text-balance sm:text-5xl xl:text-6xl"
          style={stagger(100)}
        >
          Compliance that doesn't <span className="text-gradient">slow you down</span>
        </h1>
        <p
          className="animate-fade-up mt-5 max-w-md text-base text-pretty text-foreground/70 sm:text-lg"
          style={stagger(200)}
        >
          Check a component's technical documentation against regulations and see the unmet
          requirements, with citations, before approval does.
        </p>
        <div
          className="animate-fade-up mt-8 flex flex-wrap items-center gap-3"
          style={stagger(300)}
        >
          <Button size="lg" className="group h-11 px-6 text-base" onClick={() => onNavigate('assess')}>
            Assess a product
            <ArrowRight
              className="transition-transform group-hover:translate-x-0.5"
              data-icon="inline-end"
              aria-hidden
            />
          </Button>
          <Button
            size="lg"
            variant="ghost"
            className="h-11 px-4 text-base"
            onClick={() => onNavigate('requirements')}
          >
            Browse requirements
          </Button>
        </div>
      </div>

      {/* Photo with hotspots. The wrapper keeps the photo's aspect ratio so the dots stay on their parts. */}
      <div
        className="animate-fade-up relative aspect-[1200/795] w-full lg:ml-auto lg:w-[62%]"
        style={stagger(150)}
      >
        <img
          src={carImage}
          alt="Silver sports coupe driving on a race track"
          fetchPriority="high"
          className={`absolute inset-0 size-full object-cover ${fadeLeft}`}
        />
        <CarHotspots />
        <p className="absolute right-3 bottom-3 rounded-full bg-black/40 px-3 py-1 text-xs text-white backdrop-blur">
          Select a dot to see example regulations
        </p>
      </div>
    </section>
  )
}
