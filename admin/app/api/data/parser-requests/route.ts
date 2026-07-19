import { getSupabase } from '@/lib/supabase'
import { NextRequest, NextResponse } from 'next/server'

// `parser_requests` ("auto" — Musa/GBFund failure paths, backend/v1/api.py:2355
// and backend/v1/integrations/musa_file_processor.py:417) and
// `pds_parser_requests` ("manual" — the user-facing form, app/api/request-parser/route.ts:203)
// are two separate tables. The admin queue must read both, or every
// form-submitted request is invisible here regardless of whether it was
// stored correctly (PAR-45).
export async function GET() {
  const supabase = getSupabase()

  const [autoResult, manualResult] = await Promise.all([
    supabase
      .from('parser_requests')
      .select('*')
      .order('requested_at', { ascending: false }),
    supabase
      .from('pds_parser_requests')
      .select('*')
      .order('created_at', { ascending: false }),
  ])

  if (autoResult.error) {
    return NextResponse.json({ error: autoResult.error.message }, { status: 500 })
  }
  if (manualResult.error) {
    return NextResponse.json({ error: manualResult.error.message }, { status: 500 })
  }

  return NextResponse.json({ auto: autoResult.data, manual: manualResult.data })
}

export async function PATCH(request: NextRequest) {
  const supabase = getSupabase()
  const { id, status } = await request.json()
  const { error } = await supabase
    .from('parser_requests')
    .update({ status })
    .eq('id', id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ ok: true })
}
