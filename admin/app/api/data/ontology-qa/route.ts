import { getSupabaseStaging } from '@/lib/supabase-staging'
import { NextResponse } from 'next/server'

export async function GET() {
  const supabase = getSupabaseStaging()
  const { data, error } = await supabase
    .from('pds_deals')
    .select('id, currency, created_at, accrual_period_start, accrual_period_end')
    .order('created_at', { ascending: false })
    .limit(100)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ deals: data ?? [], fetched_at: new Date().toISOString() })
}
