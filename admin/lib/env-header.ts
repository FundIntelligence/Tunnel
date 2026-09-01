// PAR-181: single source of truth for surfacing "which environment did this
// response actually come from" to the browser.
//
// The badge shown on a page must never be a literal string hardcoded in that
// page's component — that's exactly the drift PAR-181 exists to prevent (a
// page could say "prod" while its API route was quietly pointed at staging,
// and nothing would catch it). Instead, each API route sets this header
// using the SUPABASE_ENV constant exported by the *same* client-factory file
// it imports its Supabase client from (see lib/supabase.ts, lib/supabase-
// staging.ts, lib/supabase-sandbox.ts). The header value and the DB
// connection are therefore always the same import, and can't independently
// drift.
export const ENV_HEADER = 'x-data-environment'

export function envHeaders(env: string): HeadersInit {
  return { [ENV_HEADER]: env }
}
