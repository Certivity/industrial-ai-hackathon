import { Check } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

interface Hotspot {
  id: string
  name: string
  /** Position on the photo, in percent of its width and height. */
  x: number
  y: number
  regulations: { code: string; title: string }[]
}

// Illustrative content only: example regulations for each part, not an assessment of this car.
const hotspots: Hotspot[] = [
  {
    id: 'windscreen',
    name: 'Windscreen',
    x: 43,
    y: 42,
    regulations: [
      { code: 'UN R43', title: 'Safety glazing materials' },
      { code: 'UN R125', title: 'Forward field of vision' },
    ],
  },
  {
    id: 'mirror',
    name: 'Side mirror',
    x: 27,
    y: 49,
    regulations: [{ code: 'UN R46', title: 'Devices for indirect vision' }],
  },
  {
    id: 'headlamp',
    name: 'Headlamp',
    x: 45,
    y: 55,
    regulations: [
      { code: 'UN R149', title: 'Road illumination devices' },
      { code: 'UN R48', title: 'Installation of lighting devices' },
      { code: 'UN R10', title: 'Electromagnetic compatibility' },
    ],
  },
  {
    id: 'grille',
    name: 'Front grille',
    x: 66,
    y: 55,
    regulations: [
      { code: 'UN R26', title: 'External projections' },
      { code: 'UN R127', title: 'Pedestrian safety' },
    ],
  },
  {
    id: 'wheel',
    name: 'Wheel and tyre',
    x: 37,
    y: 68,
    regulations: [
      { code: 'UN R124', title: 'Wheels for passenger cars' },
      { code: 'UN R30', title: 'Tyres for passenger cars' },
    ],
  },
]

/** Clickable dots laid over the banner photo; each opens a popover with example regulations. */
export function CarHotspots() {
  return (
    <ul className="absolute inset-0 m-0 list-none p-0">
      {hotspots.map((spot) => (
        <li key={spot.id} className="absolute" style={{ left: `${spot.x}%`, top: `${spot.y}%` }}>
          <Popover>
            <PopoverTrigger
              aria-label={`${spot.name}: show example regulations`}
              className="group relative -translate-x-1/2 -translate-y-1/2 rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span
                aria-hidden
                className="absolute inset-0 animate-ping rounded-full bg-white/70 [animation-duration:2.4s]"
              />
              <span className="relative block size-4 rounded-full border-2 border-white bg-brand shadow-md transition-transform group-hover:scale-125 group-data-popup-open:scale-125 sm:size-5" />
            </PopoverTrigger>
            <PopoverContent side="top" sideOffset={10} className="w-72">
              <p className="font-medium">{spot.name}</p>
              <p className="text-xs text-muted-foreground">Example regulations</p>
              <ul className="mt-2 flex flex-col gap-2">
                {spot.regulations.map((r) => (
                  <li key={r.code} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
                    <span>
                      <span className="font-medium">{r.code}</span>
                      <span className="text-muted-foreground"> · {r.title}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
                Illustrative example, not an assessment of this vehicle.
              </p>
            </PopoverContent>
          </Popover>
        </li>
      ))}
    </ul>
  )
}
