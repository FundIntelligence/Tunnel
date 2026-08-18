import { getSupabase, SUPABASE_ENV } from '@/lib/supabase'
import { requireAdminSession } from '@/lib/require-admin-session'
import { signParserRequestPaths } from '@/lib/parser-requests-signed-urls'
import { envHeaders } from '@/lib/env-header'
import { NextRequest, NextResponse } from 'next/server'

// `parser_requests` ("auto" — Musa/GBFund failure paths, backend/v1/api.py:2355
// and backend/v1/integrations/musa_file_processor.py:417) and
// `pds_parser_requests` ("manual" — the user-facing form, app/api/request-parser/route.ts:203)
// are two separate tables. The admin queue must read both, or every
// form-submitted request is invisible here regardless of whether it was
// stored correctly (PAR-45).
export async function GET() {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

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

  // `storage_path` (both tables) points into Parity's own `parser-requests`
  // Storage bucket — PAR-145: sign it fresh on every read instead of ever
  // persisting a URL, so the link is never older than this response. Rows
  // with no storage_path (nothing was ever uploaded) get signed_url: null.
  const [auto, manual] = await Promise.all([
    signParserRequestPaths(supabase, autoResult.data ?? []),
    signParserRequestPaths(supabase, manualResult.data ?? []),
  ])

  return NextResponse.json({ auto, manual }, { headers: envHeaders(SUPABASE_ENV) })
}

export async function PATCH(request: NextRequest) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const supabase = getSupabase()
  const { id, status } = await request.json()
  const { error } = await supabase
    .from('parser_requests')
    .update({ status })
    .eq('id', id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ ok: true })
}
