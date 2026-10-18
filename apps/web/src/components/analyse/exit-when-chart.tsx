'use client'

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { actionBarColor, type ExitHorizon } from '@/lib/exit-horizon'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function ExitWhenChart({ horizons }: { horizons: ExitHorizon[] }) {
  if (!horizons.length) return null

  const data = horizons.map((h) => ({
    ...h,
    // Minimum bar width for "Now" so it's visible
    displayDays: Math.max(h.days, h.days === 0 ? 0.4 : h.days),
  }))

  const height = Math.max(160, data.length * 36 + 40)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">When to act (estimate)</CardTitle>
        <CardDescription>
          All open holdings — sooner bars need attention first. Estimates from stop/target and your
          review date — not a guaranteed sell day.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div style={{ width: '100%', height }}>
          <ResponsiveContainer>
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 4, bottom: 4 }}
            >
              <XAxis
                type="number"
                dataKey="displayDays"
                tick={{ fontSize: 11 }}
                unit="d"
                allowDecimals={false}
              />
              <YAxis
                type="category"
                dataKey="shortName"
                width={120}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                cursor={{ fill: 'hsl(var(--muted))' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.[0]) return null
                  const h = payload[0].payload as ExitHorizon & { displayDays: number }
                  const actionLabel =
                    h.action === 'exit'
                      ? 'Exit'
                      : h.action === 'tighten'
                        ? 'Tighten'
                        : h.action === 'review'
                          ? 'Review'
                          : 'Hold'
                  return (
                    <div className="rounded-md border bg-background px-3 py-2 text-xs shadow-sm">
                      <div className="font-medium">{h.name}</div>
                      <div className="mt-0.5 text-muted-foreground">
                        {actionLabel} · {h.label}
                        {h.days > 0 ? ` · ${h.days}d` : ''}
                        {h.sector ? ` · ${h.sector}` : ''}
                      </div>
                    </div>
                  )
                }}
              />
              <Bar dataKey="displayDays" radius={[0, 4, 4, 0]} maxBarSize={18}>
                {data.map((d) => (
                  <Cell key={d.holdingId} fill={actionBarColor(d.action)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          <li>
            <span className="mr-1 inline-block size-2 rounded-full bg-red-600" /> Exit now
          </li>
          <li>
            <span className="mr-1 inline-block size-2 rounded-full bg-amber-600" /> Tighten
          </li>
          <li>
            <span className="mr-1 inline-block size-2 rounded-full bg-slate-500" /> Review
          </li>
          <li>
            <span className="mr-1 inline-block size-2 rounded-full bg-emerald-700" /> Hold / review by
            date
          </li>
        </ul>
      </CardContent>
    </Card>
  )
}
