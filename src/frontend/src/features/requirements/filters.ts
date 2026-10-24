import type { Requirement } from '@/lib/cases'

export interface Filters {
  query: string
  regulation: string // '' = all
  version: string // '' = all
  paragraph: string // prefix, e.g. "6.4"
}

export const emptyFilters: Filters = { query: '', regulation: '', version: '', paragraph: '' }

export const isFiltering = (f: Filters) => Object.values(f).some((v) => v !== '')

export function applyFilters(requirements: Requirement[], f: Filters): Requirement[] {
  const query = f.query.trim().toLowerCase()
  const paragraph = f.paragraph.trim().toLowerCase()
  return requirements.filter(
    ({ id, text, source }) =>
      (!f.regulation || source.regulation === f.regulation) &&
      (!f.version || source.version === f.version) &&
      (!paragraph || source.paragraph.toLowerCase().startsWith(paragraph)) &&
      (!query || text.toLowerCase().includes(query) || id.toLowerCase().includes(query)),
  )
}

export const unique = (values: string[]) => [...new Set(values)].sort()
