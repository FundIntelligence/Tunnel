import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest, NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const rows = [
  { id: 'k1', partner_name: 'Acme', contact_email: 'dev@acme.com', calls_used: 3, call_cap: 10000, status: 'active', created_at: '2026-07-01T00:00:00Z' },
]

const selectMock = vi.fn()
const orderMock = vi.fn()
const insertSelectSingleMock = vi.fn()
const insertMock = vi.fn()
const fromMock = vi.fn()
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/supabase-sandbox', () => ({
  getSupabaseSandbox: () => ({ from: fromMock }),
  SUPABASE_ENV: 'sandbox',
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

vi.mock('@/lib/sandbox-key', () => ({
  generateSandboxApiKey: () => 'psb_rawkeyvalue',
  hashSandboxApiKey: async () => '$2b$12$fakehash',
}))

beforeEach(() => {
  requireAdminSessionMock.mockClear()
  requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))

  orderMock.mockResolvedValue({ data: rows, error: null })
  selectMock.mockReturnValue({ order: orderMock })

  insertSelectSingleMock.mockResolvedValue({
    data: { id: 'k2', partner_name: 'Acme', contact_email: 'dev@acme.com', calls_used: 0, call_cap: 10000, status: 'active', created_at: '2026-08-17T00:00:00Z' },
    error: null,
  })
  insertMock.mockReturnValue({ select: () => ({ single: insertSelectSingleMock }) })

  fromMock.mockReset()
  fromMock.mockReturnValue({ select: selectMock, insert: insertMock })
})

describe('GET /api/data/sandbox-keys', () => {
  it('returns 401 and never queries supabase when there is no session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('returns sandbox api_keys rows, never the hash column', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    expect(fromMock).toHaveBeenCalledWith('api_keys')
    expect(selectMock).toHaveBeenCalledWith('id, partner_name, contact_email, calls_used, call_cap, status, created_at')
    expect(await res.json()).toEqual(rows)
  })

  it('sets the x-data-environment header to sandbox (PAR-181)', async () => {
    const { GET } = await import('./route')
    const res = await GET()
    expect(res.headers.get('x-data-environment')).toBe('sandbox')
  })
})

describe('POST /api/data/sandbox-keys', () => {
  it('returns 400 when partner_name or contact_email is missing', async () => {
    const { POST } = await import('./route')
    const req = new NextRequest('http://localhost/api/data/sandbox-keys', {
      method: 'POST',
      body: JSON.stringify({ partner_name: '' }),
    })
    const res = await POST(req)
    expect(res.status).toBe(400)
    expect(insertMock).not.toHaveBeenCalled()
  })

  it('issues a key, inserts a hashed row scoped to sandbox-classify, and returns the raw key once', async () => {
    const { POST } = await import('./route')
    const req = new NextRequest('http://localhost/api/data/sandbox-keys', {
      method: 'POST',
      body: JSON.stringify({ partner_name: 'Acme', contact_email: 'dev@acme.com' }),
    })
    const res = await POST(req)
    expect(res.status).toBe(201)
    expect(insertMock).toHaveBeenCalledWith({
      api_key_hash: '$2b$12$fakehash',
      partner_name: 'Acme',
      contact_email: 'dev@acme.com',
      key_type: 'sandbox-classify',
    })
    const body = await res.json()
    expect(body.raw_key).toBe('psb_rawkeyvalue')
    expect(body.id).toBe('k2')
  })
})
