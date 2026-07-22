'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQueries } from '@tanstack/react-query'
import { createBrowserClient } from '@/lib/supabase'
import { getDeal, listDocuments, type AnalysisRun } from '@/lib/v1-api'
import { useDealsListQuery, dealDetailKey, dealDocumentsKey } from '@/lib/queries/deals'
import { ThemeToggle } from '@/components/ThemeToggle'

interface PipelineStatus {
  label: string
  dot: string
}

const STATUS_UPLOADING: PipelineStatus = { label: 'Uploading documents', dot: 'var(--t1)' }
const STATUS_READY: PipelineStatus = { label: 'Ready to analyse', dot: 'var(--t1)' }

function computeStatus(documentStatuses: string[], hasAnalysisRun: boolean): PipelineStatus {
  if (documentStatuses.length === 0) return STATUS_UPLOADING
  if (documentStatuses.includes('failed')) return { label: 'Failed — retry', dot: 'var(--red)' }
  if (hasAnalysisRun) return { label: 'Analysis complete', dot: 'var(--green)' }
  if (documentStatuses.includes('processing')) return { label: 'In progress', dot: 'var(--amber)' }
  return STATUS_READY
}

export default function DashboardPage() {
  const router = useRouter()
  const [user, setUser] = useState<any>(null)
  const [userId, setUserId] = useState<string | undefined>(undefined)

  useEffect(() => {
    const supabase = createBrowserClient()
    if (!supabase) { router.replace('/login'); return }
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      setUser(session.user)
      setUserId(session.user.id)
    })
  }, [router])

  // Shares the ['deals', userId] cache with /v1/deal — re-opening the dashboard
  // after viewing a deal reads from cache instead of re-fetching within staleTime.
  const dealsQuery = useDealsListQuery(userId)
  const deals = dealsQuery.data?.deals ?? []

  // Per-deal status, also cache-shared with /v1/deal (['deal', id] / ['documents', id]) —
  // opening a deal you just saw on this dashboard won't re-fetch its detail/documents.
  const dealDetailQueries = useQueries({
    queries: deals.map((d) => ({
      queryKey: dealDetailKey(d.id),
      queryFn: () => getDeal(d.id),
      enabled: !!d.id,
    })),
  })
  const dealDocumentsQueries = useQueries({
    queries: deals.map((d) => ({
      queryKey: dealDocumentsKey(d.id),
      queryFn: () => listDocuments(d.id),
      enabled: !!d.id,
    })),
  })

  const statuses: Record<string, PipelineStatus> = {}
  const latestRunByDeal: Record<string, AnalysisRun | undefined> = {}
  let statusesLoaded = 0
  deals.forEach((d, i) => {
    const detail = dealDetailQueries[i]?.data
    const docs = dealDocumentsQueries[i]?.data
    if (!detail || !docs) return
    statusesLoaded += 1
    statuses[d.id] = computeStatus(
      docs.documents.map((doc) => doc.status),
      detail.analysis_runs.length > 0
    )
    latestRunByDeal[d.id] = detail.analysis_runs.length > 0
      ? detail.analysis_runs.reduce((a, b) => ((b.created_at as string || '') > (a.created_at as string || '') ? b : a))
      : undefined
  })

  const loading = dealsQuery.isLoading
  const email = user?.email ?? ''
  const initials = email ? email.slice(0, 2).toUpperCase() : 'AN'
  const activeDeals = deals.length

  // All derived from data already fetched above — no additional per-deal calls.
  const now = new Date()
  const newThisMonth = deals.filter((d) => {
    if (!d.created_at) return false
    const c = new Date(d.created_at as string)
    return c.getUTCFullYear() === now.getUTCFullYear() && c.getUTCMonth() === now.getUTCMonth()
  }).length

  const dealsWithStatus = deals.filter((d) => statuses[d.id])
  const pendingCount = dealsWithStatus.filter((d) => statuses[d.id].label !== 'Analysis complete').length

  const runsWithConfidence = deals
    .map((d) => latestRunByDeal[d.id])
    .filter((r): r is AnalysisRun => !!r)
  const avgAccuracyBp = runsWithConfidence.length > 0
    ? Math.round(runsWithConfidence.reduce((s, r) => s + (r.final_confidence_bp || 0), 0) / runsWithConfidence.length)
    : null
  const avgOverridePenaltyBp = runsWithConfidence.length > 0
    ? Math.round(runsWithConfidence.reduce((s, r) => s + (Number(r.override_penalty_bp) || 0), 0) / runsWithConfidence.length)
    : null

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <div style={{ width: 28, height: 28, borderRadius: '50%', borderTop: '2px solid var(--accent)', borderRight: '2px solid transparent', animation: 'spin 0.8s linear infinite' }} />
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', fontFamily: "'IBM Plex Sans', sans-serif", color: 'var(--t0)' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {/* Sidebar */}
      <aside style={{ width: 200, background: 'var(--s1)', borderRight: '1px solid var(--s3)', display: 'flex', flexDirection: 'column', padding: '20px 0', position: 'fixed', top: 0, left: 0, bottom: 0, zIndex: 50 }}>
        <div style={{ padding: '0 16px 16px', borderBottom: '1px solid var(--s3)' }}>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 700, letterSpacing: '0.08em' }}>
            <span style={{ color: 'var(--accent)' }}>P/</span> <span style={{ color: '#fff' }}>PARITY</span><span style={{ fontSize: 9, verticalAlign: 'super', color: 'var(--t1)' }}>v2.0</span>
          </div>
          <div style={{ fontSize: 9, color: 'var(--t2)', marginTop: 4, letterSpacing: '0.12em' }}>DETERMINISTIC</div>
        </div>
        {email && (
          <div style={{ margin: '10px 16px', background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 4, padding: '4px 8px', fontSize: 10, color: 'var(--t1)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontWeight: 700, color: 'var(--t1)' }}>{initials}</span>
            <span>PARITY DEMO</span>
          </div>
        )}
        <nav style={{ flex: 1, padding: '8px 0' }}>
          <div style={{ padding: '6px 16px', fontSize: 9, color: 'var(--t2)', letterSpacing: '0.12em', fontWeight: 600 }}>OPERATIONS</div>
          <button onClick={() => router.push('/deals')} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: '9px 16px', background: 'rgba(20,184,166,0.1)', borderLeft: '2px solid var(--accent)', border: 'none', color: 'var(--accent)', fontSize: 13, cursor: 'pointer', textAlign: 'left', fontFamily: "'IBM Plex Sans', sans-serif" }}>
            Dashboard <span style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>SYS</span>
          </button>
          <button onClick={() => router.push('/deals')} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: '9px 16px', background: 'transparent', borderLeft: '2px solid transparent', border: 'none', color: 'var(--t1)', fontSize: 13, cursor: 'pointer', textAlign: 'left', fontFamily: "'IBM Plex Sans', sans-serif" }}>
            Deals <span style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>{String(activeDeals).padStart(2, '0')}</span>
          </button>
          <div style={{ padding: '12px 16px 6px', fontSize: 9, color: 'var(--t2)', letterSpacing: '0.12em', fontWeight: 600, marginTop: 4 }}>INTELLIGENCE</div>
          <div style={{ padding: '9px 16px', color: 'var(--t2)', fontSize: 13 }}>Parity Review</div>
          <div style={{ padding: '9px 16px', color: 'var(--t2)', fontSize: 13 }}>Benchmarks</div>
          <div style={{ padding: '12px 16px 6px', fontSize: 9, color: 'var(--t2)', letterSpacing: '0.12em', fontWeight: 600, marginTop: 4 }}>SWITCH MODE</div>
          <div style={{ padding: '9px 16px', color: 'var(--t2)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>&lt;&gt;</span> Credit officer view
          </div>
        </nav>
        <div style={{ padding: '12px 16px', borderTop: '1px solid var(--s3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{email}</div>
            <ThemeToggle />
          </div>
          <button
            onClick={async () => { const sb = createBrowserClient(); if (sb) await sb.auth.signOut(); router.push('/login'); }}
            style={{ width: '100%', padding: '6px 0', background: 'transparent', border: '1px solid var(--s3)', borderRadius: 4, color: 'var(--t2)', fontSize: 12, cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
          >Sign out</button>
        </div>
      </aside>

      {/* Main */}
      <div style={{ marginLeft: 200, flex: 1 }}>
        {/* Top bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 40px', height: 48, borderBottom: '1px solid var(--s3)', background: 'var(--s1)' }}>
          <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.08em' }}>
            <span style={{ color: 'var(--accent)' }}>PARITY</span>
            <span>·</span>
            <span style={{ color: 'var(--t0)' }}>DASHBOARD</span>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button
              onClick={() => router.push('/deals/new')}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 5, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
            >+ New deal</button>
            <div style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{initials} · PARITY DEMO</div>
          </div>
        </div>

        <div style={{ padding: '28px 40px' }}>
          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', background: 'var(--s3)', border: '1px solid var(--s3)', borderRadius: 8, overflow: 'hidden', marginBottom: 28, gap: 1 }}>
            {[
              { label: 'ACTIVE DEALS', value: String(activeDeals).padStart(2, '0'), sub: newThisMonth > 0 ? `+${newThisMonth} this month` : 'No new deals this month', color: 'var(--t0)' },
              {
                label: 'PENDING REVIEW',
                value: statusesLoaded > 0 ? String(pendingCount).padStart(2, '0') : '—',
                sub: statusesLoaded > 0 ? `of ${activeDeals} total` : 'Loading…',
                color: 'var(--amber)',
              },
              {
                label: 'AVG ACCURACY',
                value: avgAccuracyBp !== null ? `${(avgAccuracyBp / 100).toFixed(1)}%` : '—',
                sub: avgAccuracyBp !== null ? `${avgAccuracyBp} bps · ${runsWithConfidence.length} deal${runsWithConfidence.length !== 1 ? 's' : ''} analysed` : 'No completed analyses yet',
                color: 'var(--green)',
              },
              {
                label: 'OVERRIDE RATE',
                value: avgOverridePenaltyBp !== null ? `${(avgOverridePenaltyBp / 100).toFixed(1)}%` : '—',
                sub: avgOverridePenaltyBp !== null ? 'avg. confidence penalty' : 'No completed analyses yet',
                color: 'var(--t0)',
              },
              // Entity discoveries and needs-review counts aren't in the data this
              // page already fetches (getDeal/listDocuments) — showing them would
              // mean N more per-deal calls (see the N+1 already flagged on this
              // page) or a new aggregate endpoint. Left honest rather than faked.
              { label: 'ENTITY DISCOVERIES', value: '—', sub: 'Not yet wired', color: '#818CF8' },
              { label: 'NEEDS REVIEW', value: '—', sub: 'Not yet wired', color: 'var(--amber)' },
            ].map((s) => (
              <div key={s.label} style={{ background: 'var(--s1)', padding: '16px 18px' }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em', marginBottom: 8 }}>{s.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: s.color, fontFamily: "'IBM Plex Mono', monospace", lineHeight: 1 }}>{s.value}</div>
                <div style={{ fontSize: 10, color: 'var(--t1)', marginTop: 6 }}>{s.sub}</div>
              </div>
            ))}
          </div>

          {/* Deal Pipeline table */}
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)' }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>DEAL PIPELINE</span>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>{activeDeals} record{activeDeals !== 1 ? 's' : ''}</span>
                <button onClick={() => router.push('/deals/new')} style={{ padding: '4px 12px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>+ New</button>
              </div>
            </div>

            {/* Column headers */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 90px 160px 70px 200px 140px 90px', padding: '10px 20px', borderBottom: '1px solid var(--s3)' }}>
              {['BORROWER', 'TYPE', 'DEAL SIZE', 'ANALYST', 'STATUS', 'CONFIDENCE', 'UPDATED'].map((h) => (
                <span key={h} style={{ fontSize: 9, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>
              ))}
            </div>

            {deals.length === 0 && (
              <div style={{ padding: '48px 20px', textAlign: 'center', color: 'var(--t2)', fontSize: 13 }}>
                No deals yet.{' '}
                <span style={{ color: 'var(--accent)', cursor: 'pointer' }} onClick={() => router.push('/deals/new')}>Create your first deal →</span>
              </div>
            )}

            {deals.map((deal) => {
              const name = (deal.company_name || deal.name || 'Untitled') as string
              const shortId = deal.id.replace(/-/g, '').slice(0, 12).toUpperCase()
              const analyst = ((deal.analyst_initials || '—') as string).toUpperCase()
              const currency = (deal.currency || 'KES') as string
              const updatedAt = deal.created_at
                ? new Date(deal.created_at as string).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
                : '—'
              const status = statuses[deal.id] ?? STATUS_UPLOADING
              const run = latestRunByDeal[deal.id]
              const dealSize = run
                ? `${currency} ${(run.non_transfer_abs_total_cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : `${currency} —`
              const confidencePct = run ? (run.final_confidence_bp / 100).toFixed(1) : null
              const tierColor: Record<string, string> = { High: 'var(--green)', Medium: 'var(--amber)', Low: 'var(--red)' }
              return (
                <div
                  key={deal.id}
                  onClick={() => router.push(`/v1/deal?deal_id=${deal.id}`)}
                  style={{ display: 'grid', gridTemplateColumns: '2fr 90px 160px 70px 200px 140px 90px', padding: '14px 20px', borderBottom: '1px solid var(--s3)', cursor: 'pointer' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(20,184,166,0.04)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--t0)' }}>{name}</div>
                    <div style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", marginTop: 2 }}>{shortId} · {currency}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    <span style={{ fontSize: 10, color: 'var(--t2)' }}>—</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', fontSize: 13, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{dealSize}</div>
                  <div style={{ display: 'flex', alignItems: 'center', fontSize: 13, fontWeight: 600, color: 'var(--t0)' }}>{analyst}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--t1)' }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: status.dot, display: 'inline-block', flexShrink: 0 }} />
                    {status.label}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: run ? tierColor[run.tier] : 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>
                    {confidencePct ? `${confidencePct}% · ${run!.tier}` : '—'}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: 'var(--t2)' }}>{updatedAt}</div>
                </div>
              )
            })}
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', gap: 24, marginTop: 14, flexWrap: 'wrap' }}>
            {[
              { dot: 'var(--green)', label: 'VERIFIED — bank-derived' },
              { dot: '#818CF8', label: 'INFERRED — model output' },
              { dot: 'var(--amber)', label: 'NEEDS REVIEW — analyst action' },
              { dot: 'var(--red)', label: 'FLAGGED — requires action' },
            ].map((l) => (
              <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--t2)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: l.dot, display: 'inline-block' }} />
                {l.label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
