import { Bar, BarChart, LabelList, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import type { RegulationCount } from './stats'
import { prefersReducedMotion } from '@/lib/motion'

const chartConfig = { count: { label: 'Unmet requirements' } } satisfies ChartConfig

const ROW_HEIGHT = 44

interface Props {
  data: RegulationCount[]
  /** Selected regulation, '' = none. */
  selected: string
  onSelect: (regulation: string) => void
}

export function RegulationChart({ data, selected, onSelect }: Props) {
  const toggle = (regulation: string) => onSelect(regulation === selected ? '' : regulation)
  const chartData = data.map((d) => ({
    ...d,
    fill: d.color,
    // Dim the other bars while one regulation is selected
    fillOpacity: !selected || selected === d.regulation ? 1 : 0.3,
  }))
  const summary = data.map((d) => `${d.regulation}: ${d.count}`).join(', ')

  return (
    <Card className="animate-fade-up" style={{ animationDelay: '280ms' }}>
      <CardHeader>
        <CardTitle>Unmet requirements by regulation</CardTitle>
        <CardDescription>Select a bar or a regulation to filter the table below.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ChartContainer
          config={chartConfig}
          role="img"
          aria-label={`Unmet requirements by regulation. ${summary}`}
          className="aspect-auto w-full"
          style={{ height: data.length * ROW_HEIGHT + 8 }}
        >
          <BarChart
            accessibilityLayer={false}
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 32, bottom: 0, left: 0 }}
            barCategoryGap={10}
          >
            <XAxis type="number" hide domain={[0, 'dataMax']} />
            <YAxis
              type="category"
              dataKey="regulation"
              tickLine={false}
              axisLine={false}
              width={72}
              tick={{ fontSize: 12 }}
            />
            <ChartTooltip cursor={{ fillOpacity: 0.4 }} content={<ChartTooltipContent />} />
            <Bar
              dataKey="count"
              name="Unmet requirements"
              radius={6}
              isAnimationActive={!prefersReducedMotion()}
              className="cursor-pointer"
              onClick={(_, index) => {
                const item = data[index]
                if (item) toggle(item.regulation)
              }}
            >
              <LabelList dataKey="count" position="right" className="fill-foreground text-xs font-medium tabular-nums" />
            </Bar>
          </BarChart>
        </ChartContainer>

        <ul className="flex flex-wrap gap-2" aria-label="Filter by regulation">
          {data.map(({ regulation, count, color }) => {
            const active = selected === regulation
            return (
              <li key={regulation}>
                <Button
                  variant={active ? 'secondary' : 'outline'}
                  size="sm"
                  aria-pressed={active}
                  onClick={() => toggle(regulation)}
                >
                  <span aria-hidden="true" className="size-2 rounded-full" style={{ backgroundColor: color }} />
                  {regulation}
                  <span className="text-muted-foreground tabular-nums">{count}</span>
                </Button>
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
