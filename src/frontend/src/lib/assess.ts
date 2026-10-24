import { listCases, loadRequirements, type Requirement } from '@/lib/cases'

export interface UnmetRequirement extends Requirement {
  /** Why the documents do not satisfy the requirement. */
  reasoning?: string
}

export interface AssessResult {
  /** Number of requirements that were checked against the documents. */
  checked: number
  unmet: UnmetRequirement[]
}

/** Which canned answer the stub gives: some unmet requirements, or none. */
const MOCK_SCENARIO: 'unmet' | 'clean' = 'unmet'

const MOCK_REASONS = [
  'The submitted documents give no value for this characteristic, so compliance cannot be shown.',
  'The specification contradicts the required value; a test report is needed to demonstrate compliance.',
  'No marking or labelling information was found in the exploded view or the specification.',
  'The material listed for this part is not covered by the required test procedure.',
]

/**
 * Sends the product documentation to the backend and returns the unmet requirements.
 *
 * STUB: the endpoint does not exist yet. When it does, replace the body with
 *   POST /api/assess  (multipart/form-data, field "files", repeated)  ->  AssessResult
 * and keep the signature, so the page does not change. The mock picks every 7th
 * requirement of the first case in cases/ and invents a reason for it.
 */
export async function assessDocuments(files: File[]): Promise<AssessResult> {
  void files
  await new Promise((resolve) => setTimeout(resolve, 1200))
  const [first] = listCases()
  if (!first) return { checked: 0, unmet: [] }
  const requirements = await loadRequirements(first.id)
  if (MOCK_SCENARIO === 'clean') return { checked: requirements.length, unmet: [] }
  const unmet = requirements
    .filter((_, i) => i % 7 === 3)
    .map((r, i) => ({ ...r, reasoning: MOCK_REASONS[i % MOCK_REASONS.length] }))
  return { checked: requirements.length, unmet }
}
