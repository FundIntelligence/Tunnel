import { createClient } from '@supabase/supabase-js'

// PAR-181: exported alongside getSupabase() so routes can set the
// x-data-environment response header from the same import that decides
// the DB connection — see lib/env-header.ts.
export const SUPABASE_ENV = 'prod' as const

export function getSupabase() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!supabaseUrl || !supabaseServiceKey) {
    throw new Error('Missing Supabase env vars')
  }
  return createClient(supabaseUrl, supabaseServiceKey)
}
