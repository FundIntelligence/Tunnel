import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const fromMock = vi.fn()
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'weevermbakaya@gmail.com' }))

vi.mock('@/lib/supabase-staging', () => ({
  getSupabaseStaging: () => ({ from: fromMock }),
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

const params = Promise.resolve({ id: 'd1' })

describe('GET /api/data/ontology-qa/[id]', () => {
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
    const res = await GET(new Request('http://x') as never, { params })
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns 403 and never queries supabase when the email is not ontology-qa allowlisted', async () => {
    requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))
    const { GET } = await import('./route')
    const res = await GET(new Request('http://x') as never, { params })
    expect(res.status).toBe(403)
    expect(fromMock).not.toHaveBeenCalled()
  })
})
