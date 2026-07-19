import { describe, it, expect, vi, beforeEach } from 'vitest'

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
  }
}

const fromMock = vi.fn((table: string) => makeQuery(table as 'parser_requests' | 'pds_parser_requests'))

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({ from: fromMock }),
}))

describe('GET /api/data/parser-requests', () => {
  beforeEach(() => {
    fromMock.mockClear()
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
    }))

    const { GET } = await import('./route')
    const res = await GET()
    expect(res.status).toBe(500)
    expect(await res.json()).toEqual({ error: 'manual boom' })
  })
})
