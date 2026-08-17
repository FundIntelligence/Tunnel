import { getSupabaseStaging } from '@/lib/supabase-staging'
import { requireAdminSession } from '@/lib/require-admin-session'
import { isOntologyQaAllowed } from '@/lib/ontology-qa-access'
import { NextResponse } from 'next/server'
import type { SupabaseClient } from '@supabase/supabase-js'

const CHUNK_SIZE = 100
const PAGE_SIZE = 1000

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

async function fetchAllTransactions(supabase: SupabaseClient, dealId: string) {
  const rows: Record<string, unknown>[] = []
  let offset = 0
  for (;;) {
    const { data, error } = await supabase
      .from('pds_raw_transactions')
      .select('id, txn_date, account_id, signed_amount_cents, abs_amount_cents, is_transfer, created_at')
      .eq('deal_id', dealId)
      .order('txn_date', { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1)
    if (error) throw error
    rows.push(...(data ?? []))
    if (!data || data.length < PAGE_SIZE) break
    offset += PAGE_SIZE
  }
  return rows
}

// pds_classification_overrides has no deal_id column, so it must be queried by
// txn_id in chunks — a deal can have thousands of transactions, and .in() with
// too many UUIDs at once was previously chunked at 1000 and silently dropped
// results past the query's practical limit. Chunking at 100 fixed that.
async function fetchClassificationOverrides(supabase: SupabaseClient, txnIds: string[]) {
  const byTxn = new Map<string, { role: string; at: string }>()
  for (const ids of chunk(txnIds, CHUNK_SIZE)) {
    if (ids.length === 0) continue
    const { data, error } = await supabase
      .from('pds_classification_overrides')
      .select('txn_id, override_role, overridden_at')
      .in('txn_id', ids)
    if (error) throw error
    for (const row of data ?? []) {
      const existing = byTxn.get(row.txn_id)
      if (!existing || row.overridden_at > existing.at) {
        byTxn.set(row.txn_id, { role: row.override_role, at: row.overridden_at })
      }
    }
  }
  return byTxn
}

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session
  if (!isOntologyQaAllowed(session.email)) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { id } = await params
  const supabase = getSupabaseStaging()

  const { data: deal, error: dealError } = await supabase
    .from('pds_deals')
    .select('id, currency, created_at, accrual_period_start, accrual_period_end')
    .eq('id', id)
    .single()
  if (dealError) return NextResponse.json({ error: dealError.message }, { status: 500 })

  const transactions = await fetchAllTransactions(supabase, id)
  const txnIds = transactions.map((t) => t.id as string)

  const [entityMapRes, overrideLogRes, entityOverridesRes] = await Promise.all([
    supabase.from('pds_txn_entity_map').select('txn_id, entity_id, role').eq('deal_id', id),
    supabase.from('pds_override_log').select('txn_uuid, override_role, created_at').eq('deal_id', id),
    supabase.from('pds_overrides').select('entity_id, new_value, created_at').eq('deal_id', id).eq('field', 'role'),
  ])
  if (entityMapRes.error) return NextResponse.json({ error: entityMapRes.error.message }, { status: 500 })
  if (overrideLogRes.error) return NextResponse.json({ error: overrideLogRes.error.message }, { status: 500 })
  if (entityOverridesRes.error) return NextResponse.json({ error: entityOverridesRes.error.message }, { status: 500 })

  const classificationOverrides = await fetchClassificationOverrides(supabase, txnIds)

  const roleByTxn = new Map<string, string>()
  const entityByTxn = new Map<string, string>()
  for (const row of entityMapRes.data ?? []) {
    roleByTxn.set(row.txn_id, row.role)
    entityByTxn.set(row.txn_id, row.entity_id)
  }

  const overrideLogByTxn = new Map<string, { role: string; at: string }>()
  for (const row of overrideLogRes.data ?? []) {
    const existing = overrideLogByTxn.get(row.txn_uuid)
    if (!existing || row.created_at > existing.at) {
      overrideLogByTxn.set(row.txn_uuid, { role: row.override_role, at: row.created_at })
    }
  }

  const entityOverrideByEntity = new Map<string, { value: string; at: string }>()
  for (const row of entityOverridesRes.data ?? []) {
    const existing = entityOverrideByEntity.get(row.entity_id)
    if (!existing || row.created_at > existing.at) {
      entityOverrideByEntity.set(row.entity_id, { value: row.new_value, at: row.created_at })
    }
  }

  // Precedence for analyst_resolution: a direct per-transaction reclassification
  // (pds_classification_overrides) beats a legacy per-transaction override log
  // entry, which beats an entity-wide role override applied to every transaction
  // for that entity. Falls back to '—' when no override exists (true for all
  // transactions today — every override table is empty on staging).
  const rows = transactions.map((txn) => {
    const txnId = txn.id as string
    const entityId = entityByTxn.get(txnId)
    const classificationOverride = classificationOverrides.get(txnId)
    const overrideLog = overrideLogByTxn.get(txnId)
    const entityOverride = entityId ? entityOverrideByEntity.get(entityId) : undefined

    const analystResolution =
      classificationOverride?.role ?? overrideLog?.role ?? entityOverride?.value ?? null

    return {
      ...txn,
      role: roleByTxn.get(txnId) ?? null,
      analyst_resolution: analystResolution,
    }
  })

  return NextResponse.json({ deal, transactions: rows, fetched_at: new Date().toISOString() })
}
