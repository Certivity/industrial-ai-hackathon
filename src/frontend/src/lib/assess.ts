import type { Requirement } from '@/lib/cases'

export interface UnmetRequirement extends Requirement {
  /** Why the documents do not satisfy the requirement. */
  reasoning?: string
}

export interface AssessResult {
  unmet: UnmetRequirement[]
}

/**
 * Sends the product documentation to the backend and returns the unmet requirements.
 *
 * STUB: the endpoint does not exist yet. When it does, replace the body with
 *   POST /api/assess  (multipart/form-data, field "files", repeated)  ->  AssessResult
 * and keep the signature, so the page does not change.
 */
export async function assessDocuments(files: File[]): Promise<AssessResult> {
  void files
  await new Promise((resolve) => setTimeout(resolve, 1200))
  return { unmet: [] }
}
