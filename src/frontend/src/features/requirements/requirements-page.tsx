import { useMemo, useState } from 'react'
import { SearchX, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { listCases } from '@/lib/cases'
import { FilterSelect } from './filter-select'
import { applyFilters, emptyFilters, isFiltering, unique, type Filters } from './filters'
import { RequirementsTable } from './requirements-table'
import { useRequirements } from './use-requirements'

const cases = listCases()
const toOptions = (values: string[]) => values.map((v) => ({ value: v, label: v }))

export function RequirementsPage() {
  const [caseId, setCaseId] = useState(cases[0]?.id)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const data = useRequirements(caseId)

  const requirements = useMemo(() => (data.status === 'ready' ? data.requirements : []), [data])
  const regulations = useMemo(() => unique(requirements.map((r) => r.source.regulation)), [requirements])
  // Versions narrow to the chosen regulation
  const versions = useMemo(
    () =>
      unique(
        requirements
          .filter((r) => !filters.regulation || r.source.regulation === filters.regulation)
          .map((r) => r.source.version),
      ),
    [requirements, filters.regulation],
  )
  const visible = useMemo(() => applyFilters(requirements, filters), [requirements, filters])

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }))

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-6 px-6 pt-24 pb-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Regulatory requirements</h1>
        <p className="text-sm text-muted-foreground">
          Requirements that apply to a product, with the regulation, version, paragraph and page they come from.
        </p>
      </header>

      <Card>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <FilterSelect
              label="Product"
              value={caseId ?? ''}
              options={cases.map((c) => ({ value: c.id, label: c.name }))}
              onChange={(id) => {
                setCaseId(id)
                setFilters(emptyFilters)
              }}
            />
            <Input
              aria-label="Search requirement text"
              placeholder="Search requirement text or ID"
              className="sm:w-72"
              value={filters.query}
              onChange={(e) => set({ query: e.target.value })}
            />
            <FilterSelect
              label="Regulation"
              allLabel="All regulations"
              value={filters.regulation}
              options={toOptions(regulations)}
              onChange={(regulation) => set({ regulation, version: '' })}
            />
            <FilterSelect
              label="Version"
              allLabel="All versions"
              value={filters.version}
              options={toOptions(versions)}
              onChange={(version) => set({ version })}
            />
            <Input
              aria-label="Paragraph starts with"
              placeholder="Paragraph, e.g. 6.4"
              className="sm:w-44"
              value={filters.paragraph}
              onChange={(e) => set({ paragraph: e.target.value })}
            />
            {isFiltering(filters) && (
              <Button variant="ghost" onClick={() => setFilters(emptyFilters)}>
                <X /> Clear
              </Button>
            )}
          </div>
          {data.status === 'ready' && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              Showing {visible.length} of {requirements.length} requirements
            </p>
          )}
        </CardContent>
      </Card>

      {data.status === 'loading' && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}
      {data.status === 'error' && (
        <p role="alert" className="text-sm text-destructive">
          {data.message}
        </p>
      )}
      {data.status === 'ready' && visible.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-16 text-muted-foreground">
          <SearchX className="size-8" />
          <p>No requirements match these filters.</p>
        </div>
      )}
      {data.status === 'ready' && visible.length > 0 && <RequirementsTable requirements={visible} />}
    </main>
  )
}
