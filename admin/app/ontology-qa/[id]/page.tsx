'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { DataTable, Column } from '@/components/DataTable'
import { PageHeader } from '@/components/PageHeader'
import { EnvBadge } from '@/components/EnvBadge'
import { formatCents, downloadCSV } from '../utils'

interface Deal {
  id: string
  currency: string
  created_at: string
  accrual_period_start: string | null
  accrual_period_end: string | null
}

interface Transaction {
  id: string
  txn_date: string
  account_id: string
  signed_amount_cents: number | null
  abs_amount_cents: number | null
  is_transfer: boolean
  role: string | null
  analyst_resolution: string | null
  [key: string]: unknown
}

export default function OntologyQaDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [deal, setDeal] = useState<Deal | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await fetch(`/api/data/ontology-qa/${id}`)
    const data = await res.json()
    if (data.error) {
      setError(data.error)
    } else {
      setError(null)
      setDeal(data.deal)
      setTransactions(data.transactions ?? [])
    }
    setLoading(false)
  }, [id])

  useEffect(() => { load() }, [load])

  const needsReviewCount = useMemo(
    () => transactions.filter((t) => t.role === 'needs_review').length,
    [transactions]
  )

  function handleExport() {
    const csvRows = transactions.map((t) => ({
      txn_id: t.id,
      txn_date: t.txn_date,
      account_id: t.account_id,
      amount: formatCents(t.signed_amount_cents),
      is_transfer: t.is_transfer,
      role: t.role ?? '',
      analyst_resolution: t.analyst_resolution ?? '',
    }))
    downloadCSV(csvRows, `ontology-qa-${id}-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  const columns: Column<Transaction>[] = [
    { key: 'txn_date', label: 'Date', mono: true },
    { key: 'account_id', label: 'Account', mono: true, truncate: true },
    {
      key: 'signed_amount_cents',
      label: 'Amount',
      mono: true,
      render: (val) => formatCents(val as number | null),
    },
    {
      key: 'role',
      label: 'Role',
      render: (val) => (
        <span style={{ color: val === 'needs_review' ? 'var(--amber)' : 'var(--t0)' }}>
          {(val as string) ?? '—'}
        </span>
      ),
    },
    {
      key: 'analyst_resolution',
      label: 'Analyst Resolution',
      render: (val) => (
        <span style={{ color: val ? 'var(--teal)' : 'var(--t2)' }}>
          {(val as string) ?? '—'}
        </span>
      ),
    },
  ]

  if (loading) return <div style={{ padding: '40px', color: 'var(--t2)' }}>Loading…</div>
  if (error) return <div style={{ padding: '40px', color: 'var(--red)' }}>{error}</div>
  if (!deal) return <div style={{ padding: '40px', color: 'var(--red)' }}>Deal not found.</div>

  return (
    <div style={{ padding: '40px' }}>
      <button
        onClick={() => router.push('/ontology-qa')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--teal)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, marginBottom: 24, padding: 0 }}
      >
        ← Back to deals
      </button>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <PageHeader title="Ontology QA" subtitle={`${transactions.length} transactions — anonymized, staging only`} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
          <EnvBadge env="staging" />
          <button
            onClick={handleExport}
            disabled={transactions.length === 0}
            style={{
              border: '1px solid var(--border)',
              background: 'var(--paper)',
              borderRadius: 6,
              padding: '6px 14px',
              cursor: transactions.length === 0 ? 'not-allowed' : 'pointer',
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 12,
              color: 'var(--t0)',
            }}
          >
            Export CSV
          </button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16, marginBottom: 40 }}>
        {[
          { label: 'Deal ID', value: deal.id, mono: true },
          { label: 'Currency', value: deal.currency },
          { label: 'Period', value: deal.accrual_period_start && deal.accrual_period_end ? `${deal.accrual_period_start} – ${deal.accrual_period_end}` : '—' },
          { label: 'Needs Review', value: String(needsReviewCount) },
        ].map((item) => (
          <div key={item.label} style={{ background: 'var(--paper)', border: '1px solid var(--border)', borderRadius: 8, padding: '16px 20px' }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, letterSpacing: '0.08em', color: 'var(--t2)', marginBottom: 6 }}>{item.label.toUpperCase()}</div>
            <div style={{ fontFamily: item.mono ? "'IBM Plex Mono', monospace" : "'IBM Plex Sans', sans-serif", fontSize: item.mono ? 11 : 14, color: 'var(--t0)' }}>{item.value ?? '—'}</div>
          </div>
        ))}
      </div>
      <section>
        <h2 style={{ fontFamily: "'IBM Plex Serif', serif", fontWeight: 400, fontSize: 18, color: 'var(--navy)', marginBottom: 16 }}>
          Transactions ({transactions.length})
        </h2>
        <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
          <DataTable columns={columns} rows={transactions} />
        </div>
      </section>
    </div>
  )
}
