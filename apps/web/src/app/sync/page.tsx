'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { AppNav } from '@/components/app-nav'
import { KiteConnectBar } from '@/components/analysis-report'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { cn, formatDateTime } from '@/lib/utils'

export default function SyncPage() {
  const qc = useQueryClient()
  const { data: summary } = useQuery({
    queryKey: ['summary'],
    queryFn: () =>
      api<{
        position_count: number
        sync: { last_stocks_sync_at: string | null; last_mf_sync_at: string | null }
      }>('/api/decide/summary'),
  })
  const [message, setMessage] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const syncStocks = useMutation({
    mutationFn: () =>
      api<{ updated: number; orders_logged: number }>('/api/decide/sync/stocks', { method: 'POST' }),
    onSuccess: (res) => {
      setMessage(`Stocks/ETFs updated: ${res.updated}. Orders logged today: ${res.orders_logged}.`)
      qc.invalidateQueries()
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const syncMf = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a Holdings_Statement XLSX')
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/decide/sync/mf', { method: 'POST', body: fd })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.detail || res.statusText)
      }
      return res.json() as Promise<{ updated: number }>
    },
    onSuccess: (res) => {
      setMessage(`Mutual funds updated: ${res.updated}. Hold-until / reason were preserved.`)
      qc.invalidateQueries()
    },
    onError: (e: Error) => setMessage(e.message),
  })

  return (
    <div className="min-h-screen bg-background">
      <AppNav active="/sync" />
      <main
        id="main-content"
        className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-10 sm:px-6 sm:py-14"
      >
        <section className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Data
            </p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
              Keep the book current
            </h1>
            <p className="max-w-xl text-sm leading-6 text-muted-foreground">
              Groww owns quantities. Pulse keeps the plan, the decisions, and the history.
            </p>
            <KiteConnectBar />
          </div>
          <Link
            href="/"
            className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'self-start sm:self-auto')}
          >
            <ArrowLeft data-icon="inline-start" />
            Back to Today
          </Link>
        </section>

        {message && (
          <Alert>
            <AlertTitle>Result</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Stocks &amp; ETFs</CardTitle>
              <CardDescription>
                Pull current holdings and today&apos;s orders from Groww.
                {summary?.sync?.last_stocks_sync_at
                  ? ` Last: ${formatDateTime(summary.sync.last_stocks_sync_at)}`
                  : ' Not synced yet.'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => syncStocks.mutate()} disabled={syncStocks.isPending}>
                {syncStocks.isPending ? 'Syncing…' : 'Sync stocks'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Mutual funds</CardTitle>
              <CardDescription>
                Import the Groww holdings statement as XLSX. The Trade API does not expose MFs.
                {summary?.sync?.last_mf_sync_at
                  ? ` Last: ${formatDateTime(summary.sync.last_mf_sync_at)}`
                  : ''}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Input type="file" accept=".xlsx,.xls" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              <Button onClick={() => syncMf.mutate()} disabled={syncMf.isPending || !file}>
                {syncMf.isPending ? 'Importing…' : 'Import MF XLSX'}
              </Button>
            </CardContent>
          </Card>
        </div>

        <p className="border-t pt-5 text-xs text-muted-foreground">
          Open book: {summary?.position_count ?? '—'} holdings. The order log is day-only, so sync
          stocks on the day you trade.
        </p>
      </main>
    </div>
  )
}
