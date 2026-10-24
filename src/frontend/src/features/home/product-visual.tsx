import { AlertTriangle, FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

interface Finding {
  regulation: string
  paragraph: string
  title: string
}

// Decorative sample content: shows the shape of a result, not real output.
const findings: Finding[] = [
  {
    regulation: 'UN R150',
    paragraph: '3.3.1.1',
    title: 'Space for approval marking is not documented',
  },
  {
    regulation: 'UN R10',
    paragraph: '6.1.1.2',
    title: 'Emission and immunity test evidence is missing',
  },
  {
    regulation: 'UN R148',
    paragraph: '3.3.1.1.1',
    title: 'Legibility of markings is not described',
  },
  {
    regulation: 'UN R48',
    paragraph: '5.1',
    title: 'Fitting of the device is not described',
  },
]

export function ProductVisual() {
  return (
    <div aria-hidden className="relative mx-auto max-w-4xl">
      <div className="absolute -inset-x-6 -inset-y-6 -z-10 rounded-[2rem] bg-gradient-to-b from-brand/20 via-brand-2/10 to-transparent blur-2xl" />
      <div className="animate-float glass overflow-hidden rounded-2xl">
        <div className="flex items-center gap-3 border-b border-border/70 px-4 py-3">
          <div className="flex gap-1.5">
            <span className="size-2.5 rounded-full bg-destructive/60" />
            <span className="size-2.5 rounded-full bg-muted-foreground/40" />
            <span className="size-2.5 rounded-full bg-muted-foreground/25" />
          </div>
          <div className="flex min-w-0 items-center gap-1.5 rounded-md bg-muted/70 px-2.5 py-1 text-xs text-muted-foreground">
            <FileText className="size-3.5 shrink-0" />
            <span className="truncate">Sample assessment result</span>
          </div>
        </div>

        <div className="grid gap-5 p-4 sm:p-6 md:grid-cols-[1fr_14rem]">
          <ul className="flex flex-col gap-2.5">
            {findings.map((f) => (
              <li
                key={`${f.regulation}-${f.paragraph}`}
                className="flex items-center gap-3 rounded-xl border border-border/70 bg-background/70 px-3 py-2.5"
              >
                <Badge variant="outline" className="shrink-0">
                  {f.regulation}
                </Badge>
                <div className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-medium">{f.title}</p>
                  <p className="text-xs text-muted-foreground">Paragraph {f.paragraph}</p>
                </div>
                <Badge variant="destructive" className="hidden shrink-0 sm:inline-flex">
                  Unmet
                </Badge>
              </li>
            ))}
          </ul>

          <div className="hidden flex-col justify-between gap-4 rounded-xl border border-border/70 bg-background/70 p-4 text-left md:flex">
            <div className="flex items-center gap-2 text-sm font-medium">
              <AlertTriangle className="size-4 text-destructive" />
              Unmet by regulation
            </div>
            <div className="flex flex-col gap-3">
              <Bar label="R48" width="82%" className="bg-brand" />
              <Bar label="R150" width="58%" className="bg-brand-2" />
              <Bar label="R10" width="36%" className="bg-brand/60" />
              <Bar label="R148" width="22%" className="bg-brand-2/60" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Bar({ label, width, className }: { label: string; width: string; className: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="w-9 shrink-0">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-muted">
        <div className={`h-full rounded-full ${className}`} style={{ width }} />
      </div>
    </div>
  )
}
