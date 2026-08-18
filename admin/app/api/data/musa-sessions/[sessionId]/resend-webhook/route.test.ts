import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextResponse } from 'next/server'
import type { AdminSession } from '@/lib/require-admin-session'

const requireAdminSessionMock = vi.fn<() => Promise<AdminSession | NextResponse>>(async () => ({ email: 'kwatukham@gmail.com' }))

vi.mock('@/lib/require-admin-session', () => ({
  requireAdminSession: () => requireAdminSessionMock(),
}))

const fetchMock = vi.fn()

beforeEach(() => {
  requireAdminSessionMock.mockClear()
  requireAdminSessionMock.mockImplementation(async () => ({ email: 'kwatukham@gmail.com' }))
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  process.env.ADMIN_BACKEND_API_KEY = 'admin-real-key'
})

afterEach(() => {
  vi.unstubAllGlobals()
  delete process.env.ADMIN_BACKEND_API_KEY
})

function params(sessionId: string) {
  return { params: Promise.resolve({ sessionId }) }
}

describe('POST /api/data/musa-sessions/[sessionId]/resend-webhook', () => {
  it('returns 401 and never calls the backend when there is no admin session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { POST } = await import('./route')
    const res = await POST(new Request('http://localhost', { method: 'POST' }), params('sid-1'))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns 500 without calling the backend when ADMIN_BACKEND_API_KEY is not configured', async () => {
    delete process.env.ADMIN_BACKEND_API_KEY
    const { POST } = await import('./route')
    const res = await POST(new Request('http://localhost', { method: 'POST' }), params('sid-1'))
    expect(res.status).toBe(500)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('proxies to the backend with the admin x-api-key header', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: 'sid-1',
          status: 'complete',
          is_retry: true,
          resend_count: 1,
          webhook_status_code: 200,
          webhook_delivered: true,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      )
    )
    const { POST } = await import('./route')
    const res = await POST(new Request('http://localhost', { method: 'POST' }), params('sid-1'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://parity-backend-prod-121148713552.us-central1.run.app/api/musa/admin/sessions/sid-1/resend-webhook')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'x-api-key': 'admin-real-key' })

    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.is_retry).toBe(true)
    expect(body.resend_count).toBe(1)
  })

  it('passes through a backend failure (e.g. session still processing) instead of masking it as success', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session is still processing — nothing to resend yet' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      })
    )
    const { POST } = await import('./route')
    const res = await POST(new Request('http://localhost', { method: 'POST' }), params('sid-1'))
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('Session is still processing — nothing to resend yet')
  })

  it('URL-encodes the session id path segment', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    const { POST } = await import('./route')
    await POST(new Request('http://localhost', { method: 'POST' }), params('sid with space'))
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('sid%20with%20space')
  })
})
