import { FileUp } from 'lucide-react'

export function AssessPage() {
  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Assess product</h1>
        <p className="text-sm text-muted-foreground">
          Upload technical documentation of a component and check it against the regulations.
        </p>
      </header>
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-24 text-muted-foreground">
        <FileUp className="size-8" />
        <p>Document upload is coming soon.</p>
      </div>
    </main>
  )
}
