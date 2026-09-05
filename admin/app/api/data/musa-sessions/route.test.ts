import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const rows = [{ id: 's1', created_at: '2026-07-01T00:00:00Z', document_urls: ['https://example.com/statement.pdf'] }]

const queryMock = {
  select: vi.fn().mockReturnThis(),
  order: vi.fn().mockReturnThis(),
  limit: vi.fn().mockResolvedValue({ data: rows, error: null }),
}
const fromMock = vi.fn(() => queryMock)
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({ from: fromMock }),
  SUPABASE_ENV: 'prod',
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

describe('GET /api/data/musa-sessions', () => {
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
    const res = await GET()
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns musa_sessions data when authenticated', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    expect(fromMock).toHaveBeenCalledWith('musa_sessions')
    expect(await res.json()).toEqual(rows)
  })

  it('sets the x-data-environment header to prod (PAR-181)', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.headers.get('x-data-environment')).toBe('prod')
  })
})
