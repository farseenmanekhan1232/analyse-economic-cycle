'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, CalendarDays, CircleAlert, RefreshCw } from 'lucide-react'
import { AppNav } from '@/components/app-nav'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  api,
  inr,
  pct,
  type DiffResponse,
  type HoldingsResponse,
  type KiteStatus,
  type PipelineStatus,
} from '@/lib/api'
import {
  ageCopy,
  bookIsFresh,
  clusterLabel,
  daysSince,
  decisionRank,
  displayFundName,
  exposureClusters,
  holdingWeight,
  isBroadMarketFund,
  isAnalysisStale,
  needsPlan,
  nextReviewDate,
} from '@/lib/decision'
import { cn, formatDate, formatDateTime } from '@/lib/utils'

const segmentClasses = [
  'bg-primary',
  'bg-primary/65',
  'bg-primary/40',
  'bg-muted-foreground/35',
  'bg-muted-foreground/20',
]

export default function TodayPage() {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<PipelineStatus | null>(null)
  const [runMessage, setRunMessage] = useState('')

  const holdingsQuery = useQuery({
    queryKey: ['holdings'],
    queryFn: () => api<HoldingsResponse>('/api/decide/holdings'),
  })
  const latestQuery = useQuery({
    queryKey: ['decide-latest'],
    queryFn: () => api<DiffResponse>('/api/decide/latest'),
  })
  const kiteQuery = useQuery({
    queryKey: ['kite-status'],
    queryFn: () => api<KiteStatus>('/api/kite/status'),
    refetchInterval: 30_000,
  })

  const startAnalysis = useMutation({
    mutationFn: () =>
      api<{ job_id: string }>('/api/run-pipeline', {
        method: 'POST',
      }),
    onSuccess: (result) => {
      setRunMessage('')
      setJobStatus({ done: false, step: 'Starting analysis', progress: 0, error: null })
      setJobId(result.job_id)
    },
    onError: (error: Error) => setRunMessage(error.message),
  })

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    const poll = async () => {
      try {
        const status = await api<PipelineStatus>(`/api/pipeline/status/${jobId}`)
        if (cancelled) return
        setJobStatus(status)

        if (status.error) {
          setRunMessage(status.error)
          setJobId(null)
          return
        }

        if (status.done) {
          setJobId(null)
          setRunMessage('Analysis updated.')
          await qc.invalidateQueries({ queryKey: ['decide-latest'] })
          await qc.invalidateQueries({ queryKey: ['holdings'] })
          return
        }

        timer = setTimeout(poll, 1500)
      } catch (error) {
        if (cancelled) return
        setRunMessage(error instanceof Error ? error.message : 'Lost connection to analysis')
        timer = setTimeout(poll, 3000)
      }
    }

    poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [jobId, qc])

  const holdings = useMemo(() => holdingsQuery.data?.holdings ?? [], [holdingsQuery.data?.holdings])
  const summary = holdingsQuery.data?.summary
  const run = latestQuery.data?.run || null
  const attentionRows = useMemo(
    () =>
      (latestQuery.data?.rows || [])
        .filter((row) => ['sell', 'review', 'extend'].includes(row.proposal.suggested))
        .sort(
          (a, b) =>
            decisionRank(a.proposal.suggested) - decisionRank(b.proposal.suggested),
        ),
    [latestQuery.data?.rows],
  )
  const plansMissing = useMemo(() => holdings.filter(needsPlan), [holdings])
  const clusters = useMemo(() => exposureClusters(holdings), [holdings])
  const nextReview = useMemo(() => nextReviewDate(holdings), [holdings])
  const analysisAge = daysSince(run?.ran_at)
  const stale = !run || isAnalysisStale(run.ran_at)
  const bookFresh = bookIsFresh(latestQuery.data?.sync_freshness)
  const primaryDecision = stale ? null : attentionRows[0] || null
  const primaryPlan = plansMissing[0] || null
  const primaryPlanIsBroad = primaryPlan ? isBroadMarketFund(primaryPlan) : false
  const suggestionRows = primaryPlan
    ? attentionRows.filter((row) => row.holding.id !== primaryPlan.id)
    : attentionRows
  const suggestionIds = new Set(attentionRows.map((row) => row.holding.id))
  const running = Boolean(jobId)
  const isLoading = holdingsQuery.isLoading || latestQuery.isLoading
  const error = holdingsQuery.error || latestQuery.error

  const chartClusters = clusters.slice(0, 4)
  const otherWeight = clusters.slice(4).reduce((sum, cluster) => sum + cluster.weight, 0)
  if (otherWeight > 0) {
    chartClusters.push({ label: 'Other', value: 0, weight: otherWeight, count: 0 })
  }

  const headline = !run
    ? 'Start with a fresh analysis.'
    : stale
      ? bookFresh
        ? 'Your book is current. Your market view is not.'
        : 'Your market view is out of date.'
      : primaryPlan
        ? primaryPlanIsBroad
          ? 'One review date needs attention.'
          : 'One plan needs attention.'
        : primaryDecision
          ? 'One model suggestion to review.'
          : 'Nothing to do today.'

  const subhead = !run
    ? 'Run an analysis to turn your portfolio into a clear decision.'
    : stale
      ? `The last analysis is ${ageCopy(analysisAge).toLowerCase()}. Pulse will not show buy or sell advice from stale data.`
      : primaryPlan
        ? suggestionRows.length
          ? `Set a review date for ${displayFundName(primaryPlan.instrument)}.${primaryPlanIsBroad ? ' It is a broad-market fund, so no sector score is required.' : ''} There are ${suggestionRows.length} optional model suggestions, but no forced trade.`
          : `Set a review date for ${displayFundName(primaryPlan.instrument)}.${primaryPlanIsBroad ? ' It is a broad-market fund, so no sector score is required.' : ''} No model decisions are waiting.`
        : primaryDecision
          ? 'This is a ranking or calendar suggestion, not a forced exit. Keep the plan unless you agree with it.'
          : `All holdings are within plan. Next review is ${formatDate(nextReview)}.`

  const staleAction = (() => {
    if (running) {
      return (
        <div className="flex min-w-40 flex-col gap-2" aria-live="polite">
          <p className="text-sm font-medium">{jobStatus?.step || 'Updating analysis'}</p>
          <div className="h-1 overflow-hidden rounded-full bg-border">
            <div
              className="h-full bg-primary transition-[width]"
              style={{ width: `${Math.round((jobStatus?.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )
    }

    if (kiteQuery.isLoading) {
      return (
        <Button size="lg" className="h-11 px-4" disabled>
          Checking connection
        </Button>
      )
    }

    if (!kiteQuery.data?.connected) {
      return (
        <a
          href={kiteQuery.data?.login_url || 'http://127.0.0.1:8000/login'}
          className={cn(buttonVariants({ size: 'lg' }), 'h-11 px-4')}
        >
          Connect Kite
          <ArrowRight data-icon="inline-end" />
        </a>
      )
    }

    return (
      <Button
        size="lg"
        className="h-11 px-4"
        onClick={() => startAnalysis.mutate()}
        disabled={startAnalysis.isPending}
      >
        <RefreshCw data-icon="inline-start" />
        {startAnalysis.isPending ? 'Starting…' : 'Update analysis'}
      </Button>
    )
  })()

  return (
    <div className="min-h-screen bg-background">
      <AppNav active="/" />
      <main
        id="main-content"
        className="mx-auto flex max-w-4xl flex-col gap-10 px-4 py-10 sm:px-6 sm:py-14"
      >
        {isLoading ? (
          <TodaySkeleton />
        ) : error ? (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Could not load Today</AlertTitle>
            <AlertDescription>{(error as Error).message}</AlertDescription>
          </Alert>
        ) : holdings.length === 0 ? (
          <section className="flex max-w-2xl flex-col items-start gap-5 py-8">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Today
              </p>
              <h1 className="text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
                Bring in your portfolio.
              </h1>
              <p className="text-base leading-7 text-muted-foreground">
                Sync stocks or import a mutual fund statement to start making decisions.
              </p>
            </div>
            <Link href="/sync" className={cn(buttonVariants({ size: 'lg' }), 'h-11 px-4')}>
              Open Data
              <ArrowRight data-icon="inline-end" />
            </Link>
          </section>
        ) : (
          <>
            <section className="max-w-3xl space-y-3">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Today
              </p>
              <h1 className="text-3xl font-semibold leading-[1.08] tracking-[-0.04em] sm:text-4xl">
                {headline}
              </h1>
              <p className="max-w-2xl text-base leading-7 text-muted-foreground">{subhead}</p>
            </section>

            {stale && (
              <Alert className="border-border bg-muted/45 px-5 py-5 sm:px-6 sm:py-6">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="space-y-1.5">
                    <AlertTitle className="text-base">
                      {run ? 'Refresh the market view' : 'Run the first analysis'}
                    </AlertTitle>
                    <AlertDescription>
                      {run?.ran_at
                        ? `Last run ${formatDateTime(run.ran_at)}. Updating takes about a minute.`
                        : 'Pulse needs a current market view before it can judge your holdings.'}
                    </AlertDescription>
                    {runMessage && (
                      <p className="text-xs text-destructive" role="status">
                        {runMessage}
                      </p>
                    )}
                  </div>
                  {staleAction}
                </div>
              </Alert>
            )}

            <section
              aria-labelledby="book-heading"
              className="grid gap-8 border-b pb-9 sm:grid-cols-[1.15fr_1fr] sm:items-end"
            >
              <div>
                <h2
                  id="book-heading"
                  className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground"
                >
                  Your book
                </h2>
                <p className="mt-2 text-4xl font-semibold tracking-[-0.045em] tabular-nums">
                  {inr(summary?.total_value || 0)}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  <span className={summary && summary.pnl < 0 ? 'text-destructive' : undefined}>
                    {summary ? `${inr(summary.pnl)} · ${pct(summary.pnl_pct)}` : '—'}
                  </span>
                  {' · '}
                  {holdings.length} {holdings.length === 1 ? 'fund' : 'funds'}
                </p>
              </div>

              <dl className="grid grid-cols-3 gap-4">
                <div>
                  <dt className="text-xs text-muted-foreground">Next review</dt>
                  <dd className="mt-1.5 text-sm font-medium">
                    {nextReview ? formatDate(nextReview).replace(/ \d{4}$/, '') : 'Not set'}
                  </dd>
                  <dd className="mt-0.5 text-xs text-muted-foreground">
                    {nextReview ? nextReview.slice(0, 4) : 'Add a plan'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Exposure</dt>
                  <dd className="mt-1.5 text-sm font-medium">
                    {clusters.length} {clusters.length === 1 ? 'cluster' : 'clusters'}
                  </dd>
                  <dd className="mt-0.5 text-xs text-muted-foreground">Grouped by risk</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Plans</dt>
                  <dd className="mt-1.5 text-sm font-medium">
                    {holdings.length - plansMissing.length} of {holdings.length}
                  </dd>
                  <dd className="mt-0.5 text-xs text-muted-foreground">
                    {plansMissing.length ? `${plansMissing.length} missing` : 'Complete'}
                  </dd>
                </div>
              </dl>
            </section>

            {!primaryPlan && primaryDecision && (
              <section
                aria-labelledby="decision-heading"
                className="flex flex-col gap-5 border-b pb-8 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="max-w-2xl space-y-2">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    Model suggestion
                  </p>
                  <h2
                    id="decision-heading"
                    className="text-xl font-semibold tracking-[-0.025em]"
                  >
                    {displayFundName(primaryDecision.holding.instrument)}
                  </h2>
                  <p className="text-sm font-medium">{primaryDecision.proposal.label}</p>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {primaryDecision.proposal.rationale}
                  </p>
                  {suggestionRows.length > 1 && (
                    <p className="text-xs text-muted-foreground">
                      {suggestionRows.length - 1} more{' '}
                      {suggestionRows.length === 2 ? 'suggestion' : 'suggestions'} for later.
                    </p>
                  )}
                </div>
                <Link
                  href={`/holding/${primaryDecision.holding.id}`}
                  className={cn(buttonVariants({ variant: 'outline' }), 'h-11 shrink-0 px-4')}
                >
                  Review suggestion
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </section>
            )}

            {primaryPlan && (
              <section
                aria-labelledby="plan-heading"
                className="flex flex-col gap-5 border-b pb-8 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="max-w-2xl space-y-2">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    {primaryPlanIsBroad ? 'Needs a review date' : 'Required'}
                  </p>
                  <h2 id="plan-heading" className="text-xl font-semibold tracking-[-0.025em]">
                    {displayFundName(primaryPlan.instrument)}
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {Math.round(holdingWeight(primaryPlan, holdings) * 100)}% of the book has no
                    review date.
                    {primaryPlanIsBroad
                      ? ' It is a broad-market fund, so it does not need a sector score.'
                      : ' It also has no sector role.'}
                    {plansMissing.length > 1 ? ` ${plansMissing.length} funds need the same.` : ''}
                  </p>
                </div>
                <Link
                  href={`/holdings#holding-${primaryPlan.id}`}
                  className={cn(buttonVariants({ variant: 'outline' }), 'h-11 shrink-0 px-4')}
                >
                  Set the plan
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </section>
            )}

            {primaryPlan && !!suggestionRows.length && (
              <section className="flex flex-col gap-5 border-b pb-8 sm:flex-row sm:items-center sm:justify-between">
                <div className="max-w-2xl space-y-2">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    Model suggestions
                  </p>
                  <h2 className="text-xl font-semibold tracking-[-0.025em]">
                    {suggestionRows.length} optional reviews
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">
                    These changed sector rank or review date. No forced trade is waiting.
                  </p>
                </div>
                <Link
                  href={`/holding/${suggestionRows[0].holding.id}`}
                  className={cn(buttonVariants({ variant: 'outline' }), 'h-11 shrink-0 px-4')}
                >
                  Review the first
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </section>
            )}

            <section aria-labelledby="exposure-heading">
              <div className="mb-4 flex items-baseline justify-between gap-4">
                <h2 id="exposure-heading" className="text-base font-semibold tracking-[-0.02em]">
                  Exposure
                </h2>
                <Link
                  href="/holdings"
                  className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  View portfolio
                </Link>
              </div>
              <div
                className="flex h-2.5 overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label={clusters
                  .map((cluster) => `${cluster.label} ${Math.round(cluster.weight * 100)}%`)
                  .join(', ')}
              >
                {chartClusters.map((cluster, index) => (
                  <span
                    key={cluster.label}
                    className={segmentClasses[index % segmentClasses.length]}
                    style={{ width: `${Math.max(cluster.weight * 100, 0.5)}%` }}
                  />
                ))}
              </div>
              <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
                {chartClusters.map((cluster, index) => (
                  <li key={cluster.label} className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={cn(
                        'size-1.5 rounded-full',
                        segmentClasses[index % segmentClasses.length],
                      )}
                    />
                    <span>
                      {cluster.label} {Math.round(cluster.weight * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section aria-labelledby="portfolio-heading">
              <div className="mb-2 flex items-baseline justify-between gap-4">
                <h2
                  id="portfolio-heading"
                  className="text-base font-semibold tracking-[-0.02em]"
                >
                  Portfolio
                </h2>
                <span className="text-xs text-muted-foreground">
                  {holdings.length} {holdings.length === 1 ? 'fund' : 'funds'}
                </span>
              </div>
              <ul className="flex flex-col">
                {holdings.map((holding) => (
                  <li
                    key={holding.id}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b py-3 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_72px_116px]"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {displayFundName(holding.instrument)}
                      </p>
                      <p className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                        {clusterLabel(holding)}
                        {suggestionIds.has(holding.id) && (
                          <Badge variant="outline">Review</Badge>
                        )}
                      </p>
                    </div>
                    <span className="text-right text-xs tabular-nums text-muted-foreground">
                      {Math.round(holdingWeight(holding, holdings) * 100)}%
                    </span>
                    <span className="hidden items-center justify-end gap-1.5 text-xs tabular-nums text-muted-foreground sm:flex">
                      <CalendarDays aria-hidden className="size-3.5" />
                      {formatDate(holding.hold_until)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <footer className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-5 text-xs text-muted-foreground">
              <span>
                Book synced{' '}
                {formatDateTime(
                  latestQuery.data?.sync_freshness?.last_mf_sync_at ||
                    summary?.sync.last_mf_sync_at,
                )}
              </span>
              <span aria-hidden>·</span>
              <Link href="/sync" className="underline-offset-4 hover:text-foreground hover:underline">
                Manage data
              </Link>
            </footer>
          </>
        )}
      </main>
    </div>
  )
}

function TodaySkeleton() {
  return (
    <div className="flex flex-col gap-10" aria-label="Loading today">
      <div className="space-y-3">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-10 w-full max-w-2xl" />
        <Skeleton className="h-5 w-full max-w-xl" />
      </div>
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid gap-8 sm:grid-cols-[1.15fr_1fr]">
        <div className="space-y-3">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-11 w-48" />
          <Skeleton className="h-4 w-36" />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      </div>
      <Skeleton className="h-2.5 w-full rounded-full" />
      <div className="space-y-3">
        <Skeleton className="h-5 w-32" />
        {[0, 1, 2, 3, 4].map((row) => (
          <Skeleton key={row} className="h-11 w-full" />
        ))}
      </div>
    </div>
  )
}
