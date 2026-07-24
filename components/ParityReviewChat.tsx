'use client'

import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { askParityReview, getParityChatSession, clearParityChatSession } from '@/lib/v1-api'
import AnalystStatus from '@/components/AnalystStatus'

// ── Lightweight markdown → HTML ────────────────────────────────────────────

function convertTables(text: string): string {
  const lines = text.split(/\r?\n/)
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const trimmed = lines[i].trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      const block: string[] = []
      while (i < lines.length) {
        const t = lines[i].trim()
        if (t.startsWith('|') && t.endsWith('|')) {
          block.push(t)
          i++
        } else if (t === '' && block.length > 0 && i + 1 < lines.length && lines[i + 1].trim().startsWith('|')) {
          i++
        } else {
          break
        }
      }
      if (block.length >= 2) {
        out.push(renderTable(block))
      } else {
        out.push(...block)
      }
    } else {
      out.push(lines[i])
      i++
    }
  }
  return out.join('\n')
}

function renderTable(rows: string[]): string {
  const parseCells = (row: string) =>
    row.split('|').slice(1, -1).map(c => c.trim())

  // Find separator row (contains only -, :, spaces, |)
  let sepIdx = -1
  for (let i = 0; i < rows.length; i++) {
    if (/^\|[\s\-:|]+\|$/.test(rows[i])) { sepIdx = i; break }
  }

  const headerCells = sepIdx > 0 ? parseCells(rows[sepIdx - 1]) : null
  const bodyStart = sepIdx >= 0 ? sepIdx + 1 : (headerCells ? 1 : 0)
  const bodyRows = rows.slice(bodyStart).filter(r => !/^\|[\s\-:|]+\|$/.test(r))

  const thStyle = 'padding:5px 10px;border:1px solid var(--b1);font-size:11px;font-weight:600;color:var(--accent);text-align:left;white-space:nowrap'
  const tdStyle = 'padding:4px 10px;border:1px solid var(--b1);font-size:12px;color:var(--t1);white-space:nowrap'

  let html = '<div style="overflow-x:auto;margin:8px 0"><table style="border-collapse:collapse;width:100%;font-family:\'IBM Plex Mono\',monospace">'
  if (headerCells) {
    html += '<thead><tr>' + headerCells.map(c => `<th style="${thStyle}">${c}</th>`).join('') + '</tr></thead>'
  }
  html += '<tbody>'
  for (const row of bodyRows) {
    const cells = parseCells(row)
    html += '<tr>' + cells.map(c => `<td style="${tdStyle}">${c}</td>`).join('') + '</tr>'
  }
  html += '</tbody></table></div>'
  return html
}

function mdToHtml(md: string): string {
  let s = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  s = convertTables(s)
  return s
    .replace(/^## (.+)$/gm, '<h3 style="font-size:13px;font-weight:700;margin:12px 0 4px;color:var(--accent)">$1</h3>')
    .replace(/^### (.+)$/gm, '<h4 style="font-size:12px;font-weight:700;margin:10px 0 3px;color:var(--t1)">$1</h4>')
    .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--b1);margin:8px 0"/>')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--t0)">$1</strong>')
    .replace(/^• (.+)$/gm, '<div style="padding-left:12px;margin:2px 0">· $1</div>')
    .replace(/^- (.+)$/gm, '<div style="padding-left:12px;margin:2px 0">· $1</div>')
    .replace(/[📊💡🏦📈📉⚠️✅❌🔍💰📋🏢📌🔎💼📁📂🗂️📄📃📑🔔🔕]/gu, '')
    .replace(/\n/g, '<br/>')
}

// ── Types ────────────────────────────────────────────────────────────────────

type ChatMessage = { role: 'analyst' | 'parity'; text: string; time: string }

type ChatCache = {
  chatHistory: ChatMessage[]
  conversationHistory: Array<{ role: string; content: unknown }>
  proactiveTriggered: boolean
}

const chatCacheKey = (id: string) => ['parity-chat', id] as const

interface Props {
  dealId: string
  corpusReady: boolean
  isCheckingAnalysis?: boolean
  txnTotal: number
  statementCount: number
}

// ── Suggestion chips ─────────────────────────────────────────────────────────

const SUGGESTION_CHIPS = [
  'What is the average monthly net cashflow?',
  'Which entities represent the highest concentration risk?',
  'Are there any irregular payroll patterns?',
  'What is the peak debt service coverage ratio?',
]

// ── Component ────────────────────────────────────────────────────────────────

function ParityReviewChat({ dealId, corpusReady, isCheckingAnalysis, txnTotal, statementCount }: Props) {
  const queryClient = useQueryClient()
  const cached = queryClient.getQueryData<ChatCache>(chatCacheKey(dealId))

  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>(cached?.chatHistory ?? [])
  const [conversationHistory, setConversationHistory] = useState<Array<{ role: string; content: unknown }>>(cached?.conversationHistory ?? [])
  const [proactiveTriggered, setProactiveTriggered] = useState(cached?.proactiveTriggered ?? false)
  const [sessionLoaded, setSessionLoaded] = useState(cached != null)
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevDealIdRef = useRef(dealId)

  // Persisted analysis state (so reloading the Analysis tab doesn't force re-run)
  const [localCorpusReady, setLocalCorpusReady] = useState<boolean>(false)
  const [localTxnTotal, setLocalTxnTotal] = useState<number>(txnTotal)
  const [localStatementCount, setLocalStatementCount] = useState<number>(statementCount)

  const effectiveCorpusReady = corpusReady || localCorpusReady
  const effectiveTxnTotal = corpusReady ? txnTotal : localTxnTotal
  const effectiveStatementCount = corpusReady ? statementCount : localStatementCount

  // Load persisted analysis state on mount
  useEffect(() => {
    const key = `parity_analysis_${dealId}`
    if (typeof window === 'undefined') return
    try {
      const raw = localStorage.getItem(key)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed && parsed.ready) {
          setLocalCorpusReady(true)
          setLocalTxnTotal(parsed.txnTotal ?? txnTotal)
          setLocalStatementCount(parsed.statementCount ?? statementCount)
        }
      }
    } catch (e) {
      // ignore
    }
  }, [dealId, txnTotal, statementCount])

  // When authoritative corpusReady arrives from server, persist it locally
  useEffect(() => {
    const key = `parity_analysis_${dealId}`
    if (corpusReady) {
      try {
        localStorage.setItem(key, JSON.stringify({ ready: true, txnTotal, statementCount }))
        setLocalCorpusReady(true)
        setLocalTxnTotal(txnTotal)
        setLocalStatementCount(statementCount)
      } catch (e) { /* ignore */ }
    }
  }, [corpusReady, dealId, txnTotal, statementCount])

  // Sync chat state to QueryClient cache so it survives full-page navigation
  useEffect(() => {
    queryClient.setQueryData(chatCacheKey(dealId), { chatHistory, conversationHistory, proactiveTriggered })
  }, [dealId, chatHistory, conversationHistory, proactiveTriggered, queryClient])

  // Handle dealId prop change: swap in state for the new deal from cache
  useEffect(() => {
    if (prevDealIdRef.current === dealId) return
    prevDealIdRef.current = dealId
    const next = queryClient.getQueryData<ChatCache>(chatCacheKey(dealId))
    setChatHistory(next?.chatHistory ?? [])
    setConversationHistory(next?.conversationHistory ?? [])
    setProactiveTriggered(next?.proactiveTriggered ?? false)
    setSessionLoaded(next != null)
  }, [dealId, queryClient])

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chatHistory])

  // Load existing session on mount
  useEffect(() => {
    if (!corpusReady || sessionLoaded) return
    setSessionLoaded(true)

    const storageKey = `parity_chat_${dealId}`

    // Try to load cached chat from localStorage first (fast restore when navigating between tabs)
    let localHistoryLength = 0
    if (typeof window !== 'undefined') {
      try {
        const raw = localStorage.getItem(storageKey)
        if (raw) {
          const parsed = JSON.parse(raw)
          if (parsed && Array.isArray(parsed.chatHistory) && parsed.chatHistory.length > 0) {
            setChatHistory(parsed.chatHistory as ChatMessage[])
            setConversationHistory(parsed.conversationHistory ?? [])
            setProactiveTriggered(true) // don't re-trigger proactive since we have history
            localHistoryLength = parsed.chatHistory.length
          }
        }
      } catch (e) {
        // ignore localStorage parse errors
      }
    }

    ;(async () => {
      try {
        const session = await getParityChatSession(dealId)
        // The server saves chat_history BEFORE the parity response is appended (it only receives
        // the request body which doesn't include the answer yet), so local storage is always at
        // least as up-to-date. Only switch to the server version when it genuinely has more
        // messages — i.e. when another session (different device/browser) built a longer history.
        if (session.chat_history && session.chat_history.length > localHistoryLength) {
          setChatHistory(session.chat_history as ChatMessage[])
          setConversationHistory(session.conversation_history)
          setProactiveTriggered(true)
          try { if (typeof window !== 'undefined') localStorage.setItem(storageKey, JSON.stringify({ chatHistory: session.chat_history, conversationHistory: session.conversation_history })) } catch (e) { /* ignore */ }
          return
        }
        // Server has same or fewer messages — localStorage is more complete, keep it.
        if (localHistoryLength > 0) {
          setProactiveTriggered(true)
          return
        }
      } catch {
        // no server session — if we already loaded local data above, keep it; otherwise fall through to proactive
        if (localHistoryLength > 0) {
          setProactiveTriggered(true)
          return
        }
      }

      // No history anywhere — trigger proactive opening analysis
      setProactiveTriggered(true)
      doAsk('start')
    })()
  }, [corpusReady, sessionLoaded, dealId])

  // Persist chat and conversation history locally so switching tabs (client-side navigation) preserves state
  useEffect(() => {
    const storageKey = `parity_chat_${dealId}`
    if (typeof window === 'undefined') return
    try {
      const payload = { chatHistory, conversationHistory }
      // Only write if there is anything to save
      if ((chatHistory && chatHistory.length > 0) || (conversationHistory && conversationHistory.length > 0)) {
        localStorage.setItem(storageKey, JSON.stringify(payload))
      } else {
        // remove empty state to avoid stale entries
        localStorage.removeItem(storageKey)
      }
    } catch (e) {
      // ignore storage errors
    }
  }, [dealId, chatHistory, conversationHistory])

  const doAsk = useCallback(async (overrideMessage?: string) => {
    const message = overrideMessage || question.trim()
    if (!message || loading) return
    const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

    // Build updated chat history for persistence
    let updatedChatHistory = [...chatHistory]
    if (!overrideMessage) {
      updatedChatHistory = [...updatedChatHistory, { role: 'analyst' as const, text: message, time: now }]
      setChatHistory(updatedChatHistory)
      setQuestion('')
    }

    setLoading(true)
    try {
      const result = await askParityReview(dealId, message, conversationHistory, updatedChatHistory)
      const answerTime = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      const newHistory = [...updatedChatHistory, { role: 'parity' as const, text: result.response, time: answerTime }]
      setChatHistory(newHistory)
      setConversationHistory(result.conversation_history)
    } catch (e) {
      const errText = e instanceof Error ? e.message : 'Request failed'
      const errTime = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      setChatHistory(prev => [...prev, { role: 'parity', text: errText, time: errTime }])
    } finally {
      setLoading(false)
    }
  }, [question, loading, dealId, conversationHistory, chatHistory])

  const handleClearChat = useCallback(async () => {
    try { await clearParityChatSession(dealId) } catch { /* ignore */ }
    setChatHistory([])
    setConversationHistory([])
    setProactiveTriggered(false)
    setSessionLoaded(false)
    queryClient.removeQueries({ queryKey: chatCacheKey(dealId) })
    try { if (typeof window !== 'undefined') localStorage.removeItem(`parity_chat_${dealId}`) } catch (e) { /* ignore */ }
  }, [dealId, queryClient])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); doAsk() }
  }

  const copyToClipboard = (text: string, idx: number) => {
    // Strip HTML/markdown for clean paste
    const clean = text
      .replace(/\*\*/g, '')
      .replace(/^## /gm, '')
      .replace(/^### /gm, '')
      .replace(/^---$/gm, '---')
      .replace(/[📊💡🏦📈📉⚠️✅❌🔍💰📋🏢📌🔎💼📁📂🗂️📄📃📑🔔🔕]/gu, '')
      .trim()
    navigator.clipboard.writeText(clean)
    setCopiedIdx(idx)
    setTimeout(() => setCopiedIdx(null), 2000)
  }

  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      {/* Left: Chat area */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--t1)', letterSpacing: '0.02em' }}>Parity Review</span>
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: '0.12em', padding: '2px 8px', borderRadius: 3,
            background: effectiveCorpusReady ? 'rgba(74,222,128,0.12)' : 'rgba(20,184,166,0.12)',
            color: effectiveCorpusReady ? 'var(--green)' : '#818CF8',
            border: `1px solid ${effectiveCorpusReady ? 'rgba(74,222,128,0.25)' : 'rgba(20,184,166,0.25)'}`,
          }}>
            {effectiveCorpusReady ? 'READY' : isCheckingAnalysis ? 'CHECKING' : 'PENDING'}
          </span>
          {chatHistory.length > 0 && (
            <button
              onClick={handleClearChat}
              style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--t2)', background: 'transparent', border: '1px solid var(--b1)', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.06em' }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--red)'; (e.currentTarget as HTMLElement).style.color = 'var(--red)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--b1)'; (e.currentTarget as HTMLElement).style.color = 'var(--t2)'; }}
            >
              CLEAR CHAT
            </button>
          )}
        </div>

        {/* Corpus description card */}
        {!effectiveCorpusReady && isCheckingAnalysis && (
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: '14px 18px', marginBottom: 16 }}>
            <AnalystStatus stage="checking" size={16} />
          </div>
        )}
        {!effectiveCorpusReady && !isCheckingAnalysis && (
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: '14px 18px', marginBottom: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--t2)', lineHeight: 1.6 }}>
              Parity Intelligence is available once analysis completes. Run analysis from the Documents tab to activate.
            </div>
          </div>
        )}
        {effectiveCorpusReady && chatHistory.length === 0 && !loading && (
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: '14px 18px', marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>CORPUS LOADED</div>
            <div style={{ fontSize: 12, color: 'var(--t2)', lineHeight: 1.6 }}>
              {effectiveTxnTotal > 0 ? `${effectiveTxnTotal} transactions` : 'Transactions'} across {effectiveStatementCount || 1} statement{effectiveStatementCount !== 1 ? 's' : ''} indexed. Ask any question about this borrower&apos;s financial history.
            </div>
          </div>
        )}

        {/* Chat history */}
        <div ref={scrollRef} style={{ maxHeight: 500, overflowY: 'auto', marginBottom: 16 }}>
          {chatHistory.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {chatHistory.map((msg, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: msg.role === 'analyst' ? 'flex-end' : 'flex-start' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: msg.role === 'analyst' ? 'var(--accent)' : 'var(--green)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace" }}>
                      {msg.role === 'analyst' ? 'ANALYST' : 'PARITY'}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--b1)', fontFamily: "'IBM Plex Mono', monospace" }}>{msg.time}</span>
                  </div>
                  <div style={{
                    maxWidth: '85%', position: 'relative',
                    background: msg.role === 'analyst' ? 'rgba(20,184,166,0.1)' : 'var(--s1)',
                    border: `1px solid ${msg.role === 'analyst' ? 'rgba(20,184,166,0.2)' : 'var(--b1)'}`,
                    borderRadius: msg.role === 'analyst' ? '8px 8px 2px 8px' : '8px 8px 8px 2px',
                    padding: '10px 14px',
                  }}>
                    {msg.role === 'parity' ? (
                      <>
                        <div style={{ fontSize: 13, color: 'var(--t1)', lineHeight: 1.6, userSelect: 'text' }} dangerouslySetInnerHTML={{ __html: mdToHtml(msg.text) }} />
                        <button
                          onClick={(e) => { e.stopPropagation(); copyToClipboard(msg.text, i) }}
                          style={{
                            position: 'absolute', top: 6, right: 6, padding: '3px 8px',
                            background: copiedIdx === i ? 'rgba(74,222,128,0.15)' : 'rgba(20,184,166,0.08)',
                            border: `1px solid ${copiedIdx === i ? 'rgba(74,222,128,0.3)' : 'var(--b1)'}`,
                            borderRadius: 3, fontSize: 9, fontWeight: 600, cursor: 'pointer',
                            color: copiedIdx === i ? 'var(--green)' : 'var(--t2)',
                            fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.06em',
                          }}
                        >
                          {copiedIdx === i ? 'COPIED' : 'COPY'}
                        </button>
                      </>
                    ) : (
                      <p style={{ fontSize: 13, color: 'var(--accent)', lineHeight: 1.6, whiteSpace: 'pre-line', margin: 0, userSelect: 'text' }}>{msg.text}</p>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                  <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--green)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace" }}>PARITY</span>
                  <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: '8px 8px 8px 2px', padding: '10px 14px' }}>
                    <AnalystStatus stage="generic" size={16} />
                  </div>
                </div>
              )}
            </div>
          )}
          {chatHistory.length === 0 && loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--green)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace" }}>PARITY</span>
              <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: '8px 8px 8px 2px', padding: '10px 14px' }}>
                <AnalystStatus stage="generic" size={16} />
              </div>
            </div>
          )}
        </div>

        {/* Suggestion chips */}
        {effectiveCorpusReady && chatHistory.length <= 1 && !loading && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
            {SUGGESTION_CHIPS.map((chip) => (
              <button
                key={chip}
                onClick={() => { setQuestion(chip); }}
                style={{ padding: '5px 12px', background: 'transparent', border: '1px solid var(--b1)', borderRadius: 20, fontSize: 11, color: 'var(--t2)', cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif", transition: 'all 0.15s' }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'; (e.currentTarget as HTMLElement).style.color = 'var(--accent)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--b1)'; (e.currentTarget as HTMLElement).style.color = 'var(--t2)'; }}
              >
                {chip}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 14 }}>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              effectiveCorpusReady
                ? "Ask anything about this borrower's financials..."
                : isCheckingAnalysis
                ? 'Checking analysis status…'
                : 'Run analysis first to enable Parity Review...'
            }
            disabled={!effectiveCorpusReady || loading}
            rows={2}
            style={{ width: '100%', background: 'transparent', border: 'none', outline: 'none', padding: 0, fontSize: 13, color: 'var(--t1)', resize: 'none', fontFamily: "'IBM Plex Sans', sans-serif", boxSizing: 'border-box', opacity: !effectiveCorpusReady ? 0.4 : 1 }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10, gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: 'var(--b1)', fontFamily: "'IBM Plex Mono', monospace" }}>ctrl+enter to send</span>
            <button
              onClick={() => void doAsk()}
              disabled={!effectiveCorpusReady || loading || !question.trim()}
              style={{ padding: '7px 16px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 5, fontSize: 12, fontWeight: 600, cursor: !effectiveCorpusReady || loading || !question.trim() ? 'not-allowed' : 'pointer', opacity: !effectiveCorpusReady || loading || !question.trim() ? 0.4 : 1, fontFamily: "'IBM Plex Sans', sans-serif" }}
            >
              {loading ? 'Computing...' : 'Send'}
            </button>
          </div>
        </div>
      </div>

      {/* Right sidebar is rendered by the parent — we only own the chat column */}
    </div>
  )
}

export default memo(ParityReviewChat)
