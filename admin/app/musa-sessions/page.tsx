'use client'

import { useEffect, useState, useCallback, useRef, Fragment } from 'react'
import { StatusBadge } from '@/components/StatusBadge'
import { PageHeader } from '@/components/PageHeader'
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
}

const SNAPSHOT_PDF_BASE = 'https://parity-backend-prod-121148713552.us-central1.run.app/v1/deals'

function documentUrlList(document_urls: unknown): string[] {
  if (!Array.isArray(document_urls)) return []
  return document_urls.map((item) =>
    typeof item === 'string' ? item : (item as { url?: string })?.url ?? JSON.stringify(item)
  )
}

interface DocBreakdownItem {
  filename?: string
  file_type?: string
  parse_status?: string
  detail?: string | null
}

interface StructuredSessionError {
  error?: string
  message?: string
  documents_submitted?: number
  breakdown?: DocBreakdownItem[]
  likely_causes?: string[]
  action_required?: string
  supported_formats?: string[]
}

// Newer sessions store a structured JSON diagnostic in error_message; older
// sessions store a plain string. Return the parsed object only when it looks
// like our diagnostic, otherwise null so callers fall back to the raw string.
function parseSessionError(raw: string): StructuredSessionError | null {
  try {
    const parsed = JSON.parse(raw)
    if (
      parsed &&
      typeof parsed === 'object' &&
      (parsed.breakdown || parsed.likely_causes || parsed.error)
    ) {
      return parsed as StructuredSessionError
    }
  } catch {
    // not JSON — legacy plain-string error
  }
  return null
}

const PARSE_STATUS_LABEL: Record<string, string> = {
  UNSUPPORTED_FORMAT: 'unsupported bank — no parser',
  PARSE_ERROR: 'not a bank statement',
  BAD_SCHEMA: 'unreadable / bad format',
  PARSED_NO_ROWS: 'parsed, no transactions',
  PARSED: 'parsed OK',
  UNKNOWN: 'unknown',
}

function SessionError({ raw }: { raw: string }) {
  const structured = parseSessionError(raw)
  if (!structured) {
    // Legacy plain-string error — render as-is.
    return <div style={{ color: 'var(--red)', whiteSpace: 'pre-wrap' }}>{raw}</div>
  }

  const mono = "'IBM Plex Mono', monospace"
  return (
    <div style={{ color: 'var(--t0)', fontSize: 13, lineHeight: 1.5 }}>
      {structured.error && (
        <div style={{ color: 'var(--red)', fontFamily: mono, fontSize: 12, letterSpacing: '0.04em', marginBottom: 6 }}>
          {structured.error.replace(/_/g, ' ')}
        </div>
      )}
      {structured.message && <div style={{ marginBottom: 8 }}>{structured.message}</div>}

      {Array.isArray(structured.breakdown) && structured.breakdown.length > 0 && (
        <ul style={{ margin: '0 0 8px', paddingLeft: 18 }}>
          {structured.breakdown.map((d, i) => (
            <li key={i} style={{ marginBottom: 2 }}>
              <span style={{ fontFamily: mono, fontSize: 12 }}>{d.filename || 'unknown'}</span>
              {' — '}
              <span style={{ color: 'var(--t2)' }}>
                {PARSE_STATUS_LABEL[d.parse_status || 'UNKNOWN'] || d.parse_status}
              </span>
              {d.detail && <span style={{ color: 'var(--t3)' }}>{` (${d.detail})`}</span>}
            </li>
          ))}
        </ul>
      )}

      {Array.isArray(structured.likely_causes) && structured.likely_causes.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: 'var(--t2)', fontFamily: mono, fontSize: 11, letterSpacing: '0.06em', marginBottom: 2 }}>
            LIKELY CAUSES
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {structured.likely_causes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {structured.action_required && (
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: 'var(--t2)', fontFamily: mono, fontSize: 11, letterSpacing: '0.06em' }}>ACTION: </span>
          <span>{structured.action_required}</span>
        </div>
      )}

      {Array.isArray(structured.supported_formats) && structured.supported_formats.length > 0 && (
        <div style={{ color: 'var(--t2)', fontSize: 12 }}>
          Supported formats: {structured.supported_formats.join(', ')}
        </div>
      )}
    </div>
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
                                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                                      {docUrls.map((url, urlIdx) => (
                                        <li key={urlIdx}>
                                          <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--teal)' }}>
                                            {url}
                                          </a>
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </div>

                                {row.error_message && (
                                  <>
                                    <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                      ERROR
                                    </div>
                                    <SessionError raw={row.error_message} />
                                  </>
                                )}

                                {row.deal_id && (
                                  <>
                                    <div style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, letterSpacing: '0.06em' }}>
                                      SNAPSHOT
                                    </div>
                                    <div>
                                      <a
                                        href={`${SNAPSHOT_PDF_BASE}/${row.deal_id}/snapshot/pdf`}
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
