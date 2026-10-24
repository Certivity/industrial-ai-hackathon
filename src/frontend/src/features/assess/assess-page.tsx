import { useState } from 'react'
import { CircleCheck, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { assessDocuments, type AssessResult } from '@/lib/assess'
import { FileDropzone } from './file-dropzone'
import { FileList } from './file-list'

type State =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'done'; result: AssessResult }

const sameFile = (a: File, b: File) =>
  a.name === b.name && a.size === b.size && a.lastModified === b.lastModified

export function AssessPage() {
  const [files, setFiles] = useState<File[]>([])
  const [state, setState] = useState<State>({ status: 'idle' })

  const addFiles = (added: File[]) =>
    setFiles((current) => [...current, ...added.filter((f) => !current.some((c) => sameFile(c, f)))])

  async function submit() {
    setState({ status: 'submitting' })
    try {
      const result = await assessDocuments(files)
      setState({ status: 'done', result })
      toast.success('Documentation submitted')
    } catch (e) {
      setState({ status: 'idle' })
      toast.error('Submission failed', { description: e instanceof Error ? e.message : String(e) })
    }
  }

  function reset() {
    setFiles([])
    setState({ status: 'idle' })
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Assess product</h1>
        <p className="text-sm text-muted-foreground">
          Upload the technical documentation of a component to check it against the regulations.
        </p>
      </header>

      {state.status === 'done' ? (
        <>
          {state.result.unmet.length === 0 && (
            <Alert>
              <CircleCheck />
              <AlertTitle>All regulations have been fulfilled</AlertTitle>
              <AlertDescription>
                No unmet requirements were found in the {files.length} submitted{' '}
                {files.length === 1 ? 'document' : 'documents'}.
              </AlertDescription>
            </Alert>
          )}
          <div>
            <Button onClick={reset}>Assess another product</Button>
          </div>
        </>
      ) : (
        <>
          <FileDropzone disabled={state.status === 'submitting'} onFiles={addFiles} />
          {files.length > 0 && (
            <FileList
              files={files}
              disabled={state.status === 'submitting'}
              onRemove={(i) => setFiles((current) => current.filter((_, j) => j !== i))}
            />
          )}
          <div>
            <Button disabled={files.length === 0 || state.status === 'submitting'} onClick={submit}>
              {state.status === 'submitting' && <Loader2 className="animate-spin" />}
              {state.status === 'submitting' ? 'Submitting…' : 'Submit documentation'}
            </Button>
          </div>
        </>
      )}
    </main>
  )
}
