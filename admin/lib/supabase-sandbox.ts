import { createClient } from '@supabase/supabase-js'

// Isolated ParitySandbox project (vksrelnjoejzqkiwqano) — same project the
// parity-classify-sandbox service reads/writes, distinct from both the main
// and staging admin projects. See parity-classify-sandbox/app/config.py for
// why these are separately named env vars rather than reusing SUPABASE_URL.
export function getSupabaseSandbox() {
  const supabaseUrl = process.env.SANDBOX_SUPABASE_URL
  const supabaseServiceKey = process.env.SANDBOX_SUPABASE_SERVICE_ROLE_KEY
  if (!supabaseUrl || !supabaseServiceKey) {
    throw new Error('Missing sandbox Supabase env vars — refusing to fall back to another project')
  }
  return createClient(supabaseUrl, supabaseServiceKey, { auth: { persistSession: false } })
}
