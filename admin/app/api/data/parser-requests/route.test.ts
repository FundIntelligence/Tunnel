import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const autoRows = [
  { id: 'a1', partner: 'musa', bank_name: 'KCB', status: 'pending', requested_at: '2026-07-01T00:00:00Z' },
]
const manualRows = [
  { id: 'm1', bank_name: 'Stanbic', original_filename: 'stanbic.pdf', created_at: '2026-07-02T00:00:00Z' },
]

function makeQuery(table: 'parser_requests' | 'pds_parser_requests') {
  const rows = table === 'parser_requests' ? autoRows : manualRows
  return {
    select: vi.fn().mockReturnThis(),
    order: vi.fn().mockResolvedValue({ data: rows, error: null }),
    update: vi.fn().mockReturnThis(),
    eq: vi.fn().mockResolvedValue({ error: null }),
  }
}

const fromMock = vi.fn((table: string) => makeQuery(table as 'parser_requests' | 'pds_parser_requests'))
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({ from: fromMock }),
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

describe('GET /api/data/parser-requests', () => {
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

  it('queries both parser_requests (auto) and pds_parser_requests (manual)', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    const body = await res.json()

    expect(fromMock).toHaveBeenCalledWith('parser_requests')
    expect(fromMock).toHaveBeenCalledWith('pds_parser_requests')
    expect(body).toEqual({ auto: autoRows, manual: manualRows })
  })

  it('returns 500 if the auto (parser_requests) query errors', async () => {
    fromMock.mockImplementationOnce(() => ({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockResolvedValue({ data: null, error: { message: 'auto boom' } }),
      update: vi.fn().mockReturnThis(),
      eq: vi.fn().mockResolvedValue({ error: null }),
    }))
    fromMock.mockImplementationOnce(() => makeQuery('pds_parser_requests'))

    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(500)
    expect(await res.json()).toEqual({ error: 'auto boom' })
  })

  it('returns 500 if the manual (pds_parser_requests) query errors', async () => {
    fromMock.mockImplementationOnce(() => makeQuery('parser_requests'))
    fromMock.mockImplementationOnce(() => ({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockResolvedValue({ data: null, error: { message: 'manual boom' } }),
      update: vi.fn().mockReturnThis(),
      eq: vi.fn().mockResolvedValue({ error: null }),
    }))

    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(500)
    expect(await res.json()).toEqual({ error: 'manual boom' })
  })
})

describe('PATCH /api/data/parser-requests', () => {
  beforeEach(() => {
    fromMock.mockClear()
    requireAdminSessionMock.mockClear()
    requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))
  })

  it('returns 401 and never queries supabase when there is no session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { PATCH } = await import('./route')
    const res = await PATCH(new Request('http://x', { method: 'PATCH', body: JSON.stringify({ id: 'a1', status: 'done' }) }) as never)
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('updates parser_requests when authenticated', async () => {
    const { PATCH } = await import('./route')
    const res = await PATCH(new Request('http://x', { method: 'PATCH', body: JSON.stringify({ id: 'a1', status: 'done' }) }) as never)
    expect(fromMock).toHaveBeenCalledWith('parser_requests')
    expect(await res.json()).toEqual({ ok: true })
  })
})
