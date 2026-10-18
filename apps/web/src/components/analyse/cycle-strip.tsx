'use client'

import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { formatDateTime } from '@/lib/utils'
import type { AnalysisRun, PipelineStatus } from '@/lib/api'

export function CycleStrip({
  run,
  syncLine,
  running,
  jobStatus,
  onRun,
  onRefresh,
  runPending,
}: {
  run: AnalysisRun | null | undefined
  syncLine?: ReactNode
  running: boolean
  jobStatus: PipelineStatus | null
  onRun: () => void
  onRefresh: () => void
  runPending: boolean
}) {
  const progressPct = Math.round((run?.progress || 0) * 100)

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Analyse</p>
          <h1 className="text-2xl font-semibold tracking-tight">
            {run ? (
              <>
                {(run.phase || 'Cycle').replace(/_/g, ' ')}
                {run.sub_phase ? (
                  <span className="text-muted-foreground">
                    {' '}
                    / {run.sub_phase.replace(/_/g, ' ')}
                  </span>
                ) : null}
              </>
            ) : (
              'What changed vs what you hold?'
            )}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {run?.market_story ||
              'Run analysis to score sectors, then decide Keep / update date / Sell from levels.'}
          </p>
          {run?.methodology_note ? (
            <p className="mt-1 max-w-2xl text-xs text-muted-foreground/90">
              {run.methodology_note}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {run?.risk_label && <Badge variant="secondary">{run.risk_label}</Badge>}
            {run?.ran_at && (
              <span className="text-xs text-muted-foreground">
                Last run {formatDateTime(run.ran_at)}
              </span>
            )}
          </div>
          {syncLine}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onRun} disabled={runPending || running}>
            {running ? 'Running…' : 'Run analysis'}
          </Button>
          <Button variant="secondary" onClick={onRefresh} disabled={running}>
            Refresh
          </Button>
        </div>
      </div>

      {run != null && run.progress != null && run.progress > 0 && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Phase progress</span>
            <span className="tabular-nums">~{progressPct}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary/80 transition-all"
              style={{ width: `${Math.min(100, progressPct)}%` }}
            />
          </div>
        </div>
      )}

      {(running || jobStatus) && (
        <div className="space-y-2 rounded-lg border px-3 py-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{jobStatus?.step || 'Starting…'}</span>
            <span className="font-mono tabular-nums text-xs">
              {Math.round((jobStatus?.progress || 0) * 100)}%
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full transition-all ${
                jobStatus?.error ? 'bg-destructive' : 'bg-primary'
              }`}
              style={{
                width: `${Math.min(100, Math.round((jobStatus?.progress || 0) * 100))}%`,
              }}
            />
          </div>
        </div>
      )}
    </section>
  )
}
