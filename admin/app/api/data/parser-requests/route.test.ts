import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const autoRows = [
  { id: 'a1', partner: 'musa', bank_name: 'KCB', status: 'pending', requested_at: '2026-07-01T00:00:00Z', storage_path: null },
]
const manualRows = [
  { id: 'm1', bank_name: 'Stanbic', original_filename: 'stanbic.pdf', created_at: '2026-07-02T00:00:00Z', storage_path: 'm1/stanbic.pdf' },
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
const createSignedUrlMock = vi.fn(async (path: string) => ({
  data: { signedUrl: `https://staging.supabase.co/storage/v1/object/sign/parser-requests/${path}?token=fresh` },
  error: null,
}))

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({
    from: fromMock,
    storage: { from: () => ({ createSignedUrl: createSignedUrlMock }) },
  }),
  SUPABASE_ENV: 'prod',
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

describe('GET /api/data/parser-requests', () => {
  beforeEach(() => {
    fromMock.mockClear()
    createSignedUrlMock.mockClear()
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

  it('queries both parser_requests (auto) and pds_parser_requests (manual), signing storage_path fresh', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    const body = await res.json()

    expect(fromMock).toHaveBeenCalledWith('parser_requests')
    expect(fromMock).toHaveBeenCalledWith('pds_parser_requests')
    // Neither fixture row has a deal_id -> no pds_deals lookup needed,
    // deal_name resolves to null rather than a guessed value.
    expect(fromMock).not.toHaveBeenCalledWith('pds_deals')
    // PAR-145: no storage_path -> signed_url: null, never a stale stored URL
    expect(body.auto).toEqual([{ ...autoRows[0], signed_url: null, deal_name: null }])
    // storage_path present -> signed fresh on this request, not read from a column
    expect(createSignedUrlMock).toHaveBeenCalledWith('m1/stanbic.pdf', 36000)
    expect(body.manual).toEqual([{
      ...manualRows[0],
      signed_url: 'https://staging.supabase.co/storage/v1/object/sign/parser-requests/m1/stanbic.pdf?token=fresh',
      deal_name: null,
    }])
  })

  it('resolves deal_id -> company_name via a batched pds_deals lookup (PAR-242)', async () => {
    const dealRow = { id: 'd1', partner: 'musa', bank_name: 'Equity', deal_id: 'deal-1', status: 'pending', requested_at: '2026-09-01T00:00:00Z', storage_path: null }
    fromMock.mockImplementationOnce(() => ({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockResolvedValue({ data: [dealRow], error: null }),
      update: vi.fn().mockReturnThis(),
      eq: vi.fn().mockResolvedValue({ error: null }),
    }))
    fromMock.mockImplementationOnce(() => ({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockResolvedValue({ data: [], error: null }),
      update: vi.fn().mockReturnThis(),
      eq: vi.fn().mockResolvedValue({ error: null }),
    }))
    fromMock.mockImplementationOnce(() => ({
      select: vi.fn().mockReturnThis(),
      in: vi.fn().mockResolvedValue({ data: [{ id: 'deal-1', company_name: 'Buildex Interiors', name: null }], error: null }),
      order: vi.fn().mockReturnThis(),
      update: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
    }))

    const { GET } = await import('./route')
    const res = await GET()
    const body = await res.json()

    expect(fromMock).toHaveBeenCalledWith('pds_deals')
    expect(body.auto[0].deal_name).toBe('Buildex Interiors')
  })

  it('sets the x-data-environment header to prod (PAR-181)', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.headers.get('x-data-environment')).toBe('prod')
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
