import { Reveal } from '@/components/reveal'
import { ProductVisual } from './product-visual'
import { SectionHeading } from './section-heading'

export function ProductShowcase() {
  return (
    <section aria-labelledby="showcase-title" className="px-4 pt-16 sm:px-6">
      <SectionHeading
        id="showcase-title"
        eyebrow="The result"
        title="Unmet requirements, with the reasoning"
        description="Every finding names the regulation, version, paragraph and page it comes from."
      />
      <Reveal delay={100} className="mt-10">
        <ProductVisual />
      </Reveal>
    </section>
  )
}
