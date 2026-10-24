import { FileText, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

const formatSize = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`

interface Props {
  files: File[]
  disabled?: boolean
  onRemove: (index: number) => void
}

export function FileList({ files, disabled, onRemove }: Props) {
  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {files.map((file, i) => (
        <li key={`${file.name}-${file.size}-${file.lastModified}`} className="flex items-center gap-3 px-4 py-2">
          <FileText className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
          <span className="text-xs text-muted-foreground tabular-nums">{formatSize(file.size)}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            aria-label={`Remove ${file.name}`}
            onClick={() => onRemove(i)}
          >
            <X />
          </Button>
        </li>
      ))}
    </ul>
  )
}
