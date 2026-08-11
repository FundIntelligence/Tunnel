import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const deal = { id: 'd1', name: 'Deal One' }
const documents = [{ id: 'doc1', deal_id: 'd1' }]
const runs = [{ id: 'run1', deal_id: 'd1' }]

function makeQuery(table: string) {
  if (table === 'pds_deals') {
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      single: vi.fn().mockResolvedValue({ data: deal, error: null }),
    }
  }
  const data = table === 'pds_documents' ? documents : runs
  return {
    select: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    order: vi.fn().mockResolvedValue({ data, error: null }),
  }
}

const fromMock = vi.fn((table: string) => makeQuery(table))
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({ from: fromMock }),
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

const params = Promise.resolve({ id: 'd1' })

describe('GET /api/data/deals/[id]', () => {
  beforeEach(() => {
    fromMock.mockClear()
    requireAdminSessionMock.mockClear()
    requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))
  })

  it('returns 401 and never queries supabase when there is no session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { GET } = await import('./route')
    const res = await GET(new Request('http://x') as never, { params })
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns the deal with documents and runs when authenticated', async () => {
    const { GET } = await import('./route')
    const res = await GET(new Request('http://x') as never, { params })
    expect(await res.json()).toEqual({ deal, documents, runs })
  })
})
