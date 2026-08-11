import { describe, it, expect, vi, beforeEach } from 'vitest'

const getUserMock = vi.fn()
const getAllMock = vi.fn(() => [])

vi.mock('next/headers', () => ({
  cookies: async () => ({ getAll: getAllMock }),
}))

vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: { getUser: getUserMock },
  }),
}))

describe('requireAdminSession', () => {
  beforeEach(() => {
    getUserMock.mockReset()
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://example.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon-key'
  })

  it('returns a 401 response when there is no session', async () => {
    getUserMock.mockResolvedValue({ data: { user: null } })
    const { requireAdminSession } = await import('./require-admin-session')

    const result = await requireAdminSession()

    expect(result).toBeInstanceOf(Response)
    expect((result as Response).status).toBe(401)
  })

  it('returns a 403 response when the session email is not allowlisted', async () => {
    getUserMock.mockResolvedValue({ data: { user: { email: 'stranger@example.com' } } })
    const { requireAdminSession } = await import('./require-admin-session')

    const result = await requireAdminSession()

    expect(result).toBeInstanceOf(Response)
    expect((result as Response).status).toBe(403)
  })

  it('returns the session when the email is allowlisted', async () => {
    getUserMock.mockResolvedValue({ data: { user: { email: 'KWATUKHAM@gmail.com' } } })
    const { requireAdminSession } = await import('./require-admin-session')

    const result = await requireAdminSession()

    expect(result).toEqual({ email: 'kwatukham@gmail.com' })
  })
})
