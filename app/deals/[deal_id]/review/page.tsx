'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { createBrowserClient } from '@/lib/supabase'
import { intelligenceAsk, logIntelligenceEntry } from '@/lib/v1-api'
import type { QueryType, UserRole } from '@/lib/v1-api'

// ── Constants ────────────────────────────────────────────────────────────────

const COMPUTING_STEPS = [
  'Parsing query against classified record…',
  'Resolving transaction references…',
  'Applying integer arithmetic…',
  'Cross-referencing entity registry…',
  'Compiling record entry…',
]

const QUERY_TYPES: { value: QueryType; label: string; color: string }[] = [
  { value: 'classification', label: 'CLASSIFICATION', color: 'var(--accent)' },
  { value: 'computation',    label: 'COMPUTATION',    color: '#A855F7' },
  { value: 'pattern',        label: 'PATTERN',        color: 'var(--accent)' },
]

// ── Types ────────────────────────────────────────────────────────────────────

type MessageKind = 'query' | 'computing' | 'response'

interface BaseMsg {
  id: string
  kind: MessageKind
  timestamp: Date
  userRole: UserRole
  queryType: QueryType
  analystInitials: string
}
interface QueryMsg extends BaseMsg { kind: 'query'; text: string }
interface ComputingMsg extends BaseMsg { kind: 'computing' }
interface ResponseMsg extends BaseMsg {
  kind: 'response'
  queryText: string
  responseText: string
  basisSources: string[]
  computationSteps: string[]
  isLogged: boolean
}
type Msg = QueryMsg | ComputingMsg | ResponseMsg

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(d: Date) {
  return d.toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function chipStyle(idx: number): React.CSSProperties {
  if (idx === 0) return { background: 'rgba(34,197,94,0.15)', color: 'var(--green)', border: '1px solid rgba(34,197,94,0.3)' }
  if (idx === 1) return { background: 'rgba(20,184,166,0.15)', color: 'var(--accent)', border: '1px solid rgba(20,184,166,0.3)' }
  return { background: 'rgba(71,85,105,0.2)', color: 'var(--t2)', border: '1px solid rgba(71,85,105,0.3)' }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function QueryBubble({ msg }: { msg: QueryMsg }) {
  const qt = QUERY_TYPES.find((q) => q.value === msg.queryType)
  return (
    <div className="flex justify-end mb-4">
      <div style={{ maxWidth: '72%' }}>
        <div className="flex items-center gap-2 justify-end mb-1">
          <span className="text-xs font-mono" style={{ color: 'var(--t2)' }}>{fmtTime(msg.timestamp)} EAT</span>
          <span
            className="text-xs px-1.5 py-0.5 rounded font-mono"
            style={{ background: qt ? `${qt.color}22` : 'var(--accent)22', color: qt?.color ?? 'var(--accent)', border: `1px solid ${qt?.color ?? 'var(--accent)'}44` }}
          >
            {msg.queryType.toUpperCase()}
          </span>
          <span
            className="text-xs px-2 py-0.5 rounded font-semibold"
            style={{
              background: msg.userRole === 'analyst' ? 'rgba(20,184,166,0.2)' : 'rgba(251,146,60,0.2)',
              color: msg.userRole === 'analyst' ? '#818CF8' : 'var(--amber)',
            }}
          >
            {msg.userRole === 'analyst' ? `ANALYST · ${msg.analystInitials}` : `CREDIT OFFICER · ${msg.analystInitials}`}
          </span>
        </div>
        <div
          className="px-4 py-3 rounded-xl text-sm"
          style={{ background: '#1E2942', border: '1px solid rgba(20,184,166,0.2)', color: 'var(--t0)' }}
        >
          {msg.text}
        </div>
      </div>
    </div>
  )
}

function ComputingBubble({ msg }: { msg: ComputingMsg }) {
  const [step, setStep] = useState(0)
  const [hashChars, setHashChars] = useState('a1b2c3d4e5f6')

  useEffect(() => {
    const iv = setInterval(() => {
      setStep((s) => Math.min(s + 1, COMPUTING_STEPS.length - 1))
    }, 280)
    const hv = setInterval(() => {
      setHashChars(
        Array.from({ length: 12 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('')
      )
    }, 80)
    return () => { clearInterval(iv); clearInterval(hv) }
  }, [])

  return (
    <div className="mb-4 ml-2">
      <div
        className="px-5 py-4 rounded-xl overflow-hidden"
        style={{ background: 'var(--bg)', border: '1px solid rgba(20,184,166,0.2)', maxWidth: '520px', position: 'relative' }}
      >
        {/* Scan line */}
        <div
          className="absolute top-0 left-0 right-0 h-px"
          style={{ background: 'linear-gradient(90deg, transparent, var(--accent), transparent)', animation: 'scanline 1.4s linear infinite' }}
        />
        <div className="text-xs font-mono mb-3" style={{ color: 'var(--t2)' }}>COMPUTING</div>
        <div className="space-y-1.5">
          {COMPUTING_STEPS.map((s, i) => (
            <div key={i} className="flex items-center gap-2 text-xs font-mono">
              <span style={{ color: i === step ? 'var(--accent)' : i < step ? 'var(--green)' : 'var(--s3)' }}>
                {i < step ? '✓' : i === step ? '⦿' : '○'}
              </span>
              <span style={{ color: i === step ? 'var(--accent)' : i < step ? 'var(--t2)' : 'var(--s3)', transition: 'color 0.2s' }}>
                {s}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs font-mono" style={{ color: 'var(--s4)' }}>
          SHA256 {hashChars}…
        </div>
      </div>
    </div>
  )
}

function ResponseBubble({
  msg,
  dealId,
  onLogged,
}: {
  msg: ResponseMsg
  dealId: string
  onLogged: (count: number) => void
}) {
  const [logging, setLogging] = useState(false)
  const [loggedAt, setLoggedAt] = useState<string | null>(null)
  const qt = QUERY_TYPES.find((q) => q.value === msg.queryType)

  const handleLog = async () => {
    if (msg.isLogged || loggedAt || logging) return
    setLogging(true)
    try {
      const { logged_count } = await logIntelligenceEntry(dealId, msg.id)
      setLoggedAt(fmtTime(new Date()))
      onLogged(logged_count)
    } catch {
      /* silent */
    } finally {
      setLogging(false)
    }
  }

  return (
    <div className="mb-6 ml-2" style={{ maxWidth: '680px' }}>
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: 'var(--s1)', border: '1px solid rgba(20,184,166,0.25)' }}
      >
        {/* Record header */}
        <div
          className="px-5 py-2.5 flex items-center justify-between"
          style={{ background: 'var(--bg)', borderBottom: '1px solid rgba(20,184,166,0.15)' }}
        >
          <span className="text-xs font-mono tracking-widest" style={{ color: 'var(--accent)' }}>
            P/ INTELLIGENCE RECORD
          </span>
          <span
            className="text-xs px-1.5 py-0.5 rounded font-mono"
            style={{ background: qt ? `${qt.color}22` : 'var(--accent)22', color: qt?.color ?? 'var(--accent)' }}
          >
            {msg.queryType.toUpperCase()}
          </span>
        </div>

        {/* Attribution */}
        <div className="px-5 pt-3 pb-1 text-xs font-mono" style={{ color: 'var(--t2)' }}>
          ↳ {msg.userRole === 'analyst' ? 'ANALYST' : 'OFFICER'}·{msg.analystInitials}·{fmtTime(msg.timestamp)} EAT
        </div>

        {/* Response body */}
        <div
          className="px-5 py-3 text-sm leading-relaxed"
          style={{ color: 'var(--t1)', fontFamily: 'IBM Plex Sans, sans-serif' }}
          dangerouslySetInnerHTML={{ __html: msg.responseText }}
        />

        {/* Computation steps (for computation queries) */}
        {msg.computationSteps.length > 0 && (
          <div className="px-5 pb-3">
            <div className="text-xs font-mono mb-1.5" style={{ color: 'var(--t2)' }}>STEPS</div>
            <div className="space-y-0.5">
              {msg.computationSteps.map((s, i) => (
                <div key={i} className="text-xs font-mono" style={{ color: 'var(--t2)' }}>
                  {i + 1}. {s}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Basis chips */}
        {msg.basisSources.length > 0 && (
          <div className="px-5 pb-3 flex flex-wrap gap-1.5">
            <span className="text-xs font-mono mr-1" style={{ color: 'var(--b2)' }}>BASIS</span>
            {msg.basisSources.map((src, i) => (
              <span
                key={i}
                className="text-xs px-2 py-0.5 rounded font-mono"
                style={chipStyle(i)}
              >
                {src}
              </span>
            ))}
          </div>
        )}

        {/* Log to record footer */}
        <div
          className="px-5 py-2.5 flex items-center justify-between"
          style={{ borderTop: '1px solid rgba(20,184,166,0.1)' }}
        >
          <span className="text-xs font-mono" style={{ color: 'var(--b2)' }}>
            {fmtTime(msg.timestamp)} EAT
          </span>
          {loggedAt ? (
            <span className="text-xs font-mono" style={{ color: 'var(--green)' }}>
              🔒 Logged · {msg.analystInitials} · {loggedAt} EAT
            </span>
          ) : (
            <button
              onClick={handleLog}
              disabled={logging}
              className="text-xs px-3 py-1 rounded font-mono transition-opacity"
              style={{ background: 'rgba(20,184,166,0.15)', color: '#818CF8', border: '1px solid rgba(20,184,166,0.3)', opacity: logging ? 0.6 : 1 }}
            >
              {logging ? '…' : 'Log to record'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReviewPage() {
  const router = useRouter()
  const params = useParams()
  const dealId = params['deal_id'] as string

  const [authChecked, setAuthChecked] = useState(false)
  const [userRole, setUserRole] = useState<UserRole>('analyst')
  const [queryType, setQueryType] = useState<QueryType>('classification')
  const [analystInitials, setAnalystInitials] = useState('AM')
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const [asking, setAsking] = useState(false)
  const [loggedCount, setLoggedCount] = useState(0)

  const streamRef = useRef<HTMLDivElement>(null)

  // Auth guard
  useEffect(() => {
    const supabase = createBrowserClient()
    if (!supabase) { router.replace('/login'); return }
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      const initials = (session.user.user_metadata?.analyst_initials as string) || ''
      if (initials) setAnalystInitials(initials.slice(0, 3).toUpperCase())
      setAuthChecked(true)
    })
  }, [router])

  // Auto-scroll on new message
  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleAsk = useCallback(async () => {
    const q = query.trim()
    if (!q || asking) return

    const computingId = crypto.randomUUID()
    const queryMsgId = crypto.randomUUID()
    const ts = new Date()

    setMessages((prev) => [
      ...prev,
      { id: queryMsgId, kind: 'query', timestamp: ts, userRole, queryType, analystInitials, text: q } as QueryMsg,
      { id: computingId, kind: 'computing', timestamp: ts, userRole, queryType, analystInitials } as ComputingMsg,
    ])
    setQuery('')
    setAsking(true)

    // Minimum computing display time
    const [result] = await Promise.allSettled([
      intelligenceAsk(dealId, q, queryType, userRole, analystInitials),
      new Promise((r) => setTimeout(r, 1600)),
    ])

    setMessages((prev) => {
      const withoutComputing = prev.filter((m) => m.id !== computingId)
      if (result.status === 'rejected') {
        return [
          ...withoutComputing,
          {
            id: crypto.randomUUID(),
            kind: 'response',
            timestamp: new Date(),
            userRole, queryType, analystInitials,
            queryText: q,
            responseText: `<span style="color:var(--red)">Error: ${(result.reason as Error)?.message ?? 'Request failed'}</span>`,
            basisSources: [],
            computationSteps: [],
            isLogged: false,
          } as ResponseMsg,
        ]
      }
      const data = result.value
      return [
        ...withoutComputing,
        {
          id: data.id,
          kind: 'response',
          timestamp: new Date(),
          userRole, queryType, analystInitials,
          queryText: q,
          responseText: data.response_text,
          basisSources: data.basis_sources,
          computationSteps: data.computation_steps,
          isLogged: false,
        } as ResponseMsg,
      ]
    })
    setAsking(false)
  }, [query, asking, dealId, queryType, userRole, analystInitials])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleAsk() }
  }

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)' }}>
        <div className="w-8 h-8 rounded-full border-2 border-teal-500 border-t-transparent animate-spin" />
      </div>
    )
  }

  const activeQT = QUERY_TYPES.find((q) => q.value === queryType)!

  return (
    <>
      <style>{`@keyframes scanline { from { transform: translateX(-100%) } to { transform: translateX(100%) } }`}</style>
      <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>
        {/* Top bar */}
        <div style={{ background: 'var(--s1)', borderBottom: '1px solid rgba(20,184,166,0.15)', flexShrink: 0 }}>
          <div className="max-w-4xl mx-auto px-6 py-3 flex items-center gap-4 flex-wrap">
            {/* Brand */}
            <span className="text-xs font-mono tracking-widest" style={{ color: 'var(--accent)', marginRight: 4 }}>
              PARITY REVIEW
            </span>

            {/* Mode toggle */}
            <button
              onClick={() => setUserRole((r) => r === 'analyst' ? 'officer' : 'analyst')}
              className="text-xs px-3 py-1 rounded font-semibold transition-colors"
              style={{
                background: userRole === 'analyst' ? 'rgba(20,184,166,0.2)' : 'rgba(251,146,60,0.2)',
                color: userRole === 'analyst' ? '#818CF8' : 'var(--amber)',
                border: `1px solid ${userRole === 'analyst' ? 'rgba(20,184,166,0.4)' : 'rgba(251,146,60,0.4)'}`,
              }}
            >
              {userRole === 'analyst' ? `ANALYST · ${analystInitials}` : `CREDIT OFFICER · ${analystInitials}`}
            </button>

            {/* Query type selector */}
            <div className="flex gap-1">
              {QUERY_TYPES.map((qt) => (
                <button
                  key={qt.value}
                  onClick={() => setQueryType(qt.value)}
                  className="text-xs px-2.5 py-1 rounded font-mono transition-colors"
                  style={{
                    background: queryType === qt.value ? `${qt.color}22` : 'transparent',
                    color: queryType === qt.value ? qt.color : 'var(--t2)',
                    border: `1px solid ${queryType === qt.value ? `${qt.color}55` : 'transparent'}`,
                  }}
                >
                  {qt.label}
                </button>
              ))}
            </div>

            {/* Spacer + stats */}
            <div className="ml-auto flex items-center gap-3">
              <span className="text-xs font-mono" style={{ color: loggedCount > 0 ? 'var(--green)' : 'var(--b2)' }}>
                {loggedCount} {loggedCount === 1 ? 'entry' : 'entries'} logged
              </span>
              <input
                value={analystInitials}
                onChange={(e) => setAnalystInitials(e.target.value.slice(0, 3).toUpperCase())}
                maxLength={3}
                className="w-12 px-2 py-1 rounded text-xs text-center uppercase font-mono outline-none"
                style={{ background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.2)', color: 'var(--accent)' }}
                title="Analyst initials"
              />
            </div>
          </div>
        </div>

        {/* Message stream */}
        <div ref={streamRef} className="flex-1 overflow-y-auto" style={{ minHeight: 0 }}>
          <div className="max-w-4xl mx-auto px-6 py-6">
            {messages.length === 0 && (
              <div className="text-center py-20 space-y-3">
                <div className="text-3xl font-mono" style={{ color: 'var(--s4)' }}>P/</div>
                <p className="text-sm" style={{ color: 'var(--b2)' }}>
                  Ask a question about this deal's classified transaction record.
                </p>
                <div className="flex flex-wrap justify-center gap-2 mt-4">
                  {[
                    "What's the annual inflow total?",
                    'Are there net-negative months?',
                    "What's the DSR?",
                    'What role is Meridian Capital?',
                  ].map((s) => (
                    <button
                      key={s}
                      onClick={() => setQuery(s)}
                      className="text-xs px-3 py-1.5 rounded-full font-mono"
                      style={{ background: 'var(--s1)', color: 'var(--t2)', border: '1px solid rgba(20,184,166,0.15)' }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => {
              if (msg.kind === 'query') return <QueryBubble key={msg.id} msg={msg as QueryMsg} />
              if (msg.kind === 'computing') return <ComputingBubble key={msg.id} msg={msg as ComputingMsg} />
              return (
                <ResponseBubble
                  key={msg.id}
                  msg={msg as ResponseMsg}
                  dealId={dealId}
                  onLogged={(count) => setLoggedCount(count)}
                />
              )
            })}
          </div>
        </div>

        {/* Sticky input */}
        <div style={{ background: 'var(--s1)', borderTop: '1px solid rgba(20,184,166,0.15)', flexShrink: 0 }}>
          <div className="max-w-4xl mx-auto px-6 py-4">
            <div className="flex gap-3 items-end">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1.5">
                  <span
                    className="text-xs font-mono px-1.5 py-0.5 rounded"
                    style={{ background: `${activeQT.color}22`, color: activeQT.color }}
                  >
                    {activeQT.label}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--b2)' }}>⌘↵ to submit</span>
                </div>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`Ask a ${queryType} question about this deal…`}
                  rows={2}
                  disabled={asking}
                  className="w-full px-3 py-2.5 rounded-lg text-sm outline-none resize-none"
                  style={{
                    background: 'var(--s2)',
                    border: '1px solid rgba(20,184,166,0.25)',
                    color: 'var(--t0)',
                    lineHeight: '1.5',
                  }}
                />
              </div>
              <button
                onClick={handleAsk}
                disabled={!query.trim() || asking}
                className="px-5 py-2.5 rounded-lg font-semibold text-sm transition-opacity mb-0.5"
                style={{ background: 'var(--accent)', color: '#fff', opacity: !query.trim() || asking ? 0.5 : 1, flexShrink: 0 }}
              >
                {asking ? (
                  <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                ) : 'Ask'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
