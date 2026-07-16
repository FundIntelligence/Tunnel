import { getSupabaseAdmin, parseEnv } from '@/lib/supabase-env'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const env = parseEnv(request)
  const supabase = getSupabaseAdmin(env)
  const { data, error } = await supabase
    .from('pds_deals')
    .select('id, name, company_name, currency, created_at, analyst_initials')
    .order('created_at', { ascending: false })
    .limit(100)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ deals: data ?? [], env, fetched_at: new Date().toISOString() })
}
