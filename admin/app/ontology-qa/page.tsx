'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { DataTable, Column } from '@/components/DataTable'
import { PageHeader } from '@/components/PageHeader'
import { EnvBadge } from '@/components/EnvBadge'
import { toEAT, refreshedLabel } from './utils'

interface Deal {
  id: string
  currency: string
  created_at: string
  accrual_period_start: string | null
  accrual_period_end: string | null
  [key: string]: unknown
}

export default function OntologyQaPage() {
  const [rows, setRows] = useState<Deal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastFetched, setLastFetched] = useState<string | null>(null)
  const [refreshedText, setRefreshedText] = useState('')
  const router = useRouter()

  const load = useCallback(async () => {
    const res = await fetch('/api/data/ontology-qa')
    const data = await res.json()
    if (data.error) {
      setError(data.error)
    } else {
      setError(null)
      setRows(data.deals ?? [])
    }
    setLoading(false)
    setLastFetched(new Date().toISOString())
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 60000)
    return () => clearInterval(interval)
  }, [load])

  useEffect(() => {
    if (!lastFetched) return
    setRefreshedText(refreshedLabel(lastFetched))
    const tick = setInterval(() => setRefreshedText(refreshedLabel(lastFetched)), 1000)
    return () => clearInterval(tick)
  }, [lastFetched])

  const columns: Column<Deal>[] = [
    { key: 'id', label: 'Deal ID', mono: true, truncate: true },
    {
      key: 'currency',
      label: 'Currency',
      mono: true,
      render: (val) => <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{val as string ?? '—'}</span>,
    },
    {
      key: 'accrual_period_start',
      label: 'Period Start',
      render: (val) => (val ? (val as string) : '—'),
    },
    {
      key: 'accrual_period_end',
      label: 'Period End',
      render: (val) => (val ? (val as string) : '—'),
    },
    {
      key: 'created_at',
      label: 'Created At',
      render: (val) => toEAT(val as string),
    },
  ]

  return (
    <div style={{ padding: '40px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <PageHeader
              title="Ontology QA"
              subtitle={loading ? 'Loading…' : `${rows.length} deals (last 100) — anonymized, staging only`}
            />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
          <EnvBadge env="staging" />
          {refreshedText && (
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'var(--t1)' }}>
              {refreshedText}
            </span>
          )}
          <button
            onClick={load}
            aria-label="Refresh"
            style={{
              border: '1px solid var(--border)',
              background: 'var(--paper)',
              borderRadius: 6,
              width: 28,
              height: 28,
              cursor: 'pointer',
              fontSize: 14,
              lineHeight: 1,
            }}
          >
            ↻
          </button>
        </div>
      </div>
      {error && (
        <div style={{ marginBottom: 16, padding: '10px 16px', borderRadius: 6, background: 'var(--red-d)', color: 'var(--red)', fontSize: 13 }}>
          {error}
        </div>
      )}
      <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={rows}
          onRowClick={(row) => router.push(`/ontology-qa/${row.id}`)}
        />
      </div>
    </div>
  )
}
