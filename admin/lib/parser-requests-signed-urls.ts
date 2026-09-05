import type { SupabaseClient } from '@supabase/supabase-js'

// Matches the 10-hour expiry Musa's own presigned URLs used (PAR-145) —
// generous for an admin viewing session, short enough that a leaked link
// doesn't stay live indefinitely.
export const PARSER_REQUEST_SIGNED_URL_EXPIRY_SECONDS = 36000

/**
 * Sign each row's `storage_path` (Parity-owned `parser-requests` Storage
 * bucket) fresh, right now — never stored, never reused across requests.
 * Rows without a storage_path (nothing was ever uploaded for that request)
 * get signed_url: null rather than being dropped.
 */
export async function signParserRequestPaths<T extends { storage_path?: string | null }>(
  supabase: SupabaseClient,
  rows: T[]
): Promise<Array<T & { signed_url: string | null }>> {
  return Promise.all(
    rows.map(async (row) => {
      if (!row.storage_path) {
        return { ...row, signed_url: null }
      }
      const { data, error } = await supabase.storage
        .from('parser-requests')
        .createSignedUrl(row.storage_path, PARSER_REQUEST_SIGNED_URL_EXPIRY_SECONDS)
      if (error) {
        return { ...row, signed_url: null }
      }
      return { ...row, signed_url: data.signedUrl }
    })
  )
}
