import type { UnmetRequirement } from '@/lib/assess'

export interface RegulationCount {
  regulation: string
  count: number
  /** Brand chart colour, stable for a regulation within one result. */
  color: string
}

/** Unmet requirements per regulation, most affected first (ties by name). */
export function countByRegulation(unmet: UnmetRequirement[]): RegulationCount[] {
  const counts = new Map<string, number>()
  for (const { source } of unmet) {
    counts.set(source.regulation, (counts.get(source.regulation) ?? 0) + 1)
  }
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([regulation, count], i) => ({ regulation, count, color: `var(--chart-${(i % 5) + 1})` }))
}

/** Percentage of checked requirements that are unmet, guarded against 0 checked. */
export const shareUnmet = (unmetCount: number, checked: number) =>
  checked > 0 ? (unmetCount / checked) * 100 : 0
