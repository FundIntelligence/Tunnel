'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { getExportSummary, downloadSnapshotPdf, exportTransactionsCsvBlob, ExportSummary } from '@/lib/v1-api'

const CHECKLIST = [
  { key: 'files', label: 'Documents uploaded', check: (s: ExportSummary) => s.files_uploaded > 0 },
  { key: 'txns', label: 'Transactions processed', check: (s: ExportSummary) => s.total_transactions > 0 },
  { key: 'overrides', label: 'Override review complete', check: (s: ExportSummary) => s.override_count >= 0 },
  { key: 'snapshot', label: 'Snapshot exported', check: (s: ExportSummary) => s.has_snapshot },
  { key: 'intelligence', label: 'Intelligence queries logged', check: (s: ExportSummary) => s.logged_entries > 0 },
]

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={{
      background: 'var(--s1)',
      border: '1px solid var(--b1)',
      borderRadius: 8,
      padding: '20px 24px',
    }}>
      <div style={{ fontSize: 11, color: 'var(--t2)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace", marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--t0)', fontFamily: "'IBM Plex Mono', monospace", lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: 'var(--t2)', marginTop: 6 }}>{sub}</div>
      )}
    </div>
  )
}

export default function ExportPage() {
  const params = useParams()
  const dealId = params?.deal_id as string

  const [summary, setSummary] = useState<ExportSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [csvLoading, setCsvLoading] = useState(false)

  useEffect(() => {
    if (!dealId) return
    getExportSummary(dealId)
      .then(setSummary)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [dealId])

  const handlePdf = async () => {
    if (!dealId || pdfLoading) return
    setPdfLoading(true)
    try {
      const res = await downloadSnapshotPdf(dealId)
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `parity-snapshot-${dealId.slice(0, 8)}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'PDF download failed')
    } finally {
      setPdfLoading(false)
    }
  }

  const handleCsv = async () => {
    if (!dealId || csvLoading) return
    setCsvLoading(true)
    try {
      const res = await exportTransactionsCsvBlob(dealId)
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `parity-transactions-${dealId.slice(0, 8)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'CSV export failed')
    } finally {
      setCsvLoading(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: 'var(--bg)' }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: 'var(--t2)', letterSpacing: '0.1em' }}>
          LOADING…
        </div>
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div style={{ padding: 40 }}>
        <div style={{ color: 'var(--red)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 13 }}>
          {error || 'Failed to load export summary'}
        </div>
      </div>
    )
  }

  const tierColor = summary.tier === 'High' ? 'var(--green)' : summary.tier === 'Medium' ? 'var(--amber)' : 'var(--red)'

  return (
    <div style={{ padding: '40px 48px', maxWidth: 960, fontFamily: "'IBM Plex Sans', sans-serif" }}>
      {/* Header */}
      <div style={{ marginBottom: 36 }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: 'var(--t2)', letterSpacing: '0.12em', marginBottom: 8 }}>
          P/ EXPORT &amp; COMPLETION
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--t0)', margin: 0, letterSpacing: '-0.01em' }}>
          {summary.deal_name}
        </h1>
        {summary.company_name && (
          <div style={{ fontSize: 13, color: 'var(--t2)', marginTop: 4 }}>{summary.company_name}</div>
        )}
      </div>

      {/* Metrics grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 40 }}>
        <MetricCard label="TRANSACTIONS" value={summary.total_transactions.toLocaleString()} />
        <MetricCard label="OVERRIDES RESOLVED" value={summary.override_count} />
        <MetricCard label="INTELLIGENCE LOGGED" value={summary.logged_entries} />
        <MetricCard label="FILES UPLOADED" value={summary.files_uploaded} />
        <MetricCard
          label="CONFIDENCE TIER"
          value={summary.tier}
          sub={summary.has_snapshot ? 'from latest snapshot' : 'no snapshot yet'}
        />
        <MetricCard
          label="ANALYST"
          value={summary.analyst_initials || '—'}
        />
      </div>

      {/* Confidence tier badge */}
      {summary.has_snapshot && (
        <div style={{
          background: 'var(--s1)',
          border: `1px solid ${tierColor}33`,
          borderRadius: 8,
          padding: '16px 24px',
          marginBottom: 32,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: tierColor, flexShrink: 0 }} />
          <div>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: tierColor, letterSpacing: '0.08em' }}>
              {summary.tier.toUpperCase()} CONFIDENCE
            </span>
            <span style={{ fontSize: 12, color: 'var(--t2)', marginLeft: 16 }}>
              Based on transaction coverage and reconciliation analysis
            </span>
          </div>
        </div>
      )}

      {/* Downloads */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ fontSize: 11, color: 'var(--t2)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace", marginBottom: 16 }}>
          EXPORTS
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={handlePdf}
            disabled={!summary.has_snapshot || pdfLoading}
            style={{
              padding: '12px 24px',
              background: summary.has_snapshot ? 'var(--accent)' : 'var(--s3)',
              border: 'none',
              borderRadius: 6,
              color: summary.has_snapshot ? '#fff' : 'var(--b1)',
              fontSize: 13,
              fontFamily: "'IBM Plex Sans', sans-serif",
              cursor: summary.has_snapshot ? 'pointer' : 'not-allowed',
              fontWeight: 600,
              letterSpacing: '0.02em',
              transition: 'opacity 0.15s',
              opacity: pdfLoading ? 0.6 : 1,
            }}
          >
            {pdfLoading ? 'Generating…' : 'Download PDF Snapshot'}
          </button>
          <button
            onClick={handleCsv}
            disabled={summary.total_transactions === 0 || csvLoading}
            style={{
              padding: '12px 24px',
              background: 'transparent',
              border: `1px solid ${summary.total_transactions > 0 ? 'var(--accent)' : 'var(--b1)'}`,
              borderRadius: 6,
              color: summary.total_transactions > 0 ? 'var(--accent)' : 'var(--b1)',
              fontSize: 13,
              fontFamily: "'IBM Plex Sans', sans-serif",
              cursor: summary.total_transactions > 0 ? 'pointer' : 'not-allowed',
              fontWeight: 600,
              letterSpacing: '0.02em',
              transition: 'opacity 0.15s',
              opacity: csvLoading ? 0.6 : 1,
            }}
          >
            {csvLoading ? 'Exporting…' : 'Export Transactions CSV'}
          </button>
        </div>
        {!summary.has_snapshot && (
          <div style={{ fontSize: 12, color: 'var(--t2)', marginTop: 8 }}>
            Run the export from the Upload page to generate a PDF snapshot.
          </div>
        )}
      </div>

      {/* Checklist */}
      <div>
        <div style={{ fontSize: 11, color: 'var(--t2)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace", marginBottom: 16 }}>
          COMPLETION CHECKLIST
        </div>
        <div style={{
          background: 'var(--s1)',
          border: '1px solid var(--b1)',
          borderRadius: 8,
          overflow: 'hidden',
        }}>
          {CHECKLIST.map((item, i) => {
            const done = item.check(summary)
            return (
              <div
                key={item.key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  padding: '14px 20px',
                  borderBottom: i < CHECKLIST.length - 1 ? '1px solid #131D2E' : undefined,
                }}
              >
                <div style={{
                  width: 18,
                  height: 18,
                  borderRadius: 4,
                  border: done ? 'none' : '1px solid var(--b1)',
                  background: done ? 'var(--green)' : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  {done && (
                    <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                      <path d="M1 4L3.5 6.5L9 1" stroke="#080C18" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
                <span style={{ fontSize: 13, color: done ? 'var(--t1)' : 'var(--t2)' }}>
                  {item.label}
                </span>
                {done && (
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace" }}>
                    DONE
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
