import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest, NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const updateSingleMock = vi.fn()
const updateSelectMock = vi.fn()
const updateMock = vi.fn()
const eqMock = vi.fn()
const fromMock = vi.fn()
const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/supabase-sandbox', () => ({
  getSupabaseSandbox: () => ({ from: fromMock }),
}))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

beforeEach(() => {
  requireAdminSessionMock.mockClear()
  requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))

  updateSingleMock.mockResolvedValue({
    data: { id: 'k1', partner_name: 'Acme', contact_email: 'dev@acme.com', calls_used: 3, call_cap: 10000, status: 'revoked', created_at: '2026-07-01T00:00:00Z' },
    error: null,
  })
  updateSelectMock.mockReturnValue({ single: updateSingleMock })
  eqMock.mockReturnValue({ select: updateSelectMock })
  updateMock.mockReturnValue({ eq: eqMock })
  fromMock.mockReset()
  fromMock.mockReturnValue({ update: updateMock })
})

function makeReq(body: unknown) {
  return new NextRequest('http://localhost/api/data/sandbox-keys/k1', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

describe('PATCH /api/data/sandbox-keys/[id]', () => {
  it('returns 401 and never touches supabase when there is no session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { PATCH } = await import('./route')
    const res = await PATCH(makeReq({ action: 'revoke' }), { params: Promise.resolve({ id: 'k1' }) })
    expect(res.status).toBe(401)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('rejects unsupported actions', async () => {
    const { PATCH } = await import('./route')
    const res = await PATCH(makeReq({ action: 'reactivate' }), { params: Promise.resolve({ id: 'k1' }) })
    expect(res.status).toBe(400)
    expect(fromMock).not.toHaveBeenCalled()
  })

  it('sets both status and active on revoke', async () => {
    const { PATCH } = await import('./route')
    const res = await PATCH(makeReq({ action: 'revoke' }), { params: Promise.resolve({ id: 'k1' }) })
    expect(updateMock).toHaveBeenCalledWith({ status: 'revoked', active: false })
    expect(eqMock).toHaveBeenCalledWith('id', 'k1')
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.status).toBe('revoked')
  })
})
