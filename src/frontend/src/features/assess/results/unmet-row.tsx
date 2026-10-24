import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TableCell, TableRow } from '@/components/ui/table'
import type { UnmetRequirement } from '@/lib/assess'
import { cn } from '@/lib/utils'

const COLUMNS = 6

interface Props {
  requirement: UnmetRequirement
  expanded: boolean
  onToggle: () => void
  index: number
}

export function UnmetRow({ requirement, expanded, onToggle, index }: Props) {
  const { id, text, reasoning, source } = requirement
  const panelId = `reasoning-${id}`
  return (
    <>
      <TableRow
        className="animate-fade-up"
        // Stagger only the first rows so long lists do not trail in slowly
        style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}
      >
        <TableCell>
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={panelId}
            aria-label={`${expanded ? 'Hide' : 'Show'} reasoning for ${id}`}
            onClick={onToggle}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <ChevronRight className={cn('size-4 transition-transform duration-200', expanded && 'rotate-90')} />
          </button>
        </TableCell>
        <TableCell className="font-mono text-xs text-muted-foreground">{id}</TableCell>
        <TableCell>
          <Badge variant="secondary">{source.regulation}</Badge>
          <span className="ml-2 text-xs text-muted-foreground">v{source.version}</span>
        </TableCell>
        <TableCell className="font-mono text-xs whitespace-normal">{source.paragraph}</TableCell>
        <TableCell className="tabular-nums">{source.page}</TableCell>
        <TableCell className="whitespace-normal">{text}</TableCell>
      </TableRow>
      {expanded && (
        <TableRow id={panelId} className="hover:bg-transparent">
          <TableCell colSpan={COLUMNS} className="whitespace-normal">
            <div className="animate-in rounded-lg bg-muted/60 p-3 duration-200 fade-in-0 slide-in-from-top-1">
              <p className="text-xs font-medium text-muted-foreground">Reasoning</p>
              <p className="mt-1 text-sm">{reasoning ?? 'No reasoning was provided for this requirement.'}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                Source: {source.regulation} v{source.version}, paragraph {source.paragraph}, page {source.page}
              </p>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
