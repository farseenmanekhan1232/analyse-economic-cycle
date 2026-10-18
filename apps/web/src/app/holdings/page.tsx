'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, CircleAlert } from 'lucide-react'
import { AppNav } from '@/components/app-nav'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  api,
  inr,
  pct,
  type Holding,
  type HoldingsResponse,
} from '@/lib/api'
import { clusterLabel, isBroadMarketFund, isSystemNote, needsPlan } from '@/lib/decision'
import { cn, formatDate } from '@/lib/utils'

export default function PortfolioPage() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['holdings'],
    queryFn: () => api<HoldingsResponse>('/api/decide/holdings'),
  })
  const [selected, setSelected] = useState<Holding | null>(null)
  const [holdUntil, setHoldUntil] = useState('')
  const [reason, setReason] = useState('')
  const [sector, setSector] = useState('')
  const openedHash = useRef<string | null>(null)

  const chooseHolding = (holding: Holding) => {
    setSelected(holding)
    setHoldUntil(holding.hold_until || '')
    setReason(isSystemNote(holding.reason) ? '' : holding.reason || '')
    setSector(holding.sector_id || holding.sector || '')
  }

  useEffect(() => {
    if (!data?.holdings?.length || typeof window === 'undefined') return
    const id = window.location.hash.replace(/^#holding-/, '')
    if (!id || openedHash.current === id) return
    const holding = data.holdings.find((row) => row.id === id)
    if (!holding) return
    openedHash.current = id
    chooseHolding(holding)
  }, [data?.holdings])

  useEffect(() => {
    if (!selected) return
    requestAnimationFrame(() => {
      document.getElementById('plan-editor')?.scrollIntoView({ block: 'nearest' })
    })
  }, [selected])

  const save = useMutation({
    mutationFn: () =>
      api(`/api/decide/holdings/${selected!.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          hold_until: holdUntil || null,
          reason,
          sector: sector || null,
        }),
      }),
    onSuccess: () => {
      setSelected(null)
      qc.invalidateQueries({ queryKey: ['holdings'] })
      qc.invalidateQueries({ queryKey: ['decide-latest'] })
    },
  })

  const markSold = useMutation({
    mutationFn: (id: string) =>
      api(`/api/decide/holdings/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'closed' }),
      }),
    onSuccess: () => {
      setSelected(null)
      qc.invalidateQueries({ queryKey: ['holdings'] })
      qc.invalidateQueries({ queryKey: ['decide-latest'] })
    },
  })

  const holdings = data?.holdings || []
  const summary = data?.summary

  return (
    <div className="min-h-screen bg-background">
      <AppNav active="/holdings" />
      <main
        id="main-content"
        className="mx-auto flex max-w-4xl flex-col gap-9 px-4 py-10 sm:px-6 sm:py-14"
      >
        <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Portfolio
            </p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">Your book</h1>
            {summary && (
              <p className="text-sm text-muted-foreground">
                {inr(summary.total_value)} ·{' '}
                <span className={summary.pnl < 0 ? 'text-destructive' : undefined}>
                  {inr(summary.pnl)} / {pct(summary.pnl_pct)}
                </span>{' '}
                · {summary.position_count} open
              </p>
            )}
          </div>
          <Link
            href="/"
            className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'self-start sm:self-auto')}
          >
            <ArrowLeft data-icon="inline-start" />
            Back to Today
          </Link>
        </section>

        {isLoading && (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <Skeleton key={row} className="h-16 w-full" />
            ))}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Could not load the portfolio</AlertTitle>
            <AlertDescription>{(error as Error).message}</AlertDescription>
          </Alert>
        )}

        {!isLoading && !error && holdings.length === 0 && (
          <Alert>
            <AlertTitle>Your book is empty</AlertTitle>
            <AlertDescription>
              Add stocks or mutual funds in <Link href="/sync">Data</Link>.
            </AlertDescription>
          </Alert>
        )}

        {!!holdings.length && (
          <section aria-labelledby="holdings-heading">
            <div className="flex items-baseline justify-between gap-4 border-b pb-3">
              <h2 id="holdings-heading" className="text-base font-semibold tracking-[-0.02em]">
                Holdings
              </h2>
              <span className="text-xs text-muted-foreground">
                {holdings.length} {holdings.length === 1 ? 'position' : 'positions'}
              </span>
            </div>
            <ul className="flex flex-col">
              {holdings.map((holding) => (
                <li
                  id={`holding-${holding.id}`}
                  key={holding.id}
                  className="scroll-mt-24 border-b last:border-b-0"
                >
                  <div className="flex flex-col gap-3 py-4 sm:grid sm:grid-cols-[minmax(0,1fr)_120px_100px_130px_auto] sm:items-center sm:gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium leading-5">{holding.instrument}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>{clusterLabel(holding)}</span>
                        <span aria-hidden>·</span>
                        <span>{holding.asset_class.toUpperCase()}</span>
                        {needsPlan(holding) && <Badge variant="outline">Needs plan</Badge>}
                        {holding.missing_from_sync && (
                          <Badge variant="destructive">Not in latest sync</Badge>
                        )}
                        {holding.needs_id_review && <Badge variant="outline">Check identity</Badge>}
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-3 sm:contents">
                      <div className="sm:text-right">
                        <p className="text-[11px] text-muted-foreground sm:hidden">Value</p>
                        <p className="mt-0.5 text-sm tabular-nums">{inr(holding.market_value)}</p>
                      </div>
                      <div className="sm:text-right">
                        <p className="text-[11px] text-muted-foreground sm:hidden">P&amp;L</p>
                        <p
                          className={cn(
                            'mt-0.5 text-sm tabular-nums',
                            holding.pnl_pct < 0 && 'text-destructive',
                          )}
                        >
                          {pct(holding.pnl_pct)}
                        </p>
                      </div>
                      <div className="sm:text-right">
                        <p className="text-[11px] text-muted-foreground sm:hidden">Review</p>
                        <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                          {formatDate(holding.hold_until)}
                        </p>
                      </div>
                    </div>

                    <div className="flex justify-end sm:block">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-9 px-3"
                        onClick={() => chooseHolding(holding)}
                      >
                        Edit
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {selected && (
          <Card id="plan-editor" className="scroll-mt-24">
            <CardHeader>
              <CardTitle className="text-base">{selected.instrument}</CardTitle>
              <CardDescription>
                A plan is a role and a review date. It is not a prediction.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              {isBroadMarketFund(selected) && (
                <p className="text-sm leading-6 text-muted-foreground">
                  This is a broad-market fund. The sector field is optional. Pulse will use your
                  review date and reason, not a sector score.
                </p>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-2 text-sm font-medium">
                  Sector or role
                  <Input
                    placeholder="CORE, FLEXI CAP, PHARMA, or leave blank"
                    value={sector}
                    onChange={(event) => setSector(event.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-2 text-sm font-medium">
                  Review by
                  <Input
                    type="date"
                    value={holdUntil}
                    onChange={(event) => setHoldUntil(event.target.value)}
                  />
                </label>
              </div>
              <label className="flex flex-col gap-2 text-sm font-medium">
                Why you own it
                <Textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={3}
                  placeholder="One sentence you can test later."
                />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => save.mutate()} disabled={save.isPending}>
                  {save.isPending ? 'Saving…' : 'Save plan'}
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => markSold.mutate(selected.id)}
                  disabled={markSold.isPending}
                >
                  Mark sold
                </Button>
                <Button variant="ghost" onClick={() => setSelected(null)}>
                  Cancel
                </Button>
              </div>
              {(save.error || markSold.error) && (
                <p className="text-sm text-destructive" role="alert">
                  {((save.error || markSold.error) as Error).message}
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  )
}
