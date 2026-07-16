import { getSupabaseAdmin, parseEnv } from '@/lib/supabase-env'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const env = parseEnv(request)
  const supabase = getSupabaseAdmin(env)
  const { data, error } = await supabase
    .from('api_keys')
    .select('id, partner_name, active, created_at')
    .order('created_at', { ascending: false })
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ keys: data ?? [], env, fetched_at: new Date().toISOString() })
}
