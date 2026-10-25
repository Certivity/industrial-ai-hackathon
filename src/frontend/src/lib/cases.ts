export interface Citation {
  regulation: string
  version: string
  page: number
  paragraph: string
}

export interface Requirement {
  id: string
  text: string
  source: Citation
}

export interface CaseSummary {
  id: string
  name: string
}

interface ExpectedFile {
  requirements: Requirement[]
}

// cases/ sits at the repo root; every case folder holds an expected.json and,
// optionally, a spec.md whose first heading ("# spec: Rear Lamp") names the product.
const expectedLoaders = import.meta.glob<ExpectedFile>(
  '../../../../cases/*/expected.json',
  { import: 'default' },
)
const specs = import.meta.glob<string>('../../../../cases/*/spec.md', {
  query: '?raw',
  import: 'default',
  eager: true,
})

const caseIdOf = (path: string) => path.split('/').at(-2) ?? path

function titleCase(slug: string) {
  const words = slug.replace(/[-_]+/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function caseName(id: string) {
  const spec = Object.entries(specs).find(([path]) => caseIdOf(path) === id)?.[1]
  const heading = spec?.match(/^#\s*(?:spec:\s*)?(.+)$/im)?.[1].trim()
  return heading ?? titleCase(id)
}

export function listCases(): CaseSummary[] {
  return Object.keys(expectedLoaders)
    .map(caseIdOf)
    .sort()
    .map((id) => ({ id, name: caseName(id) }))
}

export async function loadRequirements(caseId: string): Promise<Requirement[]> {
  const entry = Object.entries(expectedLoaders).find(
    ([path]) => caseIdOf(path) === caseId,
  )
  if (!entry) throw new Error(`Unknown case: ${caseId}`)
  const data = await entry[1]()
  if (!Array.isArray(data?.requirements)) {
    throw new Error(`cases/${caseId}/expected.json has no "requirements" list`)
  }
  return data.requirements
}
