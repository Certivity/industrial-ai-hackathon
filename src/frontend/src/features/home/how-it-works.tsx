import { ClipboardCheck, Scale, Upload, type LucideIcon } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { SectionHeading } from './section-heading'

interface Step {
  icon: LucideIcon
  title: string
  body: string
}

const steps: Step[] = [
  {
    icon: Upload,
    title: 'Upload documentation',
    body: 'Drop in the technical files for a component. Several documents can be submitted together.',
  },
  {
    icon: Scale,
    title: 'Analyse against UN regulations',
    body: 'The documentation is checked against the applicable requirements, one atomic requirement at a time.',
  },
  {
    icon: ClipboardCheck,
    title: 'Review unmet requirements',
    body: 'See what is missing, why it was flagged, and the regulation paragraph it comes from.',
  },
]

export function HowItWorks() {
  return (
    <section aria-labelledby="how-it-works" className="px-4 py-20 sm:px-6">
      <div className="mx-auto max-w-5xl">
        <SectionHeading
          id="how-it-works"
          eyebrow="How it works"
          title="From documents to findings in three steps"
        />

        <div className="relative mt-14">
          <div
            aria-hidden
            className="absolute top-6 right-[16.7%] left-[16.7%] hidden h-px bg-gradient-to-r from-brand/10 via-brand-2/50 to-brand/10 md:block"
          />
          <div
            aria-hidden
            className="absolute top-6 bottom-6 left-6 w-px bg-gradient-to-b from-brand/10 via-brand-2/50 to-brand/10 md:hidden"
          />
          <ol className="relative grid gap-10 md:grid-cols-3 md:gap-8">
            {steps.map((step, i) => (
              <li key={step.title}>
                <Reveal
                  delay={i * 150}
                  className="flex gap-5 md:flex-col md:items-center md:text-center"
                >
                  <div className="relative flex size-12 shrink-0 items-center justify-center rounded-full border bg-background text-brand">
                    <step.icon className="size-5" aria-hidden />
                    <span
                      aria-hidden
                      className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white"
                    >
                      {i + 1}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-base font-semibold">{step.title}</h3>
                    <p className="mt-1.5 text-sm text-pretty text-muted-foreground">{step.body}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}
