import { getSupabase } from '@/lib/supabase'
import { requireAdminSession } from '@/lib/require-admin-session'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const supabase = getSupabase()
  const { id } = await params
  const [dealRes, docsRes, runsRes] = await Promise.all([
    supabase.from('pds_deals').select('*').eq('id', id).single(),
    supabase.from('pds_documents').select('*').eq('deal_id', id).order('created_at', { ascending: false }),
    supabase.from('pds_analysis_runs').select('*').eq('deal_id', id).order('created_at', { ascending: false }),
  ])
  if (dealRes.error) return NextResponse.json({ error: dealRes.error.message }, { status: 500 })
  return NextResponse.json({
    deal: dealRes.data,
    documents: docsRes.data ?? [],
    runs: runsRes.data ?? [],
  })
}
