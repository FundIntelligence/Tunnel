import { NextRequest, NextResponse } from 'next/server'
import { getSupabaseSandbox, SUPABASE_ENV } from '@/lib/supabase-sandbox'
import { requireAdminSession } from '@/lib/require-admin-session'
import { generateSandboxApiKey, hashSandboxApiKey } from '@/lib/sandbox-key'
import { envHeaders } from '@/lib/env-header'

const SCOPE = 'sandbox-classify'

// PAR-245: api_keys.call_cap's table-wide default is 10000 (migration 027,
// shared with 'musa-partner' rows -- changing the column default would
// silently affect Musa's cap too, so it's left alone). Sandbox keys need
// the real, enforced 3,000 lifetime limit, set explicitly at issuance
// rather than relying on that shared default. Mirrors backend/v1/config.py's
// SANDBOX_FREE_LIMIT_CALLS -- no shared module between the two apps, so
// kept in sync by convention; a migration-042 CHECK constraint on
// api_keys (key_type <> 'sandbox-classify' OR call_cap <= 3000) is the
// real backstop if this ever drifts.
const SANDBOX_FREE_LIMIT_CALLS = 3000

export async function GET() {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const supabase = getSupabaseSandbox()
  const { data, error } = await supabase
    .from('api_keys')
    .select('id, partner_name, contact_email, calls_used, call_cap, status, created_at')
    .order('created_at', { ascending: false })
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data, { headers: envHeaders(SUPABASE_ENV) })
}

export async function POST(req: NextRequest) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const body = await req.json().catch(() => null)
  const partnerName = typeof body?.partner_name === 'string' ? body.partner_name.trim() : ''
  const contactEmail = typeof body?.contact_email === 'string' ? body.contact_email.trim() : ''
  if (!partnerName || !contactEmail) {
    return NextResponse.json({ error: 'partner_name and contact_email are required' }, { status: 400 })
  }

  const rawKey = generateSandboxApiKey()
  const apiKeyHash = await hashSandboxApiKey(rawKey)

  const supabase = getSupabaseSandbox()
  const { data, error } = await supabase
    .from('api_keys')
    .insert({
      api_key_hash: apiKeyHash,
      partner_name: partnerName,
      contact_email: contactEmail,
      key_type: SCOPE,
      call_cap: SANDBOX_FREE_LIMIT_CALLS,
    })
    .select('id, partner_name, contact_email, calls_used, call_cap, status, created_at')
    .single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  // raw_key is only ever present in this one response — it is never
  // stored, and no other endpoint can re-derive or re-display it.
  return NextResponse.json({ ...data, raw_key: rawKey }, { status: 201 })
}
