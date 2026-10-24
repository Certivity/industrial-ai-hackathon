import { useMemo, useState } from 'react'
import { CircleCheck } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { AssessResult } from '@/lib/assess'
import { downloadJson } from './export-json'
import { RegulationChart } from './regulation-chart'
import { ResultsHeader } from './results-header'
import { countByRegulation } from './stats'
import { SummaryCards } from './summary-cards'
import { UnmetTable } from './unmet-table'

interface Props {
  result: AssessResult
  fileCount: number
  onReset: () => void
}

export function AssessResults({ result, fileCount, onReset }: Props) {
  // Shared by the chart (bars, chips) and the table's regulation select
  const [regulation, setRegulation] = useState('')
  const { unmet, checked } = result
  const byRegulation = useMemo(() => countByRegulation(unmet), [unmet])

  return (
    <div className="flex flex-col gap-6">
      <ResultsHeader
        fileCount={fileCount}
        canExport={unmet.length > 0}
        onReset={onReset}
        onExport={() => downloadJson(unmet, 'unmet-requirements.json')}
      />

      {unmet.length === 0 ? (
        <Alert className="animate-fade-up">
          <CircleCheck />
          <AlertTitle>All regulations have been fulfilled</AlertTitle>
          <AlertDescription>
            No unmet requirements were found in the {fileCount} submitted {fileCount === 1 ? 'document' : 'documents'}.
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <SummaryCards unmetCount={unmet.length} checked={checked} byRegulation={byRegulation} />
          <RegulationChart data={byRegulation} selected={regulation} onSelect={setRegulation} />
          <UnmetTable
            unmet={unmet}
            regulations={byRegulation.map((d) => d.regulation)}
            regulation={regulation}
            onRegulationChange={setRegulation}
          />
        </>
      )}
    </div>
  )
}
