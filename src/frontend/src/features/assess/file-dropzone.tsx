import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  disabled?: boolean
  onFiles: (files: File[]) => void
}

export function FileDropzone({ disabled, onFiles }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (!disabled) onFiles(Array.from(e.dataTransfer.files))
      }}
      className={cn(
        'flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-12 text-center transition-colors',
        dragging ? 'border-primary bg-muted' : 'bg-card',
        disabled && 'opacity-50',
      )}
    >
      <Upload className="size-8 text-muted-foreground" />
      <div>
        <p className="font-medium">Drag and drop documents here</p>
        <p className="text-sm text-muted-foreground">Specs, exploded views, drawings, datasheets</p>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="text-sm font-medium underline underline-offset-4 hover:text-primary focus-visible:outline-2 focus-visible:outline-ring disabled:pointer-events-none"
      >
        or browse files
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        disabled={disabled}
        aria-label="Choose documents to upload"
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []))
          e.target.value = '' // allow choosing the same file again
        }}
      />
    </div>
  )
}
