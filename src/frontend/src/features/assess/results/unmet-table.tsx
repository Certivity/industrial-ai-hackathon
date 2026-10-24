import { useMemo, useState } from 'react'
import { SearchX } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { UnmetRequirement } from '@/lib/assess'
import { FilterSelect } from '@/features/requirements/filter-select'
import { UnmetRow } from './unmet-row'

interface Props {
  unmet: UnmetRequirement[]
  regulations: string[]
  /** Selected regulation, '' = all. */
  regulation: string
  onRegulationChange: (regulation: string) => void
}

function matches(r: UnmetRequirement, query: string) {
  return [r.id, r.text, r.reasoning ?? '', r.source.paragraph].some((v) => v.toLowerCase().includes(query))
}

export function UnmetTable({ unmet, regulations, regulation, onRegulationChange }: Props) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return unmet.filter((r) => (!regulation || r.source.regulation === regulation) && (!q || matches(r, q)))
  }, [unmet, regulation, query])

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })

  return (
    <Card className="animate-fade-up" style={{ animationDelay: '350ms' }}>
      <CardHeader>
        <CardTitle>Unmet requirements</CardTitle>
        <CardDescription>Expand a row to read why the documents do not satisfy the requirement.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <Input
            aria-label="Search unmet requirements"
            placeholder="Search ID, text, reasoning or paragraph"
            className="sm:w-72"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <FilterSelect
            label="Regulation"
            allLabel="All regulations"
            value={regulation}
            options={regulations.map((r) => ({ value: r, label: r }))}
            onChange={onRegulationChange}
          />
          <p className="text-sm text-muted-foreground sm:ml-auto" aria-live="polite">
            Showing {visible.length} of {unmet.length}
          </p>
        </div>

        {visible.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <SearchX className="size-8" />
            <p>No unmet requirements match these filters.</p>
          </div>
        ) : (
          // Fixed layout: column widths stay constant whatever the row contents are
          <Table className="min-w-4xl table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <span className="sr-only">Reasoning</span>
                </TableHead>
                <TableHead className="w-24">ID</TableHead>
                <TableHead className="w-48">Regulation</TableHead>
                <TableHead className="w-44">Paragraph</TableHead>
                <TableHead className="w-16">Page</TableHead>
                <TableHead>Requirement</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((requirement, i) => (
                <UnmetRow
                  key={requirement.id}
                  requirement={requirement}
                  index={i}
                  expanded={expanded.has(requirement.id)}
                  onToggle={() => toggle(requirement.id)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
