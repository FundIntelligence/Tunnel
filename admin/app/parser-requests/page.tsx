'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { DataTable, Column } from '@/components/DataTable'
import { StatusBadge } from '@/components/StatusBadge'
import { PageHeader } from '@/components/PageHeader'
import { toEAT, timeSince, refreshedLabel, downloadCSV } from './utils'
import { useEnv } from '@/app/providers'

type Status = 'pending' | 'in_progress' | 'done' | 'new' | 'processing' | 'processed'
// Auto (parser_requests) and manual (pds_parser_requests) rows use different
// status vocabularies. Cycle each within its own set.
const STATUS_CYCLE: Status[] = ['pending', 'in_progress', 'done']
const MANUAL_STATUS_CYCLE: Status[] = ['new', 'processing', 'processed']

// Raw shape from `parser_requests` ("auto" / Musa table)
interface AutoRequest {
  id: string
  partner: string
  market: string
  bank_name: string
  document_url: string | null
  session_id?: string | null
  deal_id?: string | null
  error_message: string | null
  status: Status
  requested_at: string
  updated_at?: string
  [key: string]: unknown
}

// Raw shape from `pds_parser_requests` ("manual" table)
interface ManualRequest {
  id: string
  deal_id?: string | null
  document_id?: string | null
  original_filename: string | null
  bank_name: string | null
  country: string | null
  account_type?: string | null
  notes?: string | null
  error_type?: string | null
  error_message: string | null
  created_at: string
  [key: string]: unknown
}

// Normalized row shape used for rendering, filtering, and CSV export
interface Row {
  id: string
  source: 'Auto · Musa' | 'Manual'
  partner: string
  market: string
  bank_display: string
  error_message: string | null
  status: Status | null
  date: string
  isAuto: boolean
  storage_path: string | null
  [key: string]: unknown
}

type ApiResponse =
  | AutoRequest[]
  | { auto: AutoRequest[]; manual: ManualRequest[]; env?: string; fetched_at?: string }

function nextStatus(current: Status, isAuto: boolean): Status {
  const cycle = isAuto ? STATUS_CYCLE : MANUAL_STATUS_CYCLE
  const idx = cycle.indexOf(current)
  return cycle[(idx + 1) % cycle.length]
}

function normalize(data: ApiResponse): Row[] {
  let auto: AutoRequest[] = []
  let manual: ManualRequest[] = []

  if (Array.isArray(data)) {
    auto = data
  } else if (data && typeof data === 'object') {
    auto = Array.isArray(data.auto) ? data.auto : []
    manual = Array.isArray(data.manual) ? data.manual : []
  }

  const autoRows: Row[] = auto.map((r) => ({
    id: r.id,
    source: 'Auto · Musa',
    partner: r.partner ?? '—',
    market: r.market ?? '—',
    bank_display: r.bank_name ?? '—',
    error_message: r.error_message ?? null,
    status: r.status,
    date: r.requested_at,
    isAuto: true,
    storage_path: null,
  }))

  const manualRows: Row[] = manual.map((r) => ({
    id: r.id,
    source: 'Manual',
    partner: 'Manual',
    market: r.country ?? '—',
    bank_display: r.bank_name ?? r.original_filename ?? '—',
    error_message: r.error_message ?? null,
    status: ((r.status as Status) ?? 'new'),
    date: r.created_at,
    isAuto: false,
    storage_path: (r.storage_path as string | null) ?? null,
  }))

  return [...autoRows, ...manualRows].sort((a, b) => {
    const ta = a.date ? new Date(a.date).getTime() : 0
    const tb = b.date ? new Date(b.date).getTime() : 0
    return tb - ta
  })
}

const PARTNER_FILTERS = ['All', 'Musa', 'GBFund', 'Manual'] as const
const STATUS_FILTERS = ['All', 'Pending', 'In Progress', 'Done'] as const

function chipStyle(active: boolean): React.CSSProperties {
  return {
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: 11,
    letterSpacing: '0.04em',
    padding: '4px 10px',
    borderRadius: 4,
    border: '1px solid var(--teal)',
    background: active ? 'var(--teal)' : 'transparent',
    color: active ? '#fff' : 'var(--teal)',
    cursor: 'pointer',
  }
}

function severityColor(severity: 'ok' | 'warn' | 'alert'): string {
  if (severity === 'alert') return 'var(--red)'
  if (severity === 'warn') return 'var(--amber)'
  return 'var(--green)'
}

export default function ParserRequestsPage() {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<string | null>(null)
  const [partnerFilter, setPartnerFilter] = useState<typeof PARTNER_FILTERS[number]>('All')
  const [statusFilter, setStatusFilter] = useState<typeof STATUS_FILTERS[number]>('All')
  const [lastFetched, setLastFetched] = useState<string>(() => new Date().toISOString())
  const [, setTick] = useState(0)
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tickIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Which Supabase project to read/write — driven by the sidebar PROD/STAGING
  // toggle (EnvContext), NOT the URL. The API route reads ?env= (parseEnv), so
  // every data call must forward it or it silently defaults to prod.
  const { env } = useEnv()

  const load = useCallback(async () => {
    const res = await fetch(`/api/data/parser-requests?env=${env}`)
    const data: ApiResponse = await res.json()
    setRows(normalize(data))
    setLoading(false)
    setLastFetched(new Date().toISOString())
  }, [env])

  useEffect(() => {
    load()
    refreshIntervalRef.current = setInterval(load, 60000)
    tickIntervalRef.current = setInterval(() => setTick((t) => t + 1), 1000)
    return () => {
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current)
      if (tickIntervalRef.current) clearInterval(tickIntervalRef.current)
    }
  }, [load])

  async function cycleStatus(row: Row) {
    if (!row.status) return
    const next = nextStatus(row.status, row.isAuto)
    const table = row.isAuto ? 'parser_requests' : 'pds_parser_requests'
    setUpdating(row.id)
    await fetch(`/api/data/parser-requests?env=${env}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: row.id, status: next, table }),
    })
    setRows((prev) => prev.map((r) => r.id === row.id ? { ...r, status: next } : r))
    setUpdating(null)
  }

  // Resolve a private-bucket sample file to a short-lived signed URL and open it.
  // Uses the toggle's env (EnvContext) so staging rows resolve against the
  // staging bucket — the same env the data load used to fetch the row.
  async function downloadFile(row: Row) {
    if (!row.storage_path) return
    const qs = new URLSearchParams({ path: row.storage_path, env })
    const res = await fetch(`/api/data/parser-requests/download?${qs.toString()}`)
    if (!res.ok) return
    const { url } = await res.json()
    if (url) window.open(url, '_blank', 'noopener')
  }

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (partnerFilter !== 'All') {
        if (partnerFilter === 'Manual') {
          if (r.isAuto) return false
        } else {
          if (!r.isAuto || r.partner?.toLowerCase() !== partnerFilter.toLowerCase()) return false
        }
      }
      if (statusFilter !== 'All') {
        if (!r.isAuto || !r.status) return false
        const want = statusFilter === 'In Progress' ? 'in_progress' : statusFilter.toLowerCase()
        if (r.status !== want) return false
      }
      return true
    })
  }, [rows, partnerFilter, statusFilter])

  const summary = useMemo(() => {
    const autoRows = rows.filter((r) => r.isAuto)
    const pending = autoRows.filter((r) => r.status === 'pending').length
    const inProgress = autoRows.filter((r) => r.status === 'in_progress').length
    const done = autoRows.filter((r) => r.status === 'done').length
    return `${pending} pending · ${inProgress} in progress · ${done} done · across both environments`
  }, [rows])

  function handleDownloadCSV() {
    const csvRows = filteredRows.map((r) => ({
      id: r.id,
      source: r.source,
      partner: r.partner,
      market: r.market,
      bank_display: r.bank_display,
      error_message: r.error_message ?? '',
      status: r.status ?? '',
      date: r.date,
      time_pending_label: timeSince(r.date).label,
    }))
    downloadCSV(csvRows, `parser-requests-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  const columns: Column<Row>[] = [
    {
      key: 'source',
      label: 'Source',
      render: (_, row) => (
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          padding: '2px 8px',
          borderRadius: 4,
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 11,
          fontWeight: 500,
          letterSpacing: '0.04em',
          border: '1px solid',
          background: row.isAuto ? 'var(--teal-d)' : 'var(--bg2)',
          color: row.isAuto ? 'var(--teal)' : 'var(--t1)',
          borderColor: row.isAuto ? 'rgba(13,148,136,0.20)' : 'var(--border)',
        }}>
          {row.source}
        </span>
      ),
    },
    { key: 'partner', label: 'Partner/Bank', render: (_, row) => row.isAuto ? row.partner : row.bank_display },
    { key: 'market', label: 'Market/Country' },
    {
      key: 'status',
      label: 'Status',
      render: (_, row) => {
        if (!row.status) {
          return <span style={{ color: 'var(--t3)' }}>—</span>
        }
        return (
          <button
            onClick={(e) => { e.stopPropagation(); cycleStatus(row) }}
            disabled={updating === row.id}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, opacity: updating === row.id ? 0.5 : 1 }}
            title="Click to cycle status"
          >
            <StatusBadge status={row.status} />
          </button>
        )
      },
    },
    {
      key: 'file',
      label: 'File',
      render: (_, row) => {
        if (!row.storage_path) {
          return <span style={{ color: 'var(--t3)' }}>—</span>
        }
        return (
          <button
            onClick={(e) => { e.stopPropagation(); downloadFile(row) }}
            style={{
              background: 'none', border: '1px solid var(--teal)', cursor: 'pointer',
              color: 'var(--teal)', borderRadius: 4, padding: '2px 8px',
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
            }}
            title="Download the submitted sample file"
          >
            ↓ file
          </button>
        )
      },
    },
    {
      key: 'time_pending',
      label: 'Time Pending',
      render: (_, row) => {
        const { label, severity } = timeSince(row.date)
        return <span style={{ color: severityColor(severity), fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{label}</span>
      },
    },
    {
      key: 'date',
      label: 'Requested At',
      render: (val) => toEAT(val as string),
    },
    {
      key: 'error_message',
      label: 'Error',
      truncate: true,
      render: (val) => val
        ? <span style={{ color: 'var(--red)', fontSize: 12 }}>{val as string}</span>
        : <span style={{ color: 'var(--t3)' }}>—</span>,
    },
  ]

  return (
    <div style={{ padding: '40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <PageHeader
          title="Parser Requests"
          subtitle={loading ? 'Loading…' : summary}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 }}>
          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'var(--t2)' }}>
            {refreshedLabel(lastFetched)}
          </span>
          <button
            onClick={() => load()}
            title="Refresh"
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 12,
              padding: '6px 10px',
              borderRadius: 4,
              border: '1px solid var(--border)',
              background: 'var(--paper)',
              color: 'var(--t1)',
              cursor: 'pointer',
            }}
          >
            ↻
          </button>
          <button
            onClick={handleDownloadCSV}
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 12,
              padding: '6px 10px',
              borderRadius: 4,
              border: '1px solid var(--teal)',
              background: 'transparent',
              color: 'var(--teal)',
              cursor: 'pointer',
            }}
          >
            Download CSV
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {PARTNER_FILTERS.map((f) => (
            <button key={f} onClick={() => setPartnerFilter(f)} style={chipStyle(partnerFilter === f)}>
              {f}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {STATUS_FILTERS.map((f) => (
            <button key={f} onClick={() => setStatusFilter(f)} style={chipStyle(statusFilter === f)}>
              {f}
            </button>
          ))}
        </div>
      </div>

      <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        <DataTable columns={columns} rows={filteredRows} />
      </div>
    </div>
  )
}
