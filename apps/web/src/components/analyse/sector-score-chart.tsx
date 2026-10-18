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
import type { SectorRow } from '@/lib/api'

export function SectorScoreChart({ sectors }: { sectors: SectorRow[] }) {
  const data = [...sectors]
    .sort((a, b) => b.score - a.score)
    .map((s) => ({
      name: s.sector.replace(/_/g, ' '),
      score: Math.round(s.score),
      recommended: s.recommended,
      rating: s.rating,
    }))

  if (!data.length) return null

  const height = Math.max(200, data.length * 28 + 24)

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 11 }} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.[0]) return null
              const d = payload[0].payload as (typeof data)[0]
              return (
                <div className="rounded-md border bg-background px-3 py-2 text-xs shadow-sm">
                  <div className="font-medium">
                    {d.name} · {d.score}
                  </div>
                  <div className="text-muted-foreground">
                    {d.rating || '—'}
                    {d.recommended ? ' · recommended' : ''}
                  </div>
                </div>
              )
            }}
          />
          <Bar dataKey="score" radius={[0, 4, 4, 0]} maxBarSize={16}>
            {data.map((d) => (
              <Cell
                key={d.name}
                fill={d.recommended ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground) / 0.35)'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
