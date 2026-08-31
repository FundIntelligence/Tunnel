'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { DataTable, Column } from '@/components/DataTable'
import { PageHeader } from '@/components/PageHeader'
import { EnvBadge } from '@/components/EnvBadge'
import { ENV_HEADER } from '@/lib/env-header'
import { toEAT, refreshedLabel } from './utils'

interface Deal {
  id: string
  name: string
  company_name: string
  currency: string
  created_at: string
  [key: string]: unknown
}

export default function DealsPage() {
  const [rows, setRows] = useState<Deal[]>([])
  const [loading, setLoading] = useState(true)
  const [lastFetched, setLastFetched] = useState<string | null>(null)
  const [refreshedText, setRefreshedText] = useState('')
  const [env, setEnv] = useState<string | null>(null)
  const router = useRouter()

  const load = useCallback(async () => {
    const res = await fetch('/api/data/deals')
    const data = await res.json()
    const list = Array.isArray(data) ? data : (data?.deals ?? [])
    setRows(list)
    setEnv(res.headers.get(ENV_HEADER))
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
    { key: 'name', label: 'Name' },
    { key: 'company_name', label: 'Company' },
    {
      key: 'currency',
      label: 'Currency',
      mono: true,
      render: (val) => <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{val as string ?? '—'}</span>,
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
        <PageHeader
          title="Deal Pipeline"
          subtitle={loading ? 'Loading…' : `${rows.length} deals (last 100)`}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
          {env === 'prod' && <EnvBadge env="prod" />}
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
      <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={rows}
          onRowClick={(row) => router.push(`/deals/${row.id}`)}
        />
      </div>
    </div>
  )
}
