import type { AnalysisRun, Entity, ExportResponse, DocumentListItem, Snapshot, TxnEntityMapping } from '@/lib/v1-api';
import type { AnalysisState, EntityBreakdownRow, PipelineStage, QueuedStatement } from '@/components/deal-tabs/types';
import type { AnalystStatusStage } from '@/components/AnalystStatus';

/** Maps a PIPELINE STAGES row name (see computePipelineStages below) to its AnalystStatus phrase set. */
const STAGE_NAME_TO_ANALYST_STAGE: Record<string, AnalystStatusStage> = {
  'Document ingestion': 'ingestion',
  'Transaction parsing': 'ingestion',
  'Classification': 'classification',
  'Entity extraction': 'classification',
  'Reconciliation': 'reconciliation',
  'Confidence scoring': 'reconciliation',
  'Snapshot generation': 'snapshot',
};

/** The AnalystStatus phrase set for whichever pipeline stage is currently 'active', or undefined if none is. */
export function activeAnalystStage(stages: PipelineStage[]): AnalystStatusStage | undefined {
  const active = stages.find((s) => s.status === 'active');
  return active ? STAGE_NAME_TO_ANALYST_STAGE[active.name] : undefined;
}

/** Normalize API status (list + status endpoints; lease may surface failed). */
export function apiDocumentStatus(doc: Pick<DocumentListItem, 'status'>): 'completed' | 'failed' | 'processing' {
  const s = String(doc.status ?? '').toLowerCase();
  if (s === 'completed') return 'completed';
  if (s === 'failed') return 'failed';
  return 'processing';
}

/** Basis-point percentage: (entity_amount_cents * 10000) // total_category_cents. No floats. */
export function pctBpsFromCents(entityCents: number, totalCategoryCents: number): number {
  if (totalCategoryCents <= 0) return 0;
  return Math.floor((entityCents * 10000) / totalCategoryCents);
}

/** Ensure percentages sum to 10000 bps (100.0%). Apply residual to largest entity. */
export function normalizePctBpsTo100(
  rows: Array<{ totalAbsCents: number; pctBps: number }>
): number[] {
  const totalBps = rows.reduce((s, r) => s + r.pctBps, 0);
  const residual = 10000 - totalBps;
  if (residual === 0) return rows.map((r) => r.pctBps);
  const sorted = [...rows].map((r, i) => ({ ...r, i })).sort((a, b) => b.totalAbsCents - a.totalAbsCents);
  const result = rows.map((r) => r.pctBps);
  result[sorted[0].i] = result[sorted[0].i] + residual;
  return result;
}

export function computeEntityBreakdownByCategory(
  exportData: ExportResponse | null,
  rawTransactions: Array<Record<string, unknown>>,
  entities: Entity[],
  txnMap: TxnEntityMapping[]
): Array<{ role: string; rows: EntityBreakdownRow[]; totalCents: number }> {
  if (!exportData || rawTransactions.length === 0) return [];
  const byEntity: Record<
    string,
    { name: string; role: string; totalCents: number; count: number }
  > = {};
  const txnById: Record<string, number> = {};
  for (const t of rawTransactions) {
    const amt = Math.abs(Number(t.signed_amount_cents ?? 0));
    const tid = t.txn_id as string;
    const id = t.id as string | undefined;
    txnById[tid] = amt;
    if (id) txnById[id] = amt;
  }
  for (const m of txnMap) {
    const eid = m.entity_id;
    const ent = entities.find((e) => e.entity_id === eid);
    const absCents = txnById[m.txn_id as string] ?? 0;
    if (!byEntity[eid]) {
      byEntity[eid] = {
        name: ent?.display_name ?? eid,
        role: (m.role as string) ?? 'other',
        totalCents: 0,
        count: 0,
      };
    }
    byEntity[eid].totalCents += absCents;
    byEntity[eid].count += 1;
  }
  const byRole = new Map<string, Array<{ entityId: string; entityName: string; role: string; totalAbsCents: number; txnCount: number }>>();
  for (const [entityId, v] of Object.entries(byEntity)) {
    const list = byRole.get(v.role) ?? [];
    list.push({
      entityId,
      entityName: v.name,
      role: v.role,
      totalAbsCents: v.totalCents,
      txnCount: v.count,
    });
    byRole.set(v.role, list);
  }
  const result: Array<{ role: string; rows: EntityBreakdownRow[]; totalCents: number }> = [];
  for (const [role, list] of Array.from(byRole.entries())) {
    const sorted = list.sort((a, b) => b.totalAbsCents - a.totalAbsCents);
    const totalCategoryCents = sorted.reduce((s, r) => s + r.totalAbsCents, 0);
    let pctBpsList: number[];
    if (totalCategoryCents <= 0) {
      pctBpsList = sorted.map(() => 0);
    } else if (sorted.length === 1) {
      pctBpsList = [10000];
    } else {
      const rawBps = sorted.map((r) => pctBpsFromCents(r.totalAbsCents, totalCategoryCents));
      pctBpsList = normalizePctBpsTo100(sorted.map((r, i) => ({ totalAbsCents: r.totalAbsCents, pctBps: rawBps[i] })));
    }
    const rows: EntityBreakdownRow[] = sorted.map((r, i) => ({
      ...r,
      pctBps: pctBpsList[i],
    }));
    result.push({ role, rows, totalCents: totalCategoryCents });
  }
  result.sort((a, b) => b.totalCents - a.totalCents);
  return result;
}

export function computePipelineStages(
  analysisState: AnalysisState,
  statementQueue: QueuedStatement[],
  rawTransactions: Array<Record<string, unknown>>,
  entities: Entity[],
  run: AnalysisRun | undefined,
  snapshot: Snapshot | undefined
): PipelineStage[] {
  const totalDocs = statementQueue.length;
  const totalTxn = rawTransactions.length || 170;
  const totalEntities = entities.length || 21;
  const doneEntities = Math.max(Math.floor(totalEntities * 0.67), 0);
  if (analysisState === 'idle') return [
    { name: 'Document ingestion', detail: `${totalDocs} documents · SHA256 · canonicalised`, progress: `${totalDocs} / ${totalDocs}`, status: 'queued' },
    { name: 'Transaction parsing', detail: 'Layout detection · row parsing · 0 errors', progress: '— / —', status: 'queued' },
    { name: 'Classification', detail: 'Ontology v2.0 · 25 roles · integer arithmetic', progress: '— / —', status: 'queued' },
    { name: 'Entity extraction', detail: 'Dedup via clean display name · collapse repeats', progress: '— / —', status: 'queued' },
    { name: 'Reconciliation', detail: 'Declared vs bank inflow · awaiting entity extraction', progress: '—', status: 'queued' },
    { name: 'Confidence scoring', detail: 'Depends on reconciliation delta', progress: '—', status: 'queued' },
    { name: 'Snapshot generation', detail: 'SHA256 dual hash · immutable · sealed', progress: '—', status: 'queued' },
  ];
  if (analysisState === 'uploading') return [
    { name: 'Document ingestion', detail: `Uploading ${totalDocs} documents…`, progress: `0 / ${totalDocs}`, status: 'active', pct: 20 },
    { name: 'Transaction parsing', detail: 'Layout detection · row parsing · 0 errors', progress: '— / —', status: 'queued' },
    { name: 'Classification', detail: 'Ontology v2.0 · 25 roles · integer arithmetic', progress: '— / —', status: 'queued' },
    { name: 'Entity extraction', detail: 'Dedup via clean display name · collapse repeats', progress: '— / —', status: 'queued' },
    { name: 'Reconciliation', detail: 'Declared vs bank inflow · awaiting entity extraction', progress: '—', status: 'queued' },
    { name: 'Confidence scoring', detail: 'Depends on reconciliation delta', progress: '—', status: 'queued' },
    { name: 'Snapshot generation', detail: 'SHA256 dual hash · immutable · sealed', progress: '—', status: 'queued' },
  ];
  if (analysisState === 'polling') return [
    { name: 'Document ingestion', detail: `${totalDocs} documents · SHA256 · canonicalised`, progress: `${totalDocs} / ${totalDocs}`, status: 'done' },
    { name: 'Transaction parsing', detail: 'Layout detection · row parsing · 0 errors', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Classification', detail: 'Ontology v2.0 · 25 roles · integer arithmetic', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Entity extraction', detail: 'Dedup via clean display name · collapse repeats', progress: `${doneEntities} / ${totalEntities}`, status: 'active', pct: 67 },
    { name: 'Reconciliation', detail: 'Declared vs bank inflow · awaiting entity extraction', progress: '—', status: 'queued' },
    { name: 'Confidence scoring', detail: 'Depends on reconciliation delta', progress: '—', status: 'queued' },
    { name: 'Snapshot generation', detail: 'SHA256 dual hash · immutable · sealed', progress: '—', status: 'queued' },
  ];
  if (analysisState === 'exporting') return [
    { name: 'Document ingestion', detail: `${totalDocs} documents · SHA256 · canonicalised`, progress: `${totalDocs} / ${totalDocs}`, status: 'done' },
    { name: 'Transaction parsing', detail: 'Layout detection · row parsing · 0 errors', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Classification', detail: 'Ontology v2.0 · 25 roles · integer arithmetic', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Entity extraction', detail: 'Dedup via clean display name · collapse repeats', progress: `${totalEntities} / ${totalEntities}`, status: 'done' },
    { name: 'Reconciliation', detail: run ? `Status: ${run.reconciliation_status}` : 'Declared vs bank inflow · awaiting entity extraction', progress: run && run.reconciliation_pct_bp != null ? `${(run.reconciliation_pct_bp / 100).toFixed(1)}%` : '—', status: 'done' },
    { name: 'Confidence scoring', detail: 'Depends on reconciliation delta', progress: '—', status: 'active', pct: 80 },
    { name: 'Snapshot generation', detail: 'SHA256 dual hash · immutable · sealed', progress: '—', status: 'queued' },
  ];
  // done or error
  return [
    { name: 'Document ingestion', detail: `${totalDocs} documents · SHA256 · canonicalised`, progress: `${totalDocs} / ${totalDocs}`, status: 'done' },
    { name: 'Transaction parsing', detail: 'Layout detection · row parsing · 0 errors', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Classification', detail: 'Ontology v2.0 · 25 roles · integer arithmetic', progress: `${totalTxn} / ${totalTxn}`, status: 'done' },
    { name: 'Entity extraction', detail: 'Dedup via clean display name · collapse repeats', progress: `${totalEntities} / ${totalEntities}`, status: 'done' },
    { name: 'Reconciliation', detail: run ? `Status: ${run.reconciliation_status}` : 'Declared vs bank inflow · awaiting entity extraction', progress: run && run.reconciliation_pct_bp != null ? `${(run.reconciliation_pct_bp / 100).toFixed(1)}%` : '—', status: 'done' },
    { name: 'Confidence scoring', detail: run ? `Tier ${run.tier} · ${(run.final_confidence_bp / 100).toFixed(1)}% confidence` : 'Depends on reconciliation delta', progress: run ? `${(run.final_confidence_bp / 100).toFixed(1)}%` : '—', status: analysisState === 'error' ? 'failed' : 'done' },
    { name: 'Snapshot generation', detail: snapshot ? `SHA256 ${snapshot.sha256_hash.slice(0, 12)}… · sealed` : 'SHA256 dual hash · immutable · sealed', progress: snapshot ? '1 / 1' : '—', status: analysisState === 'error' ? 'queued' : 'done' },
  ];
}
