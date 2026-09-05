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

  // PAR-242: "which deal/org requested it" — both tables only carry deal_id,
  // not a name, so the list previously showed an opaque UUID at best (manual
  // rows) or nothing (auto rows have no deal-name field at all). Resolve
  // deal_id -> company_name/name in one batched query rather than persisting
  // a duplicate copy of the name on either source table.
  const dealIds = Array.from(
    new Set(
      [...auto, ...manual]
        .map((r) => (r as { deal_id?: string | null }).deal_id)
        .filter((id): id is string => Boolean(id))
    )
  )
  let dealNameById: Record<string, string> = {}
  if (dealIds.length > 0) {
    const { data: deals } = await supabase
      .from('pds_deals')
      .select('id, company_name, name')
      .in('id', dealIds)
    dealNameById = Object.fromEntries(
      (deals ?? []).map((d) => [d.id, d.company_name || d.name || null])
    )
  }
  const withDealName = <T extends { deal_id?: string | null }>(rows: T[]) =>
    rows.map((r) => ({ ...r, deal_name: r.deal_id ? dealNameById[r.deal_id] ?? null : null }))

  return NextResponse.json(
    { auto: withDealName(auto), manual: withDealName(manual) },
    { headers: envHeaders(SUPABASE_ENV) }
  )
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
