import { createClient } from '@supabase/supabase-js'

// PAR-181: see lib/supabase.ts's SUPABASE_ENV for why this lives here.
export const SUPABASE_ENV = 'staging' as const

export function getSupabaseStaging() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL_STAGING
  const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY_STAGING
  if (!supabaseUrl || !supabaseServiceKey) {
    throw new Error('Missing staging Supabase env vars — refusing to fall back to prod')
  }
  return createClient(supabaseUrl, supabaseServiceKey, { auth: { persistSession: false } })
}
