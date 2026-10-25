import type { Route } from '@/lib/use-route'
import { CtaBand } from './cta-band'
import { FeaturesSection } from './features-section'
import { HeroSection } from './hero-section'
import { HowItWorks } from './how-it-works'
import { ProductShowcase } from './product-showcase'
import { SiteFooter } from './site-footer'
import { StatsStrip } from './stats-strip'

export function HomePage({ onNavigate }: { onNavigate: (route: Route) => void }) {
  return (
    <>
      <main className="overflow-x-clip">
        <HeroSection onNavigate={onNavigate} />
        <StatsStrip />
        <ProductShowcase />
        <HowItWorks />
        <FeaturesSection />
        <CtaBand onNavigate={onNavigate} />
      </main>
      <SiteFooter />
    </>
  )
}
