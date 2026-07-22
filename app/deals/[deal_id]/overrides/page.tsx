'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { createBrowserClient } from '@/lib/supabase'
import { getNeedsReviewTransactions, resolveTransaction, OVERRIDE_REASON_OPTIONS } from '@/lib/v1-api'
import type { NeedsReviewTransaction, OverrideReasonCategory } from '@/lib/v1-api'

const ROLES: { value: string; label: string }[] = [
  { value: 'revenue_operational', label: 'Revenue: Operational' },
  { value: 'revenue_investment', label: 'Revenue: Investment' },
  { value: 'mpesa_inflow', label: 'M-Pesa Inflow' },
  { value: 'loan_inflow', label: 'Loan Inflow' },
  { value: 'equity_inflow', label: 'Equity Inflow' },
  { value: 'fund_inflow', label: 'Fund Inflow' },
  { value: 'supplier_payment', label: 'Supplier Payment' },
  { value: 'payroll', label: 'Payroll' },
  { value: 'tax', label: 'Tax Payment' },
  { value: 'loan_repayment', label: 'Loan Repayment' },
  { value: 'capital_transfer', label: 'Capital Transfer' },
  { value: 'related_party_transfer', label: 'Related Party Transfer' },
  { value: 'owner_withdrawal', label: 'Owner Withdrawal' },
  { value: 'utility_payment', label: 'Utility Payment' },
  { value: 'rent_payment', label: 'Rent Payment' },
  { value: 'insurance_payment', label: 'Insurance Payment' },
  { value: 'legal_professional', label: 'Legal/Professional Fees' },
  { value: 'bank_charges', label: 'Bank Charges' },
  { value: 'interest_income', label: 'Interest Income' },
  { value: 'cash_deposit', label: 'Cash Deposit' },
  { value: 'cash_withdrawal', label: 'Cash Withdrawal' },
  { value: 'internal_transfer', label: 'Internal Transfer' },
  { value: 'pos_settlement', label: 'POS Settlement' },
  { value: 'reversal', label: 'Reversal' },
]

function formatAmount(cents: number): string {
  const abs = Math.abs(cents)
  const formatted = (abs / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return cents < 0 ? `-${formatted}` : `+${formatted}`
}

interface RowState {
  selectedRole: string
  selectedReason: OverrideReasonCategory | ''
  reasonNote: string
  resolving: boolean
  resolved: boolean
  error: string
}

export default function OverridesPage() {
  const router = useRouter()
  const params = useParams()
  const dealId = params['deal_id'] as string

  const [authChecked, setAuthChecked] = useState(false)
  const [analystInitials, setAnalystInitials] = useState('AM')
  const [transactions, setTransactions] = useState<NeedsReviewTransaction[]>([])
  const [rowStates, setRowStates] = useState<Record<string, RowState>>({})
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState('')

  // Auth guard
  useEffect(() => {
    const supabase = createBrowserClient()
    if (!supabase) { router.replace('/login'); return }
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return }
      // Try to get analyst initials from session metadata
      const initials = (session.user.user_metadata?.analyst_initials as string) || ''
      if (initials) setAnalystInitials(initials.slice(0, 3).toUpperCase())
      setAuthChecked(true)
    })
  }, [router])

  // Fetch needs_review transactions
  useEffect(() => {
    if (!authChecked || !dealId) return
    setLoading(true)
    getNeedsReviewTransactions(dealId)
      .then(({ transactions: txns }) => {
        setTransactions(txns)
        const initial: Record<string, RowState> = {}
        for (const t of txns) {
          initial[t.row_id] = { selectedRole: ROLES[0].value, selectedReason: '', reasonNote: '', resolving: false, resolved: false, error: '' }
        }
        setRowStates(initial)
      })
      .catch((err) => setFetchError(err?.message || 'Failed to load transactions'))
      .finally(() => setLoading(false))
  }, [authChecked, dealId])

  const resolvedCount = Object.values(rowStates).filter((s) => s.resolved).length
  const total = transactions.length
  const allDone = total > 0 && resolvedCount === total

  // Auto-redirect when everything resolved
  useEffect(() => {
    if (allDone) {
      const t = setTimeout(() => router.push(`/deals/${dealId}/review`), 800)
      return () => clearTimeout(t)
    }
  }, [allDone, dealId, router])

  const handleRoleChange = useCallback((rowId: string, role: string) => {
    setRowStates((prev) => ({ ...prev, [rowId]: { ...prev[rowId], selectedRole: role, error: '' } }))
  }, [])

  const handleReasonChange = useCallback((rowId: string, reason: OverrideReasonCategory) => {
    setRowStates((prev) => ({ ...prev, [rowId]: { ...prev[rowId], selectedReason: reason, error: '' } }))
  }, [])

  const handleReasonNoteChange = useCallback((rowId: string, note: string) => {
    setRowStates((prev) => ({ ...prev, [rowId]: { ...prev[rowId], reasonNote: note, error: '' } }))
  }, [])

  const handleResolve = useCallback(async (txn: NeedsReviewTransaction) => {
    const state = rowStates[txn.row_id]
    if (!state || state.resolved || state.resolving) return
    if (!state.selectedReason) {
      setRowStates((prev) => ({ ...prev, [txn.row_id]: { ...prev[txn.row_id], error: 'Select a reason before resolving.' } }))
      return
    }
    if (state.selectedReason === 'other' && !state.reasonNote.trim()) {
      setRowStates((prev) => ({ ...prev, [txn.row_id]: { ...prev[txn.row_id], error: "Reason note is required for 'Other'." } }))
      return
    }
    setRowStates((prev) => ({ ...prev, [txn.row_id]: { ...prev[txn.row_id], resolving: true, error: '' } }))
    try {
      await resolveTransaction(dealId, txn.row_id, state.selectedRole, analystInitials, state.selectedReason, state.reasonNote)
      setRowStates((prev) => ({ ...prev, [txn.row_id]: { ...prev[txn.row_id], resolving: false, resolved: true } }))
    } catch (err: any) {
      setRowStates((prev) => ({
        ...prev,
        [txn.row_id]: { ...prev[txn.row_id], resolving: false, error: err?.message || 'Failed' },
      }))
    }
  }, [rowStates, dealId, analystInitials])

  if (!authChecked || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)' }}>
        <div className="w-8 h-8 rounded-full border-2 border-teal-500 border-t-transparent animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg)' }}>
      {/* Top bar */}
      <div className="border-b px-6 py-4" style={{ borderColor: 'rgba(20,184,166,0.15)', background: 'var(--s1)' }}>
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <div className="text-xs font-medium tracking-widest uppercase" style={{ color: 'var(--accent)', fontFamily: 'IBM Plex Mono, monospace' }}>
              PARITY · OVERRIDE GATE
            </div>
            <h1 className="text-lg font-bold mt-0.5" style={{ color: 'var(--t0)' }}>Needs Review</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs" style={{ color: 'var(--t2)' }}>Analyst</span>
            <input
              value={analystInitials}
              onChange={(e) => setAnalystInitials(e.target.value.slice(0, 3).toUpperCase())}
              maxLength={3}
              className="w-14 px-2 py-1 rounded text-xs text-center uppercase font-mono outline-none"
              style={{ background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.3)', color: 'var(--accent)' }}
            />
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6 space-y-5">
        {/* Progress banner */}
        {total > 0 && (
          <div className="rounded-xl p-5" style={{ background: 'var(--s1)', border: '1px solid rgba(20,184,166,0.2)' }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium" style={{ color: 'var(--t0)' }}>
                {allDone ? '✓ All resolved — redirecting…' : `${resolvedCount} of ${total} resolved`}
              </span>
              <span className="text-xs font-mono" style={{ color: 'var(--t2)' }}>
                {total - resolvedCount} remaining
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(20,184,166,0.15)' }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: total > 0 ? `${(resolvedCount / total) * 100}%` : '0%',
                  background: allDone ? 'var(--green)' : 'var(--accent)',
                }}
              />
            </div>
          </div>
        )}

        {/* Error state */}
        {fetchError && (
          <div className="p-4 rounded-xl text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)', color: 'var(--red)' }}>
            {fetchError}
          </div>
        )}

        {/* Empty state */}
        {!fetchError && total === 0 && (
          <div className="rounded-xl p-10 text-center" style={{ background: 'var(--s1)', border: '1px solid rgba(20,184,166,0.2)' }}>
            <div className="text-3xl mb-3">✓</div>
            <p className="text-sm font-medium" style={{ color: 'var(--t0)' }}>No transactions need review</p>
            <p className="text-xs mt-1" style={{ color: 'var(--t2)' }}>All transactions have been classified automatically.</p>
            <button
              onClick={() => router.push(`/deals/${dealId}/review`)}
              className="mt-4 px-4 py-2 rounded-lg text-sm font-medium"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              Continue to Review
            </button>
          </div>
        )}

        {/* Transaction rows */}
        {transactions.length > 0 && (
          <div className="rounded-xl overflow-hidden" style={{ border: '1px solid rgba(20,184,166,0.2)' }}>
            {/* Table header */}
            <div
              className="grid text-xs font-medium px-4 py-2.5"
              style={{
                gridTemplateColumns: '100px 1fr 110px 220px 100px',
                background: 'var(--s2)',
                color: 'var(--t2)',
                borderBottom: '1px solid rgba(20,184,166,0.15)',
              }}
            >
              <span>Date</span>
              <span>Description</span>
              <span className="text-right">Amount</span>
              <span className="pl-3">Assign role</span>
              <span />
            </div>

            {transactions.map((txn, idx) => {
              const state = rowStates[txn.row_id]
              if (!state) return null
              const isCredit = txn.signed_amount_cents > 0
              const isLast = idx === transactions.length - 1

              return (
                <div
                  key={txn.row_id}
                  className="grid items-center px-4 py-3 transition-colors"
                  style={{
                    gridTemplateColumns: '100px 1fr 110px 220px 100px',
                    background: state.resolved ? 'rgba(34,197,94,0.04)' : idx % 2 === 0 ? 'var(--s1)' : 'var(--s2)',
                    borderBottom: isLast ? 'none' : '1px solid rgba(20,184,166,0.1)',
                    opacity: state.resolved ? 0.65 : 1,
                  }}
                >
                  {/* Date */}
                  <span className="text-xs font-mono" style={{ color: 'var(--t1)' }}>
                    {txn.txn_date || '—'}
                  </span>

                  {/* Description + entity */}
                  <div className="min-w-0 pr-4">
                    <p className="text-xs truncate" style={{ color: 'var(--t0)' }}>
                      {txn.description || '—'}
                    </p>
                    {txn.entity_name && (
                      <p className="text-xs truncate mt-0.5" style={{ color: 'var(--t2)' }}>{txn.entity_name}</p>
                    )}
                  </div>

                  {/* Amount */}
                  <span
                    className="text-xs font-mono text-right"
                    style={{ color: isCredit ? 'var(--green)' : 'var(--red)' }}
                  >
                    {formatAmount(txn.signed_amount_cents)}
                  </span>

                  {/* Role + reason */}
                  <div className="pl-3 space-y-1.5">
                    {state.resolved ? (
                      <span className="text-xs font-medium" style={{ color: 'var(--green)' }}>
                        ✓ {ROLES.find((r) => r.value === state.selectedRole)?.label ?? state.selectedRole}
                      </span>
                    ) : (
                      <>
                        <select
                          value={state.selectedRole}
                          onChange={(e) => handleRoleChange(txn.row_id, e.target.value)}
                          disabled={state.resolving}
                          className="w-full text-xs rounded px-2 py-1.5 outline-none"
                          style={{
                            background: 'var(--s2)',
                            border: '1px solid rgba(20,184,166,0.3)',
                            color: 'var(--t0)',
                          }}
                        >
                          {ROLES.map((r) => (
                            <option key={r.value} value={r.value}>{r.label}</option>
                          ))}
                        </select>
                        <select
                          value={state.selectedReason}
                          onChange={(e) => handleReasonChange(txn.row_id, e.target.value as OverrideReasonCategory)}
                          disabled={state.resolving}
                          className="w-full text-xs rounded px-2 py-1.5 outline-none"
                          style={{
                            background: 'var(--s2)',
                            border: `1px solid ${state.selectedReason ? 'rgba(20,184,166,0.3)' : 'var(--amber)'}`,
                            color: 'var(--t0)',
                          }}
                        >
                          <option value="">Reason…</option>
                          {OVERRIDE_REASON_OPTIONS.map((r) => (
                            <option key={r.value} value={r.value}>{r.label}</option>
                          ))}
                        </select>
                        {state.selectedReason === 'other' && (
                          <input
                            type="text"
                            value={state.reasonNote}
                            onChange={(e) => handleReasonNoteChange(txn.row_id, e.target.value)}
                            placeholder="Reason note (required)"
                            className="w-full text-xs rounded px-2 py-1.5 outline-none"
                            style={{
                              background: 'var(--s2)',
                              border: '1px solid rgba(20,184,166,0.3)',
                              color: 'var(--t0)',
                            }}
                          />
                        )}
                      </>
                    )}
                    {state.error && (
                      <p className="text-xs mt-1" style={{ color: 'var(--red)' }}>{state.error}</p>
                    )}
                  </div>

                  {/* Resolve button */}
                  <div className="flex justify-end">
                    {state.resolved ? (
                      <span className="text-base" style={{ color: 'var(--green)' }}>✓</span>
                    ) : (
                      <button
                        onClick={() => handleResolve(txn)}
                        disabled={state.resolving}
                        className="px-3 py-1.5 rounded text-xs font-medium transition-opacity"
                        style={{ background: 'var(--accent)', color: '#fff', opacity: state.resolving ? 0.6 : 1 }}
                      >
                        {state.resolving ? (
                          <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                          </svg>
                        ) : 'Resolve'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Skip / continue */}
        {total > 0 && !allDone && (
          <div className="flex justify-end">
            <button
              onClick={() => router.push(`/deals/${dealId}/review`)}
              className="text-xs"
              style={{ color: 'var(--t2)' }}
            >
              Skip to review →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
