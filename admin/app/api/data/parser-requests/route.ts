import { getSupabaseAdmin, parseEnv } from '@/lib/supabase-env'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const env = parseEnv(request)
  const supabase = getSupabaseAdmin(env)

  const [autoRes, manualRes] = await Promise.all([
    supabase.from('parser_requests').select('*').order('requested_at', { ascending: false }),
    supabase.from('pds_parser_requests').select('*').order('created_at', { ascending: false }),
  ])
  if (autoRes.error) return NextResponse.json({ error: autoRes.error.message }, { status: 500 })
  if (manualRes.error) return NextResponse.json({ error: manualRes.error.message }, { status: 500 })

  return NextResponse.json({
    auto: autoRes.data ?? [],
    manual: manualRes.data ?? [],
    env,
    fetched_at: new Date().toISOString(),
  })
}

// Tables whose status the admin may cycle. Allowlisted so a request body can
// never point .from() at an arbitrary table.
const PATCHABLE_TABLES = new Set(['parser_requests', 'pds_parser_requests'])
// Statuses that mean "the parser was built / request resolved" — trigger the
// resolution Slack message. parser_requests uses done; pds_parser_requests uses
// processed.
const RESOLVED_STATUSES = new Set(['processed', 'done'])

async function notifySlackResolved(bankName: string, fileName: string | null, status: string) {
  const webhook = process.env.SLACK_PARSER_WEBHOOK_URL
  if (!webhook) return
  const text = [
    `:white_check_mark: *Parser Request resolved:* ${bankName || '—'}`,
    fileName ? `• File: ${fileName}` : '',
    `• Status: ${status}`,
  ].filter(Boolean).join('\n')
  try {
    await fetch(webhook, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
  } catch (err) {
    console.error('[admin/parser-requests] slack resolved-notify failed:', err)
  }
}

export async function PATCH(request: NextRequest) {
  const env = parseEnv(request)
  const supabase = getSupabaseAdmin(env)
  const { id, status, table = 'parser_requests' } = await request.json()

  if (!PATCHABLE_TABLES.has(table)) {
    return NextResponse.json({ error: `unknown table '${table}'` }, { status: 400 })
  }

  // pds_parser_requests carries processed_at; stamp it on resolution.
  const patch: Record<string, unknown> = { status }
  if (table === 'pds_parser_requests' && RESOLVED_STATUSES.has(status)) {
    patch.processed_at = new Date().toISOString()
  }

  const { error } = await supabase.from(table).update(patch).eq('id', id)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  // Fire the resolution notification (best-effort; never fails the update).
  if (RESOLVED_STATUSES.has(status)) {
    const { data: row } = await supabase
      .from(table)
      .select('bank_name, original_filename')
      .eq('id', id)
      .maybeSingle()
    await notifySlackResolved(
      (row?.bank_name as string) ?? '',
      (row?.original_filename as string) ?? null,
      status,
    )
  }

  return NextResponse.json({ ok: true })
}
