import { getSupabase, SUPABASE_ENV } from '@/lib/supabase'
import { requireAdminSession } from '@/lib/require-admin-session'
import { envHeaders } from '@/lib/env-header'
import { NextResponse } from 'next/server'

export async function GET() {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const supabase = getSupabase()
  const { data, error } = await supabase
    .from('pds_deals')
    .select('id, name, company_name, currency, created_at')
    .order('created_at', { ascending: false })
    .limit(100)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json(data, { headers: envHeaders(SUPABASE_ENV) })
}
