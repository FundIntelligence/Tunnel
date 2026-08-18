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

function params(dealId: string) {
  return { params: Promise.resolve({ dealId }) }
}

describe('GET /api/data/deals/[dealId]/snapshot-pdf', () => {
  it('returns 401 and never calls the backend when there is no admin session', async () => {
    requireAdminSessionMock.mockImplementation(async () =>
      NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    )
    const { GET } = await import('./route')
    const res = await GET(new Request('http://localhost'), params('deal-1'))
    expect(res.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns 500 without calling the backend when ADMIN_BACKEND_API_KEY is not configured', async () => {
    delete process.env.ADMIN_BACKEND_API_KEY
    const { GET } = await import('./route')
    const res = await GET(new Request('http://localhost'), params('deal-1'))
    expect(res.status).toBe(500)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('proxies to the backend with the admin x-api-key header', async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob([new Uint8Array([1, 2, 3])]), {
        status: 200,
        headers: { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="parity_snapshot_deal-1.pdf"' },
      })
    )
    const { GET } = await import('./route')
    const res = await GET(new Request('http://localhost'), params('deal-1'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://parity-backend-prod-121148713552.us-central1.run.app/v1/deals/deal-1/snapshot/pdf')
    expect(init.headers).toEqual({ 'x-api-key': 'admin-real-key' })

    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toBe('application/pdf')
  })

  it('passes through a backend auth failure instead of masking it as success', async () => {
    fetchMock.mockResolvedValue(new Response('Authentication required', { status: 401 }))
    const { GET } = await import('./route')
    const res = await GET(new Request('http://localhost'), params('deal-1'))
    expect(res.status).toBe(401)
  })
})
