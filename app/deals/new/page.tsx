'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { createBrowserClient } from '@/lib/supabase'
import { createDeal } from '@/lib/v1-api'

export default function NewDealPage() {
  const router = useRouter()
  const [dealName, setDealName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [authChecked, setAuthChecked] = useState(false)

  useEffect(() => {
    const supabase = createBrowserClient()
    if (!supabase) { router.replace('/login'); return }
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) router.replace('/login')
      else setAuthChecked(true)
    })
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!dealName.trim() || !companyName.trim()) {
      setError('All fields are required.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const { deal } = await createDeal('KES', dealName.trim(), undefined, companyName.trim())
      router.push(`/v1/deal?deal_id=${deal.id}`)
    } catch (err: any) {
      setError(err?.message || 'Failed to create deal. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg)' }}>
        <div className="w-8 h-8 rounded-full border-2 border-teal-500 border-t-transparent animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'var(--bg)' }}>
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="mb-8">
          <div className="text-xs font-medium tracking-widest uppercase mb-1" style={{ color: 'var(--accent)', fontFamily: 'IBM Plex Mono, monospace' }}>
            PARITY
          </div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--t0)' }}>New Deal</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--t2)' }}>
            Set up a new deal workspace to start uploading statements.
          </p>
        </div>

        <div
          className="rounded-xl p-8"
          style={{ background: 'var(--s1)', border: '1px solid rgba(20,184,166,0.2)' }}
        >
          {error && (
            <div className="mb-5 p-3 rounded-lg text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)', color: 'var(--red)' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--t1)' }}>
                Deal name <span style={{ color: 'var(--red)' }}>*</span>
              </label>
              <input
                type="text"
                value={dealName}
                onChange={(e) => setDealName(e.target.value)}
                required
                placeholder="Q1 2026 Deal Pipeline"
                className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-colors"
                style={{ background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.25)', color: 'var(--t0)' }}
              />
            </div>

            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--t1)' }}>
                Company name <span style={{ color: 'var(--red)' }}>*</span>
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                required
                placeholder="Acme Manufacturing Ltd"
                className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-colors"
                style={{ background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.25)', color: 'var(--t0)' }}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-lg font-semibold text-sm transition-opacity mt-2"
              style={{ background: 'var(--accent)', color: '#fff', opacity: loading ? 0.7 : 1 }}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Creating deal...
                </span>
              ) : (
                'Create Deal'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
