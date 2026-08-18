'use client'

import { useEffect, useState, useCallback, useRef, Fragment } from 'react'
import { StatusBadge } from '@/components/StatusBadge'
import { PageHeader } from '@/components/PageHeader'
import { EnvBadge } from '@/components/EnvBadge'
import { ENV_HEADER } from '@/lib/env-header'
import { toEAT, refreshedLabel, downloadCSV } from './utils'

interface MusaSession {
  session_id: string
  venture_id: string
  venture_name: string
  venture_country: string
  deal_id: string | null
  status: string
  created_at: string
  completed_at: string | null
  document_urls: unknown
  error_message: string | null
  webhook_last_status_code: number | null
  webhook_last_attempted_at: string | null
  webhook_last_error: string | null
  webhook_delivered_at: string | null
  webhook_resend_count: number
}

function webhookDeliveryLabel(row: MusaSession): { text: string; color: string } {
  if (!row.webhook_last_attempted_at) {
    return { text: 'Not sent yet', color: 'var(--t3)' }
  }
  if (row.webhook_delivered_at) {
    return { text: 'Delivered', color: 'var(--green)' }
  }
  const code = row.webhook_last_status_code
  return { text: code ? `Failed (${code})` : 'Failed', color: 'var(--red)' }
}

function documentUrlList(document_urls: unknown): string[] {
  if (!Array.isArray(document_urls)) return []
  return document_urls.map((item) =>
    typeof item === 'string' ? item : (item as { url?: string })?.url ?? JSON.stringify(item)
  )
}

export default function MusaSessionsPage() {
  const [rows, setRows] = useState<MusaSession[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [lastFetched, setLastFetched] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0)
  const loadingRef = useRef(false)
  const [resendingId, setResendingId] = useState<string | null>(null)
  const [resendResult, setResendResult] = useState<{ sessionId: string; message: string; ok: boolean } | null>(null)
  const [env, setEnv] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (loadingRef.current) return
    loadingRef.current = true
    try {
      const res = await fetch('/api/data/musa-sessions')
      const data = await res.json()
      if (!res.ok) {
        throw new Error(typeof data?.error === 'string' ? data.error : `Request failed (${res.status})`)
      }
      const sessions: MusaSession[] = Array.isArray(data) ? data : (data?.sessions ?? [])
      setRows(sessions)
      setEnv(res.headers.get(ENV_HEADER))
      setError(null)
      setLastFetched(new Date().toISOString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleResend = async (sessionId: string) => {
    setResendingId(sessionId)
    setResendResult(null)
    try {
      const res = await fetch(`/api/data/musa-sessions/${encodeURIComponent(sessionId)}/resend-webhook`, {
        method: 'POST',
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setResendResult({ sessionId, ok: false, message: data?.error ?? `Resend failed (${res.status})` })
        return
      }
      setResendResult({
        sessionId,
        ok: true,
        message: data?.webhook_delivered
          ? `Resent — Musa returned ${data.webhook_status_code}`
          : `Resend attempt ${data?.resend_count ?? '?'} sent — Musa returned ${data?.webhook_status_code ?? 'no response'}`,
      })
      await load()
    } finally {
      setResendingId(null)
    }
  }

  useEffect(() => {
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [load])

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const handleExport = () => {
    const exportRows = rows.map((r) => ({
      session_id: r.session_id,
      venture_name: r.venture_name,
      venture_country: r.venture_country,
      status: r.status,
      created_at: r.created_at,
      completed_at: r.completed_at,
      error_message: r.error_message,
    }))
    downloadCSV(exportRows, `musa-sessions-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  const columns: { key: string; label: string }[] = [
    { key: 'session_id', label: 'Session ID' },
    { key: 'venture_name', label: 'Venture' },
    { key: 'venture_country', label: 'Country' },
    { key: 'status', label: 'Status' },
    { key: 'webhook', label: 'Webhook' },
    { key: 'created_at', label: 'Created At' },
    { key: 'error_message', label: 'Error' },
  ]

  return (
    <div style={{ padding: '40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <PageHeader
          title="Musa Sessions"
          subtitle={loading ? 'Loading…' : `${rows.length} sessions (last 100)`}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {env === 'prod' && <EnvBadge env="prod" />}
          {lastFetched && (
            <span style={{ fontSize: 12, color: 'var(--t3)', fontFamily: "'IBM Plex Mono', monospace" }}>
              {refreshedLabel(lastFetched)}
            </span>
          )}
          <button
            onClick={() => load()}
            title="Refresh"
            style={{
              border: '1px solid var(--border)',
              background: 'var(--paper)',
              borderRadius: 6,
              padding: '6px 10px',
              fontSize: 13,
              cursor: 'pointer',
              color: 'var(--t1)',
            }}
          >
            ↻
          </button>
          <button
            onClick={handleExport}
            disabled={rows.length === 0}
            style={{
              border: '1px solid var(--border)',
              background: 'var(--paper)',
              borderRadius: 6,
              padding: '6px 12px',
              fontSize: 13,
              cursor: rows.length === 0 ? 'default' : 'pointer',
              color: 'var(--t1)',
              opacity: rows.length === 0 ? 0.5 : 1,
            }}
          >
            ⬇ Download CSV
          </button>
        </div>
      </div>

      <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        {rows.length === 0 ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px 24px',
            color: error ? 'var(--red)' : 'var(--t2)',
            fontFamily: "'IBM Plex Sans', sans-serif",
            fontSize: 14,
          }}>
            {loading ? 'Loading…' : error ? `Failed to load sessions: ${error}` : 'No records found'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: "'IBM Plex Sans', sans-serif",
              fontSize: 13,
            }}>
              <thead>
                <tr style={{ background: 'var(--bg2)' }}>
                  {columns.map((col) => (
                    <th key={col.key} style={{
                      padding: '10px 16px',
                      textAlign: 'left',
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontWeight: 500,
                      fontSize: 11,
                      letterSpacing: '0.06em',
                      color: 'var(--t2)',
                      borderBottom: '1px solid var(--border)',
                      whiteSpace: 'nowrap',
                    }}>
                      {col.label.toUpperCase()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => {
                  const rowKey = row.session_id || `row-${idx}`
                  const isExpanded = expandedId === rowKey
                  const docUrls = isExpanded ? documentUrlList(row.document_urls) : []
                  return (
                    <Fragment key={rowKey}>
                      <tr
                        onClick={() => setExpandedId((prev) => (prev === rowKey ? null : rowKey))}
                        style={{
                          cursor: 'pointer',
                          background: isExpanded ? 'var(--teal-d)' : 'var(--paper)',
                          transition: 'background 0.1s',
                        }}
                        onMouseOver={(e) => {
                          if (!isExpanded) (e.currentTarget as HTMLTableRowElement).style.background = 'var(--teal-d)'
                        }}
                        onMouseOut={(e) => {
                          if (!isExpanded) (e.currentTarget as HTMLTableRowElement).style.background = 'var(--paper)'
                        }}
                      >
                        <td style={{
                          padding: '12px 16px',
                          borderBottom: '1px solid var(--border)',
                          fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 12,
                          color: 'var(--t0)',
                          maxWidth: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }} title={row.session_id}>
                          {row.session_id?.slice(0, 16)}…
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, color: 'var(--t0)' }}>
                          {row.venture_name ?? '—'}
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, color: 'var(--t0)' }}>
                          {row.venture_country ?? '—'}
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, color: 'var(--t0)' }}>
                          <StatusBadge status={row.status} />
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
                          {(() => {
                            const wh = webhookDeliveryLabel(row)
                            return (
                              <span style={{ color: wh.color, fontSize: 12 }}>
                                {wh.text}
                                {row.webhook_resend_count > 0 && ` · resent ${row.webhook_resend_count}×`}
                              </span>
                            )
                          })()}
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, color: 'var(--t0)' }}>
                          {toEAT(row.created_at)}
                        </td>
                        <td style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: 13, color: 'var(--t0)' }}>
                          {row.error_message ? (
                            <span style={{ color: 'var(--red)', fontSize: 12, cursor: 'pointer' }}>
                              ⚠ error — click to view
                            </span>
                          ) : (
                            <span style={{ color: 'var(--t3)' }}>—</span>
                          )}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={columns.length} style={{ padding: 0, borderBottom: '1px solid var(--border)' }}>
                            <div style={{ padding: 16, background: 'var(--bg2)' }}>
                              <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: 8, columnGap: 12, fontSize: 13 }}>
                                <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                  COUNTRY
                                </div>
                                <div style={{ color: 'var(--t0)' }}>{row.venture_country || '—'}</div>

                                <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                  CREATED
                                </div>
                                <div style={{ color: 'var(--t0)' }}>{toEAT(row.created_at)}</div>

                                {row.completed_at && (
                                  <>
                                    <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                      COMPLETED
                                    </div>
                                    <div style={{ color: 'var(--t0)' }}>{toEAT(row.completed_at)}</div>
                                  </>
                                )}

                                <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                  DOCUMENTS
                                </div>
                                <div style={{ color: 'var(--t0)' }}>
                                  {docUrls.length === 0 ? (
                                    <span style={{ color: 'var(--t3)' }}>—</span>
                                  ) : (
                                    <>
                                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                                        {docUrls.map((url, urlIdx) => (
                                          <li key={urlIdx}>
                                            <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--teal)' }}>
                                              {url}
                                            </a>
                                          </li>
                                        ))}
                                      </ul>
                                      {/* PAR-145: these are Musa's own presigned URLs, captured verbatim from
                                          their session-creation request — Parity never takes ownership of that
                                          storage, so unlike Parser Requests' storage_path there is no credential
                                          Parity holds to mint a fresh one. Once Musa's own expiry passes, this
                                          link is gone for good; that's expected, not an admin bug. */}
                                      <div style={{ fontSize: 11, color: 'var(--t3)', marginTop: 4 }}>
                                        External links from Musa&apos;s own storage — expire independently on
                                        their side and can&apos;t be refreshed by Parity.
                                      </div>
                                    </>
                                  )}
                                </div>

                                {row.error_message && (
                                  <>
                                    <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                      ERROR
                                    </div>
                                    <div style={{ color: 'var(--red)', whiteSpace: 'pre-wrap' }}>{row.error_message}</div>
                                  </>
                                )}

                                <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                  WEBHOOK
                                </div>
                                <div>
                                  {(() => {
                                    const wh = webhookDeliveryLabel(row)
                                    const isProcessing = row.status === 'processing'
                                    const isResending = resendingId === row.session_id
                                    return (
                                      <>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                                          <span style={{ color: wh.color, fontWeight: 500 }}>{wh.text}</span>
                                          {row.webhook_last_attempted_at && (
                                            <span style={{ color: 'var(--t2)', fontSize: 12 }}>
                                              last attempt {toEAT(row.webhook_last_attempted_at)}
                                            </span>
                                          )}
                                          {row.webhook_resend_count > 0 && (
                                            <span style={{ color: 'var(--t2)', fontSize: 12 }}>
                                              · resent {row.webhook_resend_count}×
                                            </span>
                                          )}
                                        </div>
                                        {row.webhook_last_error && (
                                          <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                                            {row.webhook_last_error}
                                          </div>
                                        )}
                                        <button
                                          onClick={() => handleResend(row.session_id)}
                                          disabled={isProcessing || isResending}
                                          title={isProcessing ? 'Session is still processing — nothing to resend yet' : undefined}
                                          style={{
                                            marginTop: 8,
                                            border: '1px solid var(--teal)',
                                            background: 'var(--white)',
                                            color: 'var(--teal)',
                                            borderRadius: 6,
                                            padding: '5px 12px',
                                            fontFamily: "'IBM Plex Mono', monospace",
                                            fontSize: 11,
                                            cursor: isProcessing || isResending ? 'default' : 'pointer',
                                            opacity: isProcessing || isResending ? 0.5 : 1,
                                          }}
                                        >
                                          {isResending ? 'Resending…' : 'Resend Webhook'}
                                        </button>
                                        {resendResult && resendResult.sessionId === row.session_id && (
                                          <div
                                            style={{
                                              marginTop: 6,
                                              fontSize: 12,
                                              color: resendResult.ok ? 'var(--green)' : 'var(--red)',
                                            }}
                                          >
                                            {resendResult.message}
                                          </div>
                                        )}
                                      </>
                                    )
                                  })()}
                                </div>

                                {row.deal_id && (
                                  <>
                                    <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                      SNAPSHOT
                                    </div>
                                    <div>
                                      <a
                                        href={`/api/data/deals/${row.deal_id}/snapshot-pdf`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{ color: 'var(--teal)' }}
                                      >
                                        View Snapshot PDF
                                      </a>
                                    </div>
                                  </>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
