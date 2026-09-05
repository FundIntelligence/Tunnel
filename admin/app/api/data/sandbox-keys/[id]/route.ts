import { NextRequest, NextResponse } from 'next/server'
import { getSupabaseSandbox } from '@/lib/supabase-sandbox'
import { requireAdminSession } from '@/lib/require-admin-session'

// Revoke is one-way (no reactivation in PAR-149's scope). Sets both status
// and active: require_scoped_api_key only checks active=true (PAR-131),
// while increment_api_key_usage only checks status='active' (PAR-130) — a
// revoke has to flip both or a revoked key still passes the auth dependency
// and only gets caught downstream at the cap-check RPC.
export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const body = await req.json().catch(() => null)
  if (body?.action !== 'revoke') {
    return NextResponse.json({ error: 'unsupported action' }, { status: 400 })
  }

  const { id } = await params
  const supabase = getSupabaseSandbox()
  const { data, error } = await supabase
    .from('api_keys')
    .update({ status: 'revoked', active: false })
    .eq('id', id)
    .select('id, partner_name, contact_email, calls_used, call_cap, status, created_at')
    .single()
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data)
}
