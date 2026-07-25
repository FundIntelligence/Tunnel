'use client'

import { useState, useEffect, useCallback, memo } from 'react'
import { getNeedsReview, resolveTransaction, OVERRIDE_REASON_OPTIONS, type NeedsReviewItem, type OverrideReasonCategory } from '@/lib/v1-api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const ROLE_OPTIONS = [
  { value: 'supplier', label: 'Supplier', color: 'var(--accent)' },
  { value: 'revenue_operational', label: 'Revenue (Operational)', color: 'var(--green)' },
  { value: 'revenue_non_operational', label: 'Revenue (Non-operational)', color: 'var(--green)' },
  { value: 'payroll', label: 'Payroll', color: 'var(--amber)' },
  { value: 'loan_repayment', label: 'Loan Repayment', color: 'var(--red)' },
  { value: 'tax', label: 'Tax / KRA', color: 'var(--amber)' },
  // PAR-89: these 3 used to send values ('intercompany', 'owner_draw', 'ignore')
  // that don't exist in backend _VALID_OVERRIDE_ROLES (api.py), so every resolve
  // attempt with them 400'd. Renamed to the backend's existing equivalent roles
  // rather than adding new backend roles — each concept already has a role with
  // real downstream meaning (related_party_transfer/owner_withdrawal feed
  // reconciliation/suggestions logic; 'other' is already the excluded/uncategorized
  // catch-all), so a second, UI-only role would just fragment the same concept.
  { value: 'related_party_transfer', label: 'Intercompany / Related Party', color: '#818CF8' },
  { value: 'owner_withdrawal', label: 'Owner Draw / Withdrawal', color: '#E879F9' },
  { value: 'other', label: 'Ignore / Not relevant', color: 'var(--t2)' },
]

function formatCents(c: number): string {
  return (c / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
}

interface Props {
  dealId: string
  analystInitials: string
  onQueueUpdate?: (remaining: number) => void
}

function ReviewQueue({ dealId, analystInitials, onQueueUpdate }: Props) {
  const [items, setItems] = useState<NeedsReviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [activeItemId, setActiveItemId] = useState<string | null>(null)
  const [selectedRole, setSelectedRole] = useState('supplier')
  const [selectedReason, setSelectedReason] = useState<OverrideReasonCategory | ''>('')
  const [reasonNote, setReasonNote] = useState('')
  const [resolving, setResolving] = useState(false)
  const [resolvedCount, setResolvedCount] = useState(0)
  const [bulkMode, setBulkMode] = useState(true)
  const [bulkSelected, setBulkSelected] = useState<Set<string>>(new Set())
  const [bulkRole, setBulkRole] = useState('supplier')
  const [bulkReason, setBulkReason] = useState<OverrideReasonCategory | ''>('')
  const [bulkReasonNote, setBulkReasonNote] = useState('')
  const [bulkResolving, setBulkResolving] = useState(false)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const queryClient = useQueryClient()

  // useQuery: use object form to satisfy newer react-query typings
  const { data, isLoading, isFetching, refetch, error: queryError } = useQuery<{ transactions: NeedsReviewItem[]; total: number }, Error>({
    queryKey: ['needsReview', dealId],
    queryFn: () => getNeedsReview(dealId),
    staleTime: 2 * 60 * 1000,
  })

  useEffect(() => {
    if (queryError) setError(queryError.message || 'Failed to load review queue')
  }, [queryError])

  useEffect(() => {
    if (data) {
      setItems(data?.transactions ?? [])
      setTotal(data?.total ?? 0)
      onQueueUpdate?.(data?.total ?? 0)
    }
  }, [data, onQueueUpdate])

  // PAR-50: search by description/amount, filter by date range. The ticket also
  // scoped "bank" and "flag reason" filters, but neither field is actually
  // returned by GET /transactions/needs-review (NeedsReviewItem has no bank
  // field at all, and flag_reason is optional/unpopulated in practice) — the
  // ticket's own note says "whatever fields the queue already exposes", so
  // those two are left out rather than filtering on data that isn't there.
  const searchLower = search.trim().toLowerCase()
  const filteredItems = items.filter((item) => {
    if (dateFrom && String(item.txn_date) < dateFrom) return false
    if (dateTo && String(item.txn_date) > dateTo) return false
    if (!searchLower) return true
    const desc = ((item.entity_name || item.description || '') as string).toLowerCase()
    const amountStr = (Math.abs(Number(item.signed_amount_cents ?? 0)) / 100).toFixed(2)
    return desc.includes(searchLower) || amountStr.includes(searchLower)
  })

  // helper to toggle bulk selection
  const toggleBulkItem = useCallback((rowId: string) => {
    setBulkSelected(prev => {
      const next = new Set(prev)
      if (next.has(rowId)) next.delete(rowId)
      else next.add(rowId)
      return next
    })
  }, [])

  // useMutation: object form and typed generics
  const resolveMutation = useMutation<
    { success: boolean; remaining_count: number },
    Error,
    { rowId: string; newRole: string; reasonCategory: OverrideReasonCategory; reasonNote: string }
  >({
    mutationFn: async ({ rowId, newRole, reasonCategory, reasonNote: note }) => {
      try {
        return await resolveTransaction(dealId, rowId, newRole, analystInitials, reasonCategory, note)
      } catch (e) {
        // PAR-89 follow-up: export()'s delete-then-reinsert of pds_txn_entity_map
        // is not atomic, so a resolve can land in the brief window where the
        // deal's map rows are gone (mid re-export) and 404. That's a stale-queue
        // read, not a real "this transaction doesn't exist" — refetch to let the
        // window close, then retry exactly once before surfacing an error.
        if ((e as Error & { status?: number }).status === 404) {
          await refetch()
          return await resolveTransaction(dealId, rowId, newRole, analystInitials, reasonCategory, note)
        }
        throw e
      }
    },
    onMutate: async ({ rowId }) => {
      await queryClient.cancelQueries({ queryKey: ['needsReview', dealId] })
      const previous = queryClient.getQueryData<{ transactions: NeedsReviewItem[]; total: number }>(['needsReview', dealId])
      if (previous) {
        queryClient.setQueryData<{ transactions: NeedsReviewItem[]; total: number }>(['needsReview', dealId], {
          ...previous,
          transactions: previous.transactions.filter(t => String(t.row_id) !== rowId),
          total: Math.max(0, previous.total - 1),
        })
      }
      return { previous }
    },
    onError: (err: Error, vars, context) => {
      if ((context as any)?.previous) queryClient.setQueryData(['needsReview', dealId], (context as any).previous)
      setError(err.message)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['needsReview', dealId] })
    },
  })

  const handleResolve = async (rowId: string, newRole: string) => {
    if (!selectedReason) { setError('Select a reason before resolving.'); return }
    if (selectedReason === 'other' && !reasonNote.trim()) { setError("Reason note is required for 'Other'."); return }
    setResolving(true)
    try {
      await resolveMutation.mutateAsync({ rowId, newRole, reasonCategory: selectedReason, reasonNote })
      setResolvedCount(prev => prev + 1)
      setActiveItemId(null)
      setSelectedReason('')
      setReasonNote('')
    } catch (e) {
      // error handled in mutation
    } finally {
      setResolving(false)
    }
  }

  const handleBulkResolve = async () => {
    if (bulkSelected.size === 0) return
    if (!bulkReason) { setError('Select a reason before resolving.'); return }
    if (bulkReason === 'other' && !bulkReasonNote.trim()) { setError("Reason note is required for 'Other'."); return }
    setBulkResolving(true)
    const ids = Array.from(bulkSelected)
    for (const rowId of ids) {
      try {
        await resolveMutation.mutateAsync({ rowId, newRole: bulkRole, reasonCategory: bulkReason, reasonNote: bulkReasonNote })
      } catch {
        /* continue with others */
      }
    }
    setBulkSelected(new Set())
    setBulkReason('')
    setBulkReasonNote('')
    setBulkResolving(false)
  }

  if (isLoading || isFetching) {
    return (
      <div style={{ padding: '48px 0', textAlign: 'center' }}>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <div style={{ width: 24, height: 24, borderRadius: '50%', borderTop: '2px solid var(--accent)', borderRight: '2px solid transparent', animation: 'spin 0.8s linear infinite', margin: '0 auto 12px' }} />
        <div style={{ fontSize: 12, color: 'var(--t2)' }}>Loading review queue…</div>
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--t1)' }}>Review Queue</span>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)', padding: '2px 8px', borderRadius: 3 }}>
            {total} remaining
          </span>
          {resolvedCount > 0 && (
            <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.25)', padding: '2px 8px', borderRadius: 3 }}>
              {resolvedCount} resolved
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => { setBulkMode(!bulkMode); setBulkSelected(new Set()) }}
            style={{ padding: '5px 12px', background: bulkMode ? 'rgba(20,184,166,0.15)' : 'transparent', border: '1px solid var(--b1)', borderRadius: 5, fontSize: 11, color: bulkMode ? 'var(--accent)' : 'var(--t2)', cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
          >
            {bulkMode ? 'Cancel bulk' : 'Bulk resolve'}
          </button>
          <button
            onClick={() => refetch()}
            style={{ padding: '5px 12px', background: 'transparent', border: '1px solid var(--b1)', borderRadius: 5, fontSize: 11, color: 'var(--t2)', cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 6, padding: '10px 14px', marginBottom: 14, fontSize: 12, color: 'var(--red)' }}>
          {error}
        </div>
      )}

      {/* Bulk action bar */}
      {bulkMode && bulkSelected.size > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 16px', background: 'rgba(20,184,166,0.08)', border: '1px solid rgba(20,184,166,0.2)', borderRadius: 6, marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>{bulkSelected.size} selected</span>
            <span style={{ fontSize: 11, color: 'var(--t2)' }}>→ Classify as:</span>
            <select
              value={bulkRole}
              onChange={(e) => setBulkRole(e.target.value)}
              style={{ background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: 'var(--t1)', fontFamily: "'IBM Plex Sans', sans-serif" }}
            >
              {ROLE_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
            <span style={{ fontSize: 11, color: 'var(--t2)' }}>Reason:</span>
            <select
              value={bulkReason}
              onChange={(e) => setBulkReason(e.target.value as OverrideReasonCategory)}
              style={{ background: 'var(--s2)', border: `1px solid ${bulkReason ? 'var(--b1)' : 'var(--amber)'}`, borderRadius: 4, padding: '4px 8px', fontSize: 11, color: 'var(--t1)', fontFamily: "'IBM Plex Sans', sans-serif" }}
            >
              <option value="">Select reason…</option>
              {OVERRIDE_REASON_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
            <button
              onClick={handleBulkResolve}
              disabled={bulkResolving}
              style={{ padding: '5px 14px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 5, fontSize: 11, fontWeight: 600, cursor: bulkResolving ? 'not-allowed' : 'pointer', opacity: bulkResolving ? 0.6 : 1 }}
            >
              {bulkResolving ? 'Resolving…' : `Resolve ${bulkSelected.size}`}
            </button>
          </div>
          {bulkReason === 'other' && (
            <input
              type="text"
              value={bulkReasonNote}
              onChange={(e) => setBulkReasonNote(e.target.value)}
              placeholder="Reason note (required for 'Other')"
              style={{ background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '5px 8px', fontSize: 11, color: 'var(--t1)', fontFamily: "'IBM Plex Sans', sans-serif" }}
            />
          )}
        </div>
      )}

      {items.length === 0 && !(isLoading || isFetching) && (
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: 'var(--green)', fontWeight: 600, marginBottom: 6 }}>All clear</div>
          <div style={{ fontSize: 12, color: 'var(--t2)' }}>No items remaining in the review queue.</div>
        </div>
      )}

      {/* Search / filter */}
      {items.length > 0 && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search description or amount…"
            style={{ flex: 1, minWidth: 180, background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '6px 10px', fontSize: 12, color: 'var(--t0)', fontFamily: "'IBM Plex Sans', sans-serif" }}
          />
          <span style={{ fontSize: 11, color: 'var(--t2)' }}>From</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            style={{ background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '5px 8px', fontSize: 12, color: 'var(--t0)', fontFamily: "'IBM Plex Sans', sans-serif" }}
          />
          <span style={{ fontSize: 11, color: 'var(--t2)' }}>To</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            style={{ background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '5px 8px', fontSize: 12, color: 'var(--t0)', fontFamily: "'IBM Plex Sans', sans-serif" }}
          />
          {(search || dateFrom || dateTo) && (
            <button
              onClick={() => { setSearch(''); setDateFrom(''); setDateTo('') }}
              style={{ padding: '5px 10px', background: 'transparent', border: '1px solid var(--b1)', borderRadius: 4, fontSize: 11, color: 'var(--t2)', cursor: 'pointer' }}
            >
              Clear
            </button>
          )}
        </div>
      )}

      {items.length > 0 && filteredItems.length === 0 && (
        <div style={{ padding: '32px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 12, color: 'var(--t2)' }}>No items match your search/filter.</div>
        </div>
      )}

      {/* Items list */}
      <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
        {/* Column headers */}
        {filteredItems.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: bulkMode ? '32px 100px 1fr 70px 100px 120px' : '100px 1fr 70px 100px 120px', gap: 8, padding: '10px 16px', borderBottom: '1px solid var(--s3)' }}>
            {bulkMode && (
              <div
                style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
                onClick={() => {
                  if (bulkSelected.size === filteredItems.length) {
                    setBulkSelected(new Set())
                  } else {
                    setBulkSelected(new Set(filteredItems.map(i => i.row_id as string)))
                  }
                }}
              >
                <div style={{
                  width: 16, height: 16, borderRadius: 3,
                  border: `1px solid ${bulkSelected.size === filteredItems.length && filteredItems.length > 0 ? 'var(--accent)' : bulkSelected.size > 0 ? 'var(--accent)' : 'var(--b1)'}`,
                  background: bulkSelected.size === filteredItems.length && filteredItems.length > 0 ? 'var(--accent)' : bulkSelected.size > 0 ? 'rgba(20,184,166,0.3)' : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {bulkSelected.size === filteredItems.length && filteredItems.length > 0 && <span style={{ color: '#fff', fontSize: 10, lineHeight: 1 }}>✓</span>}
                  {bulkSelected.size > 0 && bulkSelected.size < filteredItems.length && <span style={{ color: '#fff', fontSize: 10, lineHeight: 1 }}>—</span>}
                </div>
              </div>
            )}
            {['DATE', 'DESCRIPTION', 'DR/CR', 'ROLE', 'AMOUNT'].map((h) => (
              <span key={h} style={{ fontSize: 9, fontWeight: 700, color: 'var(--b1)', letterSpacing: '0.1em' }}>{h}</span>
            ))}
          </div>
        )}

        {filteredItems.map((item) => {
          const rowId = item.row_id as string
          const isActive = activeItemId === rowId
          const amt = Math.abs(Number(item.signed_amount_cents ?? 0))
          const isNeg = Number(item.signed_amount_cents ?? 0) < 0

          return (
            <div key={rowId}>
              <div
                onClick={() => {
                  if (bulkMode) { toggleBulkItem(rowId); return }
                  setActiveItemId(isActive ? null : rowId)
                  setSelectedRole('supplier')
                  setSelectedReason('')
                  setReasonNote('')
                }}
                style={{
                  display: 'grid',
                  gridTemplateColumns: bulkMode ? '32px 100px 1fr 70px 100px 120px' : '100px 1fr 70px 100px 120px',
                  gap: 8, padding: '10px 16px', borderBottom: '1px solid var(--s3)', cursor: 'pointer',
                  background: isActive ? 'rgba(245,158,11,0.04)' : bulkSelected.has(rowId) ? 'rgba(20,184,166,0.06)' : 'transparent',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'rgba(20,184,166,0.04)' }}
                onMouseLeave={(e) => { if (!isActive && !bulkSelected.has(rowId)) e.currentTarget.style.background = 'transparent' }}
              >
                {bulkMode && (
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    <div style={{
                      width: 16, height: 16, borderRadius: 3,
                      border: `1px solid ${bulkSelected.has(rowId) ? 'var(--accent)' : 'var(--b1)'}`,
                      background: bulkSelected.has(rowId) ? 'var(--accent)' : 'transparent',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {bulkSelected.has(rowId) && <span style={{ color: '#fff', fontSize: 10, lineHeight: 1 }}>✓</span>}
                    </div>
                  </div>
                )}
                <span style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", display: 'flex', alignItems: 'center' }}>{item.txn_date as string}</span>
                <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', minWidth: 0 }}>
                  <span style={{ fontSize: 12, color: 'var(--amber)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {(item.entity_name || item.description) as string}
                  </span>
                  {item.flag_reason && (
                    <span style={{ fontSize: 10, color: 'var(--t2)', marginTop: 2 }}>{String(item.flag_reason)}</span>
                  )}
                </div>
                <span style={{ fontSize: 11, fontWeight: 700, color: isNeg ? 'var(--red)' : 'var(--green)', fontFamily: "'IBM Plex Mono', monospace", display: 'flex', alignItems: 'center' }}>{isNeg ? 'DR' : 'CR'}</span>
                <span style={{ fontSize: 10, color: 'var(--amber)', fontFamily: "'IBM Plex Mono', monospace", display: 'flex', alignItems: 'center' }}>needs_review</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: isNeg ? 'var(--red)' : 'var(--green)', fontFamily: "'IBM Plex Mono', monospace", textAlign: 'right', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
                  {formatCents(amt)}
                </span>
              </div>

              {/* Inline override panel */}
              {isActive && !bulkMode && (
                <div style={{ padding: '12px 16px 16px', background: 'rgba(245,158,11,0.03)', borderBottom: '1px solid var(--s3)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 10 }}>RECLASSIFY TRANSACTION</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                    {ROLE_OPTIONS.map((r) => (
                      <button
                        key={r.value}
                        onClick={(e) => { e.stopPropagation(); setSelectedRole(r.value) }}
                        style={{
                          padding: '5px 12px', borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                          background: selectedRole === r.value ? `${r.color}18` : 'transparent',
                          border: `1px solid ${selectedRole === r.value ? r.color : 'var(--b1)'}`,
                          color: selectedRole === r.value ? r.color : 'var(--t2)',
                          fontFamily: "'IBM Plex Sans', sans-serif",
                        }}
                      >
                        {r.label}
                      </button>
                    ))}
                  </div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 8 }}>REASON</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                    {OVERRIDE_REASON_OPTIONS.map((r) => (
                      <button
                        key={r.value}
                        onClick={(e) => { e.stopPropagation(); setSelectedReason(r.value) }}
                        style={{
                          padding: '5px 12px', borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                          background: selectedReason === r.value ? 'rgba(20,184,166,0.15)' : 'transparent',
                          border: `1px solid ${selectedReason === r.value ? 'var(--accent)' : 'var(--b1)'}`,
                          color: selectedReason === r.value ? 'var(--accent)' : 'var(--t2)',
                          fontFamily: "'IBM Plex Sans', sans-serif",
                        }}
                      >
                        {r.label}
                      </button>
                    ))}
                  </div>
                  {selectedReason === 'other' && (
                    <input
                      type="text"
                      value={reasonNote}
                      onChange={(e) => setReasonNote(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      placeholder="Reason note (required for 'Other')"
                      style={{ width: '100%', boxSizing: 'border-box', background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 4, padding: '6px 8px', fontSize: 11, color: 'var(--t1)', fontFamily: "'IBM Plex Sans', sans-serif", marginBottom: 12 }}
                    />
                  )}
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleResolve(rowId, selectedRole) }}
                      disabled={resolving || !selectedReason || (selectedReason === 'other' && !reasonNote.trim())}
                      style={{ padding: '7px 18px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 5, fontSize: 12, fontWeight: 600, cursor: resolving ? 'not-allowed' : 'pointer', opacity: (resolving || !selectedReason || (selectedReason === 'other' && !reasonNote.trim())) ? 0.5 : 1 }}
                    >
                      {resolving ? 'Saving…' : `Classify as ${ROLE_OPTIONS.find(r => r.value === selectedRole)?.label ?? selectedRole}`}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setActiveItemId(null) }}
                      style={{ padding: '7px 14px', background: 'transparent', border: '1px solid var(--b1)', borderRadius: 5, fontSize: 12, color: 'var(--t2)', cursor: 'pointer' }}
                    >
                      Cancel
                    </button>
                    <span style={{ fontSize: 10, color: 'var(--b1)', fontFamily: "'IBM Plex Mono', monospace", marginLeft: 'auto' }}>
                      {analystInitials}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Footer stats */}
      {items.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>
          <span>Showing {filteredItems.length} of {total} items</span>
          <span>Analyst: {analystInitials}</span>
        </div>
      )}
    </div>
  )
}

export default memo(ReviewQueue)
