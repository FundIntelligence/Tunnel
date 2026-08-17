import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const rows = [{ id: 'd1', currency: 'KES', created_at: '2026-07-01T00:00:00Z' }]

const queryMock = {
  select: vi.fn().mockReturnThis(),
  order: vi.fn().mockReturnThis(),
  limit: vi.fn().mockResolvedValue({ data: rows, error: null }),
}
const fromMock = vi.fn(() => queryMock)
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'weevermbakaya@gmail.com' }))

vi.mock('@/lib/supabase-staging', () => ({
  getSupabaseStaging: () => ({ from: fromMock }),
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

describe('GET /api/data/ontology-qa', () => {
  beforeEach(() => {
    fromMock.mockClear()
    requireAdminSessionMock.mockClear()
    requireAdminSessionMock.mockImplementation(async () => ({ email: 'weevermbakaya@gmail.com' }))
  })

  it('returns 401 and never queries supabase when there is no session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns 403 and never queries supabase when the email is not ontology-qa allowlisted', async () => {
    requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(403)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns deals data for an ontology-qa allowlisted session', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    const body = await res.json()
    expect(fromMock).toHaveBeenCalledWith('pds_deals')
    expect(body.deals).toEqual(rows)
  })
})
