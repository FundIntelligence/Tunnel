'use client'

import { useEffect, useState, useCallback } from 'react'
import { DataTable, Column } from '@/components/DataTable'
import { StatusBadge } from '@/components/StatusBadge'
import { PageHeader } from '@/components/PageHeader'
import { EnvBadge } from '@/components/EnvBadge'
import { ENV_HEADER } from '@/lib/env-header'
import { toEAT } from './utils'

interface SandboxKey {
  id: string
  partner_name: string
  contact_email: string
  calls_used: number
  call_cap: number
  status: string
  created_at: string
  [key: string]: unknown
}

const inputStyle: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: '8px 10px',
  fontFamily: "'IBM Plex Sans', sans-serif",
  fontSize: 13,
  color: 'var(--t0)',
  background: 'var(--white)',
  width: '100%',
}

const labelStyle: React.CSSProperties = {
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 11,
  letterSpacing: '0.06em',
  color: 'var(--t2)',
  marginBottom: 4,
  display: 'block',
}

export default function SandboxKeysPage() {
  const [rows, setRows] = useState<SandboxKey[]>([])
  const [loading, setLoading] = useState(true)
  const [partnerName, setPartnerName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [issuing, setIssuing] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [revealedKey, setRevealedKey] = useState<{ rawKey: string; partnerName: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [env, setEnv] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await fetch('/api/data/sandbox-keys')
    const data = await res.json()
    setRows(Array.isArray(data) ? data : [])
    setEnv(res.headers.get(ENV_HEADER))
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleIssue = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (!partnerName.trim() || !contactEmail.trim()) {
      setFormError('Partner name and contact email are required')
      return
    }
    setIssuing(true)
    try {
      const res = await fetch('/api/data/sandbox-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ partner_name: partnerName.trim(), contact_email: contactEmail.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        setFormError(data?.error ?? 'Failed to issue key')
        return
      }
      setRevealedKey({ rawKey: data.raw_key, partnerName: data.partner_name })
      setCopied(false)
      setPartnerName('')
      setContactEmail('')
      await load()
    } finally {
      setIssuing(false)
    }
  }

  const handleRevoke = async (row: SandboxKey) => {
    if (row.status === 'revoked') return
    const ok = window.confirm(
      `Revoke the sandbox key for "${row.partner_name}"? This cannot be undone — the partner will need a new key to make further calls.`
    )
    if (!ok) return
    const res = await fetch(`/api/data/sandbox-keys/${row.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'revoke' }),
    })
    if (res.ok) await load()
  }

  const columns: Column<SandboxKey>[] = [
    { key: 'partner_name', label: 'Partner' },
    { key: 'contact_email', label: 'Contact' },
    {
      key: 'calls_used',
      label: 'Usage',
      render: (_val, row) => `${row.calls_used.toLocaleString()} / ${row.call_cap.toLocaleString()}`,
    },
    {
      key: 'status',
      label: 'Status',
      render: (val) => <StatusBadge status={val as string} />,
    },
    {
      key: 'created_at',
      label: 'Created At',
      render: (val) => toEAT(val as string),
    },
    {
      key: 'id',
      label: '',
      render: (_val, row) =>
        row.status === 'revoked' ? (
          <span style={{ color: 'var(--t2)', fontSize: 12 }}>—</span>
        ) : (
          <button
            onClick={() => handleRevoke(row)}
            style={{
              border: '1px solid rgba(220,38,38,0.3)',
              background: 'var(--red-d)',
              color: 'var(--red)',
              borderRadius: 6,
              padding: '4px 10px',
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 11,
              cursor: 'pointer',
            }}
          >
            Revoke
          </button>
        ),
    },
  ]

  return (
    <div style={{ padding: '40px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <PageHeader
          title="Sandbox Keys"
          subtitle={loading ? 'Loading…' : `${rows.length} keys — scope: sandbox-classify`}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
          {env === 'sandbox' && <EnvBadge env="sandbox" />}
        </div>
      </div>

      {revealedKey && (
        <div
          style={{
            background: 'var(--teal-d)',
            border: '1px solid var(--teal)',
            borderRadius: 8,
            padding: '16px 20px',
            marginBottom: 24,
          }}
        >
          <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 13, fontWeight: 600, color: 'var(--t0)', marginBottom: 6 }}>
            Key issued for {revealedKey.partnerName} — shown once, right now, and never again
          </div>
          <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 12, color: 'var(--t1)', marginBottom: 10 }}>
            Copy this value and send it to the partner now. It is not stored anywhere retrievable — if it&apos;s lost, revoke this key and issue a new one.
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <code
              style={{
                background: 'var(--white)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '8px 12px',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 13,
                color: 'var(--t0)',
                flex: 1,
                overflowX: 'auto',
                whiteSpace: 'nowrap',
              }}
            >
              {revealedKey.rawKey}
            </code>
            <button
              onClick={() => {
                navigator.clipboard.writeText(revealedKey.rawKey)
                setCopied(true)
              }}
              style={{
                border: '1px solid var(--teal)',
                background: 'var(--white)',
                color: 'var(--teal)',
                borderRadius: 6,
                padding: '8px 12px',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button
              onClick={() => setRevealedKey(null)}
              style={{
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--t1)',
                borderRadius: 6,
                padding: '8px 12px',
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <form
        onSubmit={handleIssue}
        style={{
          background: 'var(--paper)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '20px',
          marginBottom: 24,
          display: 'flex',
          gap: 16,
          alignItems: 'flex-end',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 200px' }}>
          <label style={labelStyle}>PARTNER NAME</label>
          <input
            style={inputStyle}
            value={partnerName}
            onChange={(e) => setPartnerName(e.target.value)}
            placeholder="Acme Sandbox Partner"
          />
        </div>
        <div style={{ flex: '1 1 220px' }}>
          <label style={labelStyle}>CONTACT EMAIL</label>
          <input
            style={inputStyle}
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="dev@partner.com"
          />
        </div>
        <div style={{ flex: '0 0 auto' }}>
          <label style={labelStyle}>SCOPE</label>
          <div style={{ ...inputStyle, background: 'var(--bg2)', color: 'var(--t1)' }}>sandbox-classify</div>
        </div>
        <button
          type="submit"
          disabled={issuing}
          style={{
            border: 'none',
            background: 'var(--teal)',
            color: 'var(--white)',
            borderRadius: 6,
            padding: '9px 18px',
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 12,
            fontWeight: 500,
            cursor: issuing ? 'default' : 'pointer',
            opacity: issuing ? 0.6 : 1,
          }}
        >
          {issuing ? 'Issuing…' : 'Issue Key'}
        </button>
        {formError && (
          <div style={{ flexBasis: '100%', color: 'var(--red)', fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 12 }}>
            {formError}
          </div>
        )}
      </form>

      <div style={{ background: 'var(--paper)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'hidden' }}>
        <DataTable columns={columns} rows={rows} />
      </div>
    </div>
  )
}
