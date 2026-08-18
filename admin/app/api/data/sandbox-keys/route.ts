import { NextRequest, NextResponse } from 'next/server'
import { getSupabaseSandbox, SUPABASE_ENV } from '@/lib/supabase-sandbox'
import { requireAdminSession } from '@/lib/require-admin-session'
import { generateSandboxApiKey, hashSandboxApiKey } from '@/lib/sandbox-key'
import { envHeaders } from '@/lib/env-header'

const SCOPE = 'sandbox-classify'

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
    })
    .select('id, partner_name, contact_email, calls_used, call_cap, status, created_at')
    .single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  // raw_key is only ever present in this one response — it is never
  // stored, and no other endpoint can re-derive or re-display it.
  return NextResponse.json({ ...data, raw_key: rawKey }, { status: 201 })
}
