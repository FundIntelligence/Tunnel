import { getSupabaseAdmin, parseEnv } from '@/lib/supabase-env'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const env = parseEnv(request)
  const supabase = getSupabaseAdmin(env)
  const { data, error } = await supabase
    .from('musa_sessions')
    .select('session_id, venture_id, venture_name, venture_country, deal_id, status, created_at, completed_at, document_urls, error_message')
    .order('created_at', { ascending: false })
    .limit(100)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ sessions: data ?? [], env, fetched_at: new Date().toISOString() })
}
