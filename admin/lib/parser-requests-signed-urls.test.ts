import { describe, it, expect, vi } from 'vitest'
import { signParserRequestPaths, PARSER_REQUEST_SIGNED_URL_EXPIRY_SECONDS } from './parser-requests-signed-urls'

function makeSupabase(createSignedUrl: ReturnType<typeof vi.fn>) {
  return { storage: { from: () => ({ createSignedUrl }) } } as never
}

describe('signParserRequestPaths', () => {
  it('signs a fresh URL for each row with a storage_path', async () => {
    const createSignedUrl = vi.fn(async (path: string) => ({
      data: { signedUrl: `https://x.supabase.co/sign/${path}` },
      error: null,
    }))
    const rows = await signParserRequestPaths(makeSupabase(createSignedUrl), [
      { id: '1', storage_path: 'a/file.pdf' },
    ])
    expect(createSignedUrl).toHaveBeenCalledWith('a/file.pdf', PARSER_REQUEST_SIGNED_URL_EXPIRY_SECONDS)
    expect(rows).toEqual([{ id: '1', storage_path: 'a/file.pdf', signed_url: 'https://x.supabase.co/sign/a/file.pdf' }])
  })

  it('returns signed_url: null without calling Storage when storage_path is missing', async () => {
    const createSignedUrl = vi.fn()
    const rows = await signParserRequestPaths(makeSupabase(createSignedUrl), [
      { id: '1', storage_path: null },
    ])
    expect(createSignedUrl).not.toHaveBeenCalled()
    expect(rows).toEqual([{ id: '1', storage_path: null, signed_url: null }])
  })

  it('returns signed_url: null (not a thrown error) if Storage signing fails', async () => {
    const createSignedUrl = vi.fn(async () => ({ data: null, error: { message: 'object not found' } }))
    const rows = await signParserRequestPaths(makeSupabase(createSignedUrl), [
      { id: '1', storage_path: 'missing/file.pdf' },
    ])
    expect(rows).toEqual([{ id: '1', storage_path: 'missing/file.pdf', signed_url: null }])
  })
})
