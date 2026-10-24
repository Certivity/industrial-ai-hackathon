import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Requirement } from '@/lib/cases'

export function RequirementsTable({ requirements }: { requirements: Requirement[] }) {
  return (
    // Fixed layout: column widths stay constant whatever the row contents are
    <Table className="min-w-4xl table-fixed">
      <TableHeader>
        <TableRow>
          <TableHead className="w-24">ID</TableHead>
          <TableHead className="w-48">Regulation</TableHead>
          <TableHead className="w-44">Paragraph</TableHead>
          <TableHead className="w-16">Page</TableHead>
          <TableHead>Requirement</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {requirements.map(({ id, text, source }) => (
          <TableRow key={id}>
            <TableCell className="font-mono text-xs text-muted-foreground">{id}</TableCell>
            <TableCell>
              <Badge variant="secondary">{source.regulation}</Badge>
              <span className="ml-2 text-xs text-muted-foreground">v{source.version}</span>
            </TableCell>
            <TableCell className="font-mono text-xs whitespace-normal">{source.paragraph}</TableCell>
            <TableCell className="tabular-nums">{source.page}</TableCell>
            <TableCell className="whitespace-normal">{text}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
