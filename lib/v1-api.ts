import { fetchApi, API_URL } from './api'
import { createBrowserClient } from './supabase'
import { getApiToken, setApiToken } from './auth-bridge'

const BASE = '/v1'

/**
 * POST multipart to /v1 without a default JSON Content-Type.
 * fetch() must set multipart boundary automatically — never pass Content-Type here.
 */
async function fetchApiFormData(
  endpoint: string,
  init: RequestInit & { body: FormData }
): Promise<Response> {
  if (!endpoint.startsWith('/v1')) {
    throw new Error(
      `Legacy API call blocked: "${endpoint}". All API calls must use /v1/* routes.`
    )
  }
  const url = `${API_URL}${endpoint}`
  const supabase = createBrowserClient()
  let token = getApiToken()
  if (!token && supabase) {
    try {
      const { data } = await supabase.auth.getSession()
      token = data.session?.access_token ?? null
      if (token) setApiToken(token)
    } catch {
      /* continue without auth */
    }
  }
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(url, { ...init, headers })
  if (res.status === 401 && supabase && token) {
    try {
      const { data } = await supabase.auth.refreshSession()
      if (data.session?.access_token) {
        setApiToken(data.session.access_token)
        headers.Authorization = `Bearer ${data.session.access_token}`
        return fetch(url, { ...init, headers })
      }
    } catch {
      /* return original response */
    }
  }
  return res
}

export interface AccrualInput {
  accrual_revenue_cents?: number
  accrual_period_start?: string
  accrual_period_end?: string
}

export interface Deal {
  id: string
  currency?: string
  name?: string
  created_by?: string
  accrual_revenue_cents?: number
  accrual_period_start?: string
  accrual_period_end?: string
  /** Distinct batch uploads used (1–20); usually derived client-side from documents if not on deal row */
  batch_upload_count?: number
}

export interface AnalysisRun {
  id: string
  deal_id: string
  non_transfer_abs_total_cents: number
  coverage_pct_bp: number
  reconciliation_status: 'OK' | 'NOT_RUN' | 'FAILED_OVERLAP' | 'LOW'
  reconciliation_pct_bp: number | null
  final_confidence_bp: number
  tier: 'Low' | 'Medium' | 'High'
  bank_operational_inflow_cents: number
  [key: string]: unknown
}

export interface Snapshot {
  id: string
  sha256_hash: string
  financial_state_hash: string
  [key: string]: unknown
}

export interface Entity {
  entity_id: string
  deal_id: string
  display_name: string
  [key: string]: unknown
}

export interface TxnEntityMapping {
  txn_id: string
  entity_id: string
  role: string
  [key: string]: unknown
}

export interface ExportResponse {
  analysis_run: AnalysisRun
  snapshot: Snapshot
  entities: Entity[]
  txn_entity_map: TxnEntityMapping[]
}

export async function createDeal(
  currency: string,
  name?: string,
  accrual?: AccrualInput,
  companyName?: string,
  analystInitials?: string
): Promise<{ deal: Deal }> {
  const form = new FormData()
  form.append('currency', currency)
  if (name) form.append('name', name)
  if (companyName) form.append('company_name', companyName)
  if (analystInitials) form.append('analyst_initials', analystInitials)
  if (accrual?.accrual_revenue_cents != null)
    form.append('accrual_revenue_cents', String(accrual.accrual_revenue_cents))
  if (accrual?.accrual_period_start)
    form.append('accrual_period_start', accrual.accrual_period_start)
  if (accrual?.accrual_period_end)
    form.append('accrual_period_end', accrual.accrual_period_end)
  const res = await fetchApiFormData(`${BASE}/deals`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadDocument(
  dealId: string,
  file: File
): Promise<{
  ingestion: { document_id: string; rows_count: number };
  detectedCurrency?: string;
}> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetchApiFormData(`${BASE}/deals/${dealId}/documents`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface DocumentStatusResponse {
  document_id: string
  status: string
  error?: string
  error_type?: string
  error_message?: string
  stage?: string
  next_action?: string
  traceback?: string
  currency_detected?: string
  analytics?: {
    monthly_cashflow?: Array<Record<string, unknown>>
    credit_scoring_inputs?: Record<string, unknown>
    monthly_entity_breakdown?: Array<Record<string, unknown>>
    [key: string]: unknown
  }
}

export async function getDocumentStatus(
  documentId: string
): Promise<DocumentStatusResponse> {
  const res = await fetchApi(`${BASE}/documents/${documentId}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function exportSnapshot(
  dealId: string
): Promise<ExportResponse> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/export`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/** Read-only check for whether a deal already has an analysis run, without triggering export. */
export async function getLatestAnalysis(
  dealId: string
): Promise<{ analysis_run: AnalysisRun | null }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/analysis/latest`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getDocumentTransactions(
  documentId: string
): Promise<{ document_id: string; transactions: Array<Record<string, unknown>> }> {
  const res = await fetchApi(`${BASE}/documents/${documentId}/transactions`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface DocumentListItem {
  id: string
  status: string
  batch_number?: number | null
  is_batch_upload?: boolean | null
  [key: string]: unknown
}

export async function listDocuments(
  dealId: string
): Promise<{ documents: DocumentListItem[] }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/documents`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface BatchUploadResponse {
  document_id: string
  batch_number: number
  batches_remaining: number
  files_merged: number
  source_files: string[]
  status: string
  message: string
  ingestion: { document_id: string; status: string; rows_count: number }
}

export async function uploadDocumentsBatch(
  dealId: string,
  files: File[]
): Promise<BatchUploadResponse> {
  const form = new FormData()
  for (const f of files) {
    form.append('files', f)
  }
  const res = await fetchApiFormData(`${BASE}/deals/${dealId}/documents/batch`, {
    method: 'POST',
    body: form,
  })
  const text = await res.text()
  if (!res.ok) {
    let msg = text?.slice(0, 500) || `Upload failed (${res.status})`
    try {
      const j = JSON.parse(text) as { detail?: string | { error_message?: string } }
      const d = j.detail
      if (typeof d === 'string') msg = d
      else if (d && typeof d === 'object' && 'error_message' in d && d.error_message)
        msg = String(d.error_message)
    } catch {
      /* keep msg */
    }
    throw new Error(msg)
  }
  try {
    return JSON.parse(text) as BatchUploadResponse
  } catch {
    throw new Error('Invalid response from batch upload')
  }
}

export interface AuditedFinancialsRecord {
  id?: string
  deal_id: string
  financial_year?: number
  financial_year_start?: string
  financial_year_end?: string
  company_name?: string
  declaration_type?: 'audited' | 'management'
  turnover_cents?: number | null
  profit_after_tax_cents?: number | null
  total_assets_cents?: number | null
  cash_and_equivalents_cents?: number | null
  total_expenses_cents?: number | null
  total_liabilities_cents?: number | null
  extraction_confidence?: number
  confirmed_at?: string | null
  removed_at?: string | null
}

/**
 * Thrown when an upload is blocked because a human-confirmed record already
 * exists for the same deal + financial year (HTTP 409). Carries a stable `code`
 * so the UI can render a named, actionable state instead of a generic failure.
 */
export class AuditedFinancialsUploadError extends Error {
  code: string
  status: number
  financialYear?: number | null
  constructor(
    message: string,
    opts: { code: string; status: number; financialYear?: number | null }
  ) {
    super(message)
    this.name = 'AuditedFinancialsUploadError'
    this.code = opts.code
    this.status = opts.status
    this.financialYear = opts.financialYear ?? null
  }
}

/**
 * Thrown when a removal is blocked or under-specified. Codes:
 *   CONFIRMED_RECORD_LOCKED   (409) — confirmed record, no ?supersede=true
 *   SUPERSEDE_REASON_REQUIRED (422) — supersede requested without a reason
 * Carries a stable `code` so the UI can render a named state.
 */
export class AuditedFinancialsRemoveError extends Error {
  code: string
  status: number
  financialYear?: number | null
  constructor(
    message: string,
    opts: { code: string; status: number; financialYear?: number | null }
  ) {
    super(message)
    this.name = 'AuditedFinancialsRemoveError'
    this.code = opts.code
    this.status = opts.status
    this.financialYear = opts.financialYear ?? null
  }
}

export async function uploadAuditedFinancials(
  dealId: string,
  file: File,
  declarationType: 'audited' | 'management' = 'audited'
): Promise<AuditedFinancialsRecord> {
  const form = new FormData()
  form.append('file', file)
  form.append('declaration_type', declarationType)
  const res = await fetchApiFormData(`${BASE}/deals/${dealId}/upload-financials`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const bodyText = await res.text()
    // FastAPI nests structured detail under { detail: {...} }.
    let detail: unknown = null
    try {
      detail = (JSON.parse(bodyText) as { detail?: unknown }).detail
    } catch {
      /* non-JSON body — fall through to raw text */
    }
    if (
      res.status === 409 &&
      detail &&
      typeof detail === 'object' &&
      (detail as { status?: string }).status === 'CONFIRMED_RECORD_EXISTS'
    ) {
      const d = detail as { detail?: string; financial_year?: number }
      throw new AuditedFinancialsUploadError(
        d.detail || 'A confirmed record exists for this financial year.',
        { code: 'CONFIRMED_RECORD_EXISTS', status: 409, financialYear: d.financial_year }
      )
    }
    const msg =
      detail && typeof detail === 'object' && (detail as { detail?: string }).detail
        ? (detail as { detail: string }).detail
        : typeof detail === 'string'
          ? detail
          : bodyText
    throw new Error(msg)
  }
  return res.json()
}

export async function getAuditedFinancials(
  dealId: string
): Promise<{ deal_id: string; records: AuditedFinancialsRecord[] }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/audited-financials`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function patchAuditedFinancials(
  dealId: string,
  financialYear: number,
  fields: Partial<AuditedFinancialsRecord>
): Promise<AuditedFinancialsRecord> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/audited-financials/${financialYear}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * Soft-remove an audited-financials record from a deal's queue.
 * Unconfirmed records remove freely. Confirmed records require
 * `{ supersede: true, reason }` — the backend returns 409 CONFIRMED_RECORD_LOCKED
 * otherwise, or 422 SUPERSEDE_REASON_REQUIRED if the reason is missing.
 */
export async function removeAuditedFinancials(
  dealId: string,
  financialYear: number,
  opts: { supersede?: boolean; reason?: string } = {}
): Promise<{ status: string; deal_id: string; financial_year: number; superseded: boolean }> {
  const qs = opts.supersede ? '?supersede=true' : ''
  const res = await fetchApi(
    `${BASE}/deals/${dealId}/audited-financials/${financialYear}${qs}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts.reason ? { reason: opts.reason } : {}),
    }
  )
  if (!res.ok) {
    const bodyText = await res.text()
    let detail: unknown = null
    try {
      detail = (JSON.parse(bodyText) as { detail?: unknown }).detail
    } catch {
      /* non-JSON body — fall through to raw text */
    }
    const d =
      detail && typeof detail === 'object'
        ? (detail as { status?: string; detail?: string; financial_year?: number })
        : null
    if (res.status === 409 && d?.status === 'CONFIRMED_RECORD_LOCKED') {
      throw new AuditedFinancialsRemoveError(
        d.detail || 'This financial year is confirmed and is locked against removal.',
        { code: 'CONFIRMED_RECORD_LOCKED', status: 409, financialYear: d.financial_year }
      )
    }
    if (res.status === 422 && d?.status === 'SUPERSEDE_REASON_REQUIRED') {
      throw new AuditedFinancialsRemoveError(
        d.detail || 'A reason is required to supersede a confirmed record.',
        { code: 'SUPERSEDE_REASON_REQUIRED', status: 422, financialYear: d.financial_year }
      )
    }
    throw new Error(d?.detail || bodyText)
  }
  return res.json()
}

export async function addOverride(
  dealId: string,
  entityId: string,
  newValue: string,
  note?: string
): Promise<{ override: Record<string, unknown> }> {
  const form = new FormData()
  form.append('entity_id', entityId)
  form.append('new_value', newValue)
  if (note) form.append('reason', note)
  const res = await fetchApiFormData(`${BASE}/deals/${dealId}/overrides`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function listOverrides(
  dealId: string
): Promise<{ overrides: Array<Record<string, unknown>> }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/overrides`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function askParity(
  dealId: string,
  question: string
): Promise<{ answer: string; intent: string | null }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ParityReviewChatResponse {
  response: string
  conversation_history: Array<{ role: string; content: unknown }>
  tools_called: string[]
  is_proactive?: boolean
  usage: {
    input_tokens: number
    output_tokens: number
    cache_creation_input_tokens?: number
    cache_read_input_tokens?: number
  }
}

export async function askParityReview(
  dealId: string,
  message: string,
  conversationHistory: Array<{ role: string; content: unknown }> = [],
  chatHistory: Array<{ role: string; text: string; time: string }> = []
): Promise<ParityReviewChatResponse> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/parity-review/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_history: conversationHistory, chat_history: chatHistory }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ParityChatSession {
  session_id: string | null
  chat_history: Array<{ role: string; text: string; time: string }>
  conversation_history: Array<{ role: string; content: unknown }>
  updated_at?: string
}

export async function getParityChatSession(dealId: string): Promise<ParityChatSession> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/parity-review/chat/session`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function clearParityChatSession(dealId: string): Promise<void> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/parity-review/chat/session`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function exportTransactionsCsv(dealId: string): Promise<Response> {
  return fetchApi(`${BASE}/deals/${dealId}/export/transactions`)
}

export interface DealTransaction {
  id: string
  txn_id: string
  txn_date: string
  description: string
  signed_amount_cents: number
  account_id: string
  role: string
  entity_name: string
}

export async function listDealTransactions(
  dealId: string
): Promise<{ deal_id: string; transactions: DealTransaction[] }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/transactions`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Analyst Enrichment ────────────────────────────────────────────────────────

export interface ClassificationOverride {
  txn_id: string
  original_role: string
  original_reason?: string
  override_role: string
  override_reason: string
}

export interface FlagCriteria {
  metric: string           // 'closing_balance' | 'overdraft_days' | 'single_transaction_amount'
  comparison: string       // 'less_than' | 'greater_than' | 'less_than_or_equal' | 'greater_than_or_equal'
  threshold_cents: number
}

export interface CustomFlag {
  flag_type: string        // 'threshold' | 'pattern' | 'compliance' | 'custom'
  flag_name: string
  flag_severity: string    // 'info' | 'warning' | 'critical'
  flag_description: string
  criteria: FlagCriteria
  // populated after evaluation
  triggered?: boolean
  trigger_count?: number
  trigger_details?: unknown[]
}

export interface Enrichment {
  id: string
  base_snapshot_id: string
  enriched_hash: string
  analyst_id: string
  analyst_name?: string
  narrative?: string
  enrichment_reason?: string
  is_final: boolean
  created_at: string
  overrides?: ClassificationOverride[]
  flags?: CustomFlag[]
}

export interface CreateEnrichmentInput {
  analyst_id: string
  analyst_name?: string
  overrides?: ClassificationOverride[]
  flags?: CustomFlag[]
  narrative?: string
  enrichment_reason?: string
  is_final?: boolean
}

export async function createEnrichment(
  dealId: string,
  input: CreateEnrichmentInput
): Promise<{ enrichment_id: string; enriched_hash: string; created: boolean }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/enrichment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getLatestEnrichment(
  dealId: string
): Promise<{ enrichment: Enrichment | null }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/enrichment/latest`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getEnrichment(enrichmentId: string): Promise<Enrichment> {
  const res = await fetchApi(`${BASE}/enrichments/${enrichmentId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function finalizeEnrichment(
  enrichmentId: string
): Promise<{ enrichment_id: string; is_final: boolean }> {
  const res = await fetchApi(`${BASE}/enrichments/${enrichmentId}/finalize`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function evaluateFlags(
  enrichmentId: string,
  flags: CustomFlag[]
): Promise<{ flags: CustomFlag[] }> {
  const res = await fetchApi(`${BASE}/enrichments/${enrichmentId}/evaluate-flags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ flags }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function downloadEnrichedPdf(
  dealId: string,
  enrichmentId?: string
): Promise<Response> {
  const params = enrichmentId ? `?enrichment_id=${enrichmentId}` : ''
  return fetchApi(`${BASE}/deals/${dealId}/snapshot/pdf/enriched${params}`)
}

export interface NeedsReviewTransaction {
  row_id: string
  txn_hash: string
  txn_date: string
  description: string
  signed_amount_cents: number
  entity_name: string
  current_role: string
}

export async function getNeedsReviewTransactions(
  dealId: string
): Promise<{ transactions: NeedsReviewTransaction[]; total: number }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/transactions/needs-review`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export type OverrideReasonCategory =
  | 'misclassified_rule_matching'
  | 'ambiguous_narrative'
  | 'known_exception'
  | 'duplicate_reversal'
  | 'other'

// PAR-52 draft taxonomy — may be refined later. 'other' requires a reason note.
export const OVERRIDE_REASON_OPTIONS: { value: OverrideReasonCategory; label: string }[] = [
  { value: 'misclassified_rule_matching', label: 'Misclassified by rule-matching' },
  { value: 'ambiguous_narrative', label: 'Ambiguous narrative' },
  { value: 'known_exception', label: 'Known exception for this client/deal' },
  { value: 'duplicate_reversal', label: 'Duplicate/reversal' },
  { value: 'other', label: 'Other' },
]

export async function resolveTransaction(
  dealId: string,
  rowId: string,
  newRole: string,
  analystInitials: string,
  reasonCategory: OverrideReasonCategory,
  reasonNote?: string
): Promise<{ success: boolean; remaining_count: number }> {
  const form = new FormData()
  form.append('row_id', rowId)
  form.append('new_role', newRole)
  form.append('analyst_initials', analystInitials)
  form.append('reason_category', reasonCategory)
  form.append('reason_note', reasonNote ?? '')
  const res = await fetchApiFormData(`${BASE}/deals/${dealId}/transactions/resolve`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Intelligence Query Interface ──────────────────────────────────────────────

export type QueryType = 'classification' | 'computation' | 'pattern'
export type UserRole = 'analyst' | 'officer'

export interface IntelligenceAskResponse {
  id: string
  response_text: string
  basis_sources: string[]
  computation_steps: string[]
}

export async function intelligenceAsk(
  dealId: string,
  query: string,
  queryType: QueryType,
  userRole: UserRole,
  analystInitials: string
): Promise<IntelligenceAskResponse> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/intelligence/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      query_type: queryType,
      user_role: userRole,
      analyst_initials: analystInitials,
    }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ExportSummary {
  deal_id: string
  deal_name: string
  company_name: string
  analyst_initials: string
  files_uploaded: number
  total_transactions: number
  override_count: number
  logged_entries: number
  tier: string
  has_snapshot: boolean
}

export async function getExportSummary(dealId: string): Promise<ExportSummary> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/export-summary`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getDeal(dealId: string): Promise<{ deal: Deal; analysis_runs: AnalysisRun[]; snapshots: Snapshot[] }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function downloadSnapshotPdf(dealId: string): Promise<Response> {
  return fetchApi(`${BASE}/deals/${dealId}/snapshot/pdf`)
}

export async function downloadReport(dealId: string): Promise<Response> {
  return fetchApi(`${BASE}/deals/${dealId}/report`)
}

export async function exportTransactionsCsvBlob(dealId: string): Promise<Response> {
  return fetchApi(`${BASE}/deals/${dealId}/export/transactions`)
}

export async function logIntelligenceEntry(
  dealId: string,
  entryId: string
): Promise<{ success: boolean; logged_count: number }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/intelligence/${entryId}/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface DealListItem {
  id: string
  name?: string
  company_name?: string
  analyst_initials?: string
  currency?: string
  created_at?: string
  [key: string]: unknown
}

export async function listDeals(userId: string): Promise<{ deals: DealListItem[] }> {
  const res = await fetchApi(`${BASE}/deals?created_by=${encodeURIComponent(userId)}`)
  if (!res.ok) return { deals: [] }
  return res.json()
}

export interface NeedsReviewItem {
  row_id: string
  txn_hash: string
  txn_date: string
  description: string
  signed_amount_cents: number
  entity_name?: string
  entity_id?: string
  role?: string
  flag_reason?: string
}

export async function getNeedsReview(dealId: string): Promise<{ transactions: NeedsReviewItem[]; total: number }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/transactions/needs-review`)
  if (!res.ok) return { transactions: [], total: 0 }
  return res.json()
}

export interface ReconciliationCashPosition {
  status?: string
  variance_pct?: number | null
  variance_kes?: number
  fiscal_year_end?: string
  [key: string]: unknown
}

export interface ReconciliationRevenue {
  assessment?: string
  gap_pct?: number | null
  fiscal_period?: string
  [key: string]: unknown
}

export interface ReconciliationExpenses {
  gap_pct?: number | null
  explanation?: string
  [key: string]: unknown
}

export interface ReconciliationLoanActivity {
  status?: string
  variance_pct?: number | null
  [key: string]: unknown
}

export interface ReconciliationAccountCoverage {
  status?: string
  coverage_pct?: number
  advisory_tier?: string
  missing_pct?: number
  [key: string]: unknown
}

export interface ReconciliationSection {
  tier?: string
  note?: string
  cash_position?: ReconciliationCashPosition
  revenue?: ReconciliationRevenue
  expenses?: ReconciliationExpenses
  loan_activity?: ReconciliationLoanActivity
  account_coverage?: ReconciliationAccountCoverage
  [key: string]: unknown
}

export interface ReconciliationResult {
  deal_id: string
  reconciliation: ReconciliationSection
}

export async function getReconciliation(dealId: string): Promise<ReconciliationResult> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/reconciliation`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Reconciliation failed' }))
    throw new Error(err.detail ?? 'Reconciliation failed')
  }
  return res.json()
}

export async function deleteDocument(documentId: string): Promise<{ deleted: boolean; document_id: string; deal_id: string }> {
  const res = await fetchApi(`${BASE}/documents/${documentId}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Delete failed' }))
    throw new Error(err.detail ?? 'Delete failed')
  }
  return res.json()
}

export interface MonthlyCashflowRow {
  month: string
  inflow_cents: number
  outflow_cents: number
  net_cents: number
}

export async function getMonthlyCashflow(dealId: string): Promise<{ monthly_cashflow: MonthlyCashflowRow[]; count: number }> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/analytics/monthly-cashflow`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load cashflow' }))
    throw new Error(err.detail ?? 'Failed to load cashflow')
  }
  return res.json()
}

export async function getCreditScoringInputs(dealId: string): Promise<Record<string, unknown>> {
  const res = await fetchApi(`${BASE}/deals/${dealId}/analytics/credit-scoring-inputs`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load credit scoring inputs' }))
    throw new Error(err.detail ?? 'Failed to load credit scoring inputs')
  }
  return res.json()
}