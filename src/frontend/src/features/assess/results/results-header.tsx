import { useEffect, useRef } from 'react'
import { Download, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  fileCount: number
  canExport: boolean
  onReset: () => void
  onExport: () => void
}

export function ResultsHeader({ fileCount, canExport, onReset, onExport }: Props) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  // The submit button that had focus is gone, so move focus to the new page title
  useEffect(() => titleRef.current?.focus(), [])

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 ref={titleRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight outline-none">
          Assessment results
        </h1>
        <p className="text-sm text-muted-foreground">
          Based on {fileCount} {fileCount === 1 ? 'document' : 'documents'}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={onReset}>
          <RotateCcw /> Assess another product
        </Button>
        <Button variant="outline" disabled={!canExport} onClick={onExport}>
          <Download /> Export JSON
        </Button>
      </div>
    </div>
  )
}
