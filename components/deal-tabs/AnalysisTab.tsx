'use client';

import type { AnalysisRun, AuditedFinancialsRecord, ReconciliationSection } from '@/lib/v1-api';
import type { AnalysisState, EntityBreakdownRow, PipelineStage, QueuedStatement, StageStatus, DrillModalState } from './types';

const StatusDot = ({ status }: { status: StageStatus }) => {
  const colors: Record<StageStatus, string> = { done: 'var(--green)', active: '#818CF8', queued: 'var(--t2)', failed: 'var(--red)' };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: '50%', background: colors[status], flexShrink: 0 }}>
      {status === 'done' && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5L8 3" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      {status === 'active' && <span style={{ width: 6, height: 6, background: '#fff', borderRadius: '50%' }} />}
      {status === 'queued' && <span style={{ width: 6, height: 6, background: 'var(--t2)', borderRadius: '50%' }} />}
      {status === 'failed' && <span style={{ color: '#fff', fontSize: 10, fontWeight: 700 }}>!</span>}
    </span>
  );
};

export interface AnalysisTabProps {
  analysisState: AnalysisState;
  run: AnalysisRun | undefined;
  isProcessing: boolean;
  statementQueue: QueuedStatement[];
  rawTransactions: Array<Record<string, unknown>>;
  pipelineStages: PipelineStage[];
  monthlyCashflow: Array<Record<string, unknown>>;
  creditScoringInputs: Record<string, unknown> | null;
  currency: string | null;
  dealCurrency?: string;
  formatCents: (c: number) => string;
  reconciliationDetail: ReconciliationSection | null;
  auditedFinancialsList: AuditedFinancialsRecord[];
  entityBreakdownByCategory: Array<{ role: string; rows: EntityBreakdownRow[]; totalCents: number }>;
  entityBreakdown: EntityBreakdownRow[];
  needsReviewItems: Array<Record<string, unknown>>;
  onGoToDocuments: () => void;
  onGoToQueue: () => void;
  onDrill: (modal: DrillModalState) => void;
  errorMsg?: string;
  onRetry?: () => void;
}

export default function AnalysisTab({
  analysisState,
  run,
  isProcessing,
  statementQueue,
  rawTransactions,
  pipelineStages,
  monthlyCashflow,
  creditScoringInputs,
  currency,
  dealCurrency,
  formatCents,
  reconciliationDetail,
  auditedFinancialsList,
  entityBreakdownByCategory,
  entityBreakdown,
  needsReviewItems,
  onGoToDocuments,
  onGoToQueue,
  onDrill,
  errorMsg,
  onRetry,
}: AnalysisTabProps) {
  const csi = creditScoringInputs as Record<string, unknown> | null;
  const confPct = run ? (run.final_confidence_bp / 100).toFixed(1) : null;
  const tier = run?.tier ?? null;
  const roleBadgeColor: Record<string, string> = {
    supplier: 'var(--accent)', revenue_operational: 'var(--green)', revenue_non_operational: '#22D3EE',
    payroll: 'var(--amber)', needs_review: 'var(--amber)', loan_repayment: 'var(--red)', other: 'var(--t2)',
  };
  return (
    <div>
      {analysisState === 'idle' && !run && (
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: 'var(--t1)', marginBottom: 16 }}>No analysis run yet. Upload documents and initialise the pipeline.</div>
          <button onClick={onGoToDocuments} style={{ padding: '9px 18px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>← Go to Documents</button>
        </div>
      )}
      {analysisState === 'error' && !run && (
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: 'var(--red)', marginBottom: 16, maxWidth: 480, marginLeft: 'auto', marginRight: 'auto' }}>{errorMsg || 'Something went wrong loading this analysis.'}</div>
          {onRetry && (
            <button onClick={onRetry} style={{ padding: '9px 18px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>Retry</button>
          )}
        </div>
      )}
      {(isProcessing || run) && (
        <>
          {/* Run meta + confidence badge */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            <div style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace", display: 'flex', gap: 14 }}>
              {run && <><span>{statementQueue.length} source document{statementQueue.length !== 1 ? 's' : ''}</span><span>·</span><span>{rawTransactions.length} transactions</span></>}
            </div>
            {confPct && (
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                {/* <span style={{ fontSize: 28, fontWeight: 700, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace", lineHeight: 1 }}>{confPct}</span> */}
                <span style={{ fontSize: 11, color: 'var(--t1)' }}> CONFIDENCE</span>
                {tier && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', padding: '2px 8px', borderRadius: 3, letterSpacing: '0.08em' }}>{tier.toUpperCase()}</span>}
              </div>
            )}
          </div>

          {/* Pipeline stages */}
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)' }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>PIPELINE STAGES</span>
              <span style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>Deterministic · No AI in financial pipeline</span>
            </div>
            <div style={{ padding: '0 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 120px 80px', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                {['STAGE', 'DETAIL', 'PROGRESS', 'STATUS'].map((h) => <span key={h} style={{ fontSize: 10, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>)}
              </div>
              {pipelineStages.map((stage) => (
                <div key={stage.name} style={{ display: 'grid', gridTemplateColumns: '200px 1fr 120px 80px', gap: 12, padding: '14px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <StatusDot status={stage.status} />
                    <span style={{ fontSize: 13, color: stage.status === 'queued' ? 'var(--t2)' : 'var(--t0)' }}>{stage.name}</span>
                  </div>
                  <div>
                    <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{stage.detail}</span>
                    {stage.status === 'active' && stage.pct !== undefined && (
                      <div style={{ marginTop: 4, height: 3, background: 'var(--s3)', borderRadius: 2, overflow: 'hidden', width: 200 }}>
                        <div style={{ height: '100%', width: `${stage.pct}%`, background: 'var(--accent)', borderRadius: 2, transition: 'width 0.5s' }} />
                      </div>
                    )}
                  </div>
                  <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{stage.progress}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', color: { done: 'var(--green)', active: '#818CF8', queued: 'var(--t2)', failed: 'var(--red)' }[stage.status] }}>
                    {stage.status === 'done' ? 'DONE' : stage.status === 'active' ? `${stage.pct ?? '…'}%` : stage.status === 'failed' ? 'FAILED' : 'QUEUED'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Rich results — only when done */}
          {run && analysisState === 'done' && (
            <>
              {/* 01 · Credit Scoring Inputs */}
              <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden', marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)', borderLeft: '3px solid var(--green)' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>01 · CREDIT SCORING INPUTS</span>
                  <span style={{ fontSize: 10, color: 'var(--green)', background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.2)', padding: '2px 8px', borderRadius: 3, letterSpacing: '0.06em' }}>Parity Format</span>
                </div>
                <div style={{ padding: '0 20px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 200px 1fr', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                    {['SCORING METRIC', 'VALUE', 'BASIS'].map((h) => <span key={h} style={{ fontSize: 10, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>)}
                  </div>
                  {(() => {
                    const fmt = (cents: unknown) => cents != null ? new Intl.NumberFormat('en-KE', { style: 'currency', currency: currency ?? dealCurrency ?? 'KES', minimumFractionDigits: 2 }).format(Number(cents) / 100) : '—';
                    const fmtBps = (bps: unknown) => bps != null ? `${(Number(bps) / 100).toFixed(1)}%` : '—';
                    const rows = [
                      { label: 'Average Monthly Inflow', value: csi ? fmt(csi.average_monthly_inflow_cents) : (monthlyCashflow.length > 0 ? fmt(monthlyCashflow.reduce((s: number, m: any) => s + (m.inflow_cents || 0), 0) / monthlyCashflow.length) : '—'), basis: '12-month arithmetic mean', positive: true },
                      { label: 'Median Monthly Inflow', value: csi ? fmt(csi.median_monthly_inflow_cents) : '—', basis: '12-month median', positive: true },
                      { label: 'Average Monthly Outflow', value: csi ? fmt(csi.average_monthly_outflow_cents) : '—', basis: '12-month arithmetic mean', positive: null },
                      { label: 'Average Net Monthly Position', value: csi ? fmt(csi.average_net_monthly_cents) : '—', basis: 'Inflow minus outflow mean', positive: csi ? Number(csi.average_net_monthly_cents) >= 0 : null },
                      { label: 'Peak Net Position', value: csi ? fmt(csi.peak_net_position_cents) : '—', basis: 'Best month', positive: true },
                      { label: 'Trough Net Position', value: csi ? fmt(csi.trough_net_position_cents) : '—', basis: 'Worst month', positive: csi ? Number(csi.trough_net_position_cents) >= 0 : false },
                      { label: 'Revenue Growth', value: csi ? fmtBps(csi.revenue_growth_bps) : '—', basis: 'First vs last month with inflow', positive: csi ? Number(csi.revenue_growth_bps) >= 0 : null },
                      { label: 'Loan Repayment Burden', value: csi ? fmtBps(csi.loan_repayment_burden_bps) : '—', basis: '% of total outflows', positive: null },
                      { label: 'Payroll Stability', value: csi ? (csi.payroll_stability as string) || 'NOT DETECTED' : 'NOT DETECTED', basis: csi?.payroll_stability === 'CONSISTENT' ? 'Consistent monthly pattern' : 'No payroll pattern in statement', positive: csi?.payroll_stability === 'CONSISTENT' ? true : csi?.payroll_stability ? null : null },
                      { label: 'KRA Compliance', value: csi ? (csi.kra_compliance as string) || 'NOT DETECTED' : 'NOT DETECTED', basis: (csi?.kra_note as string) || 'No KRA/VAT/PAYE transactions found', positive: csi?.kra_compliance === 'PASS' ? true : csi?.kra_compliance === 'GAPS_DETECTED' ? false : null },
                    ];
                    return rows.map((row) => (
                      <div key={row.label} style={{ display: 'grid', gridTemplateColumns: '1fr 200px 1fr', gap: 12, padding: '11px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                        <span style={{ fontSize: 13, color: 'var(--t0)' }}>{row.label}</span>
                        <span style={{ fontSize: 13, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, color: row.positive === true ? 'var(--green)' : row.positive === false ? 'var(--red)' : 'var(--t0)' }}>{row.value}</span>
                        <span style={{ fontSize: 12, color: 'var(--t1)' }}>{row.basis}</span>
                      </div>
                    ));
                  })()}
                </div>
              </div>

              {/* MoM Cashflow */}
              {monthlyCashflow.length > 0 && (
                <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden', marginBottom: 16 }}>
                  <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--s3)', borderLeft: '3px solid #818CF8' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>02 · MONTH-ON-MONTH CASHFLOW</span>
                  </div>
                  <div style={{ padding: '0 20px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 1fr 1fr', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                      {['MONTH', 'INFLOW', 'OUTFLOW', 'NET'].map((h) => <span key={h} style={{ fontSize: 10, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>)}
                    </div>
                    {/* No count cap here — monthlyCashflow already IS the real observed
                        period from GET /analytics/monthly-cashflow (backend/v1/analytics.py's
                        monthly_cashflow(), unbounded). A hardcoded .slice(0, 12) previously
                        silently dropped any statement period longer than 12 months (e.g. a
                        13-month cross-year lookback) — same "12 months" assumption bug fixed
                        in the exported PDF's snapshot_html_renderer.py, independently present
                        here since this tab reads the live endpoint directly, not the PDF. */}
                    {(monthlyCashflow as Array<Record<string, unknown>>).map((m) => {
                      const net = Number(m.net_cents ?? 0);
                      return (
                        <div key={m.month as string} style={{ display: 'grid', gridTemplateColumns: '100px 1fr 1fr 1fr', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                          <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{m.month as string}</span>
                          <span style={{ fontSize: 13, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace" }}>{formatCents(Number(m.inflow_cents ?? 0))}</span>
                          <span style={{ fontSize: 13, color: 'var(--red)', fontFamily: "'IBM Plex Mono', monospace" }}>{formatCents(Number(m.outflow_cents ?? 0))}</span>
                          <span style={{ fontSize: 13, fontWeight: 600, color: net >= 0 ? 'var(--green)' : 'var(--red)', fontFamily: "'IBM Plex Mono', monospace" }}>{formatCents(net)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Reconciliation */}
              {run && (() => {
                const STATUS_COLORS: Record<string, string> = {
                  OK: 'var(--green)',
                  HIGH_CONFIDENCE: 'var(--green)',
                  EXACT_MATCH: 'var(--green)',
                  ACCEPTABLE: 'var(--green)',
                  ACCEPTABLE_VARIANCE: 'var(--green)',
                  MEDIUM_CONFIDENCE: 'var(--amber)',
                  LOW: 'var(--amber)',
                  NOT_RUN: 'var(--t1)',
                  SKIPPED: 'var(--t1)',
                  INSUFFICIENT_DATA: 'var(--t1)',
                  LOW_CONFIDENCE: 'var(--red)',
                  FAILED_OVERLAP: 'var(--red)',
                  SIGNIFICANT_VARIANCE: 'var(--red)',
                  VARIANCE: 'var(--red)',
                  ERROR: 'var(--red)',
                };
                const reconColor = STATUS_COLORS[run.reconciliation_status] ?? 'var(--t1)';
                const RECON_BASIS: Record<string, string> = {
                  OK: 'Declared accrual revenue matches bank-detected operational inflow within tolerance',
                  FAILED_OVERLAP: 'Bank statement period covers less than 60% of the declared accrual period — result not reliable',
                  NOT_RUN: 'No accrual revenue or accrual period declared for this deal — reconciliation not run',
                  LOW: 'Fiscal-year reconciliation ran with LOW_CONFIDENCE tier — see breakdown below',
                };
                const fmtKes = (v: unknown) =>
                  v != null ? new Intl.NumberFormat('en-KE', { style: 'currency', currency: currency ?? dealCurrency ?? 'KES', minimumFractionDigits: 2 }).format(Number(v)) : '—';
                const fmtPct = (v: unknown) => v != null ? `${Number(v)}%` : '—';

                type ReconRow = { check: string; result: string; basis: string; color?: string };
                const detailRows: ReconRow[] = [];
                if (reconciliationDetail) {
                  detailRows.push({
                    check: 'Fiscal-Year Reconciliation Tier',
                    result: reconciliationDetail.tier ?? '—',
                    basis: 'Combines cash position, loan activity and account coverage vs audited financials',
                    color: STATUS_COLORS[reconciliationDetail.tier ?? ''] ?? 'var(--t0)',
                  });
                  const cash = reconciliationDetail.cash_position;
                  if (cash && cash.status !== 'SKIPPED' && cash.status !== 'ERROR') {
                    detailRows.push({
                      check: 'Cash Position (FY-end)',
                      result: cash.status ?? '—',
                      basis: `Bank ${fmtKes(cash.total_bank_kes)} vs Declared ${fmtKes(cash.total_declared_kes)}${cash.variance_pct != null ? ` · variance ${fmtPct(cash.variance_pct)}` : ''}`,
                      color: STATUS_COLORS[cash.status ?? ''] ?? 'var(--t0)',
                    });
                  } else if (cash?.reason) {
                    detailRows.push({ check: 'Cash Position (FY-end)', result: cash.status ?? '—', basis: String(cash.reason), color: 'var(--t1)' });
                  }
                  const revenue = reconciliationDetail.revenue;
                  if (revenue && revenue.status !== 'SKIPPED' && revenue.status !== 'ERROR') {
                    detailRows.push({
                      check: 'Revenue (FY)',
                      result: fmtPct(revenue.gap_pct),
                      basis: revenue.assessment ?? '—',
                    });
                  } else if (revenue?.reason) {
                    detailRows.push({ check: 'Revenue (FY)', result: 'SKIPPED', basis: String(revenue.reason), color: 'var(--t1)' });
                  }
                  const expenses = reconciliationDetail.expenses;
                  if (expenses && expenses.status !== 'SKIPPED' && expenses.status !== 'ERROR') {
                    detailRows.push({
                      check: 'Expenses (FY)',
                      result: fmtPct(expenses.gap_pct),
                      basis: expenses.explanation ?? '—',
                    });
                  } else if (expenses?.reason) {
                    detailRows.push({ check: 'Expenses (FY)', result: 'SKIPPED', basis: String(expenses.reason), color: 'var(--t1)' });
                  }
                  const loans = reconciliationDetail.loan_activity;
                  if (loans && loans.status !== 'SKIPPED' && loans.status !== 'ERROR') {
                    detailRows.push({
                      check: 'Loan Activity (FY)',
                      result: loans.status ?? '—',
                      basis: loans.variance_pct != null ? `Variance: ${fmtPct(loans.variance_pct)}` : '—',
                      color: STATUS_COLORS[loans.status ?? ''] ?? 'var(--t0)',
                    });
                  } else if (loans?.reason) {
                    detailRows.push({ check: 'Loan Activity (FY)', result: 'SKIPPED', basis: String(loans.reason), color: 'var(--t1)' });
                  }
                  const coverage = reconciliationDetail.account_coverage;
                  if (coverage && coverage.status !== 'SKIPPED' && coverage.status !== 'ERROR') {
                    detailRows.push({
                      check: 'Account Coverage',
                      result: coverage.coverage_pct != null ? `${coverage.coverage_pct}%` : '—',
                      basis: coverage.advisory_tier ? `Advisory: ${coverage.advisory_tier}` : '—',
                      color: coverage.advisory_tier === 'CRITICAL' ? 'var(--red)' : coverage.advisory_tier === 'NEGLIGIBLE' ? 'var(--green)' : 'var(--amber)',
                    });
                  } else if (coverage?.reason) {
                    detailRows.push({ check: 'Account Coverage', result: 'SKIPPED', basis: String(coverage.reason), color: 'var(--t1)' });
                  }
                }

                return (
                  <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden', marginBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)', borderLeft: `3px solid ${reconColor}` }}>
                      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>03 · RECONCILIATION</span>
                      <span style={{ fontSize: 10, color: reconColor, background: `${reconColor}18`, border: `1px solid ${reconColor}33`, padding: '2px 8px', borderRadius: 3, letterSpacing: '0.06em' }}>{run.reconciliation_status}</span>
                    </div>
                    <div style={{ padding: '0 20px' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 190px 1.4fr', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                        {['CHECK', 'RESULT', 'BASIS'].map((h) => <span key={h} style={{ fontSize: 10, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>)}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 190px 1.4fr', gap: 12, padding: '11px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                        <span style={{ fontSize: 13, color: 'var(--t0)' }}>Accrual Revenue vs Bank Inflow</span>
                        <span style={{ fontSize: 13, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, color: run.reconciliation_pct_bp != null ? 'var(--green)' : 'var(--t1)', whiteSpace: 'nowrap' }}>
                          {run.reconciliation_pct_bp != null ? `${(run.reconciliation_pct_bp / 100).toFixed(1)}%` : '—'}
                        </span>
                        <span style={{ fontSize: 12, color: 'var(--t1)' }}>{RECON_BASIS[run.reconciliation_status] ?? '—'}</span>
                      </div>
                      {detailRows.map((row) => (
                        <div key={row.check} style={{ display: 'grid', gridTemplateColumns: '1fr 190px 1.4fr', gap: 12, padding: '11px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                          <span style={{ fontSize: 13, color: 'var(--t0)' }}>{row.check}</span>
                          <span style={{ fontSize: 13, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, color: row.color ?? 'var(--t0)', whiteSpace: 'nowrap' }}>{row.result}</span>
                          <span style={{ fontSize: 12, color: 'var(--t1)' }}>{row.basis}</span>
                        </div>
                      ))}
                      {!reconciliationDetail && auditedFinancialsList.length === 0 && (
                        <div style={{ padding: '11px 0', fontSize: 12, color: 'var(--t1)' }}>
                          Upload audited or management financials to unlock the fiscal-year reconciliation breakdown (cash position, revenue, expenses, loan activity, account coverage).
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* Entity Breakdown + Needs Review */}
              <div style={{ display: 'grid', gridTemplateColumns: needsReviewItems.length > 0 ? '1fr 1fr' : '1fr', gap: 16, marginBottom: 16 }}>
                {/* Entity Breakdown */}
                {entityBreakdownByCategory.length > 0 && (
                  <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)', borderLeft: '3px solid var(--accent)' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>ENTITY BREAKDOWN</span>
                      <span style={{ fontSize: 10, color: 'var(--accent)', background: 'rgba(20,184,166,0.1)', border: '1px solid rgba(20,184,166,0.2)', padding: '2px 7px', borderRadius: 3, letterSpacing: '0.06em' }}>ONTOLOGY v2.0</span>
                    </div>
                    <div style={{ padding: '0 20px' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 120px 50px', gap: 8, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                        {['ENTITY', 'ROLE', 'AMOUNT', 'TXNS'].map((h) => <span key={h} style={{ fontSize: 10, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.1em' }}>{h}</span>)}
                      </div>
                      {entityBreakdown.slice(0, 10).map((r) => (
                        <div key={r.entityId} onClick={() => {
                          const txns = (rawTransactions as Array<Record<string, unknown>>).filter(t => String(t.entity_id ?? '') === r.entityId || String(t.entity_name ?? '') === r.entityName);
                          onDrill({ title: r.entityName, color: 'var(--accent)', rows: txns, type: 'txn' });
                        }} style={{ display: 'grid', gridTemplateColumns: '1fr 100px 120px 50px', gap: 8, padding: '10px 0', borderBottom: '1px solid var(--s3)', alignItems: 'center', cursor: 'pointer', transition: 'background 0.15s' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(20,184,166,0.06)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <span style={{ fontSize: 12, color: r.role === 'needs_review' ? 'var(--amber)' : 'var(--t0)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: r.role === 'needs_review' ? 600 : 400 }}>{r.entityName}</span>
                          <span style={{ fontSize: 10, fontWeight: 600, color: roleBadgeColor[r.role] ?? 'var(--t2)', background: `${roleBadgeColor[r.role] ?? 'var(--t2)'}18`, padding: '2px 5px', borderRadius: 3, letterSpacing: '0.04em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.role.replace(/_/g, '_')}</span>
                          <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{formatCents(r.totalAbsCents)}</span>
                          <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{r.txnCount}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Items Requiring Review */}
                {needsReviewItems.length > 0 && (
                  <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--s3)', borderLeft: '3px solid var(--amber)' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>ITEMS REQUIRING REVIEW</span>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)', padding: '2px 7px', borderRadius: 3 }}>{needsReviewItems.length} flagged</span>
                        <button onClick={onGoToQueue} style={{ fontSize: 10, color: 'var(--accent)', background: 'transparent', border: '1px solid rgba(20,184,166,0.3)', borderRadius: 3, padding: '2px 8px', cursor: 'pointer' }}>Review →</button>
                      </div>
                    </div>
                    <div style={{ padding: '8px 0' }}>
                      {needsReviewItems.slice(0, 5).map((item, idx) => (
                        <div key={(item.row_id as string) ?? idx} style={{ padding: '12px 20px', borderBottom: '1px solid var(--s3)' }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--amber)', display: 'inline-block', flexShrink: 0 }} />
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--amber)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(item.entity_name || item.description) as string}</span>
                              </div>
                              <div style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>
                                needs_review · {item.txn_date as string}
                                {item.flag_reason != null && <div style={{ color: 'var(--amber)', marginTop: 2, fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 11 }}>{String(item.flag_reason)}</div>}
                              </div>
                            </div>
                            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--red)', fontFamily: "'IBM Plex Mono', monospace", flexShrink: 0 }}>{formatCents(Math.abs(Number(item.signed_amount_cents ?? 0)))}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Concentration: Suppliers / Revenue / Payroll */}
              {entityBreakdown.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
                  {[
                    { label: 'SUPPLIERS', role: 'supplier', color: 'var(--accent)' },
                    { label: 'REVENUE', roles: ['revenue_operational', 'revenue_non_operational'], color: 'var(--green)' },
                    { label: 'PAYROLL', role: 'payroll', color: 'var(--amber)' },
                  ].map((section) => {
                    const rows = entityBreakdown.filter((r) =>
                      section.role ? r.role === section.role : (section.roles ?? []).includes(r.role)
                    ).slice(0, 5);
                    return (
                      <div key={section.label} style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
                        <div onClick={() => {
                          const allRows = entityBreakdown.filter((r) =>
                            section.role ? r.role === section.role : (section.roles ?? []).includes(r.role)
                          );
                          const allTxns = (rawTransactions as Array<Record<string, unknown>>).filter(t => {
                            const eid = String(t.entity_id ?? '');
                            const ename = String(t.entity_name ?? '');
                            return allRows.some(r => r.entityId === eid || r.entityName === ename);
                          }).sort((a, b) => Math.abs(Number(b.signed_amount_cents ?? 0)) - Math.abs(Number(a.signed_amount_cents ?? 0)));
                          onDrill({ title: section.label, color: section.color, rows: allTxns, type: 'txn' });
                        }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--s3)', borderLeft: `3px solid ${section.color}`, cursor: 'pointer', transition: 'background 0.15s' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(20,184,166,0.06)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>{section.label}</span>
                          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)', background: 'rgba(20,184,166,0.1)', border: '1px solid rgba(20,184,166,0.3)', borderRadius: 4, padding: '2px 8px', letterSpacing: '0.02em', flexShrink: 0 }}>View all →</span>
                        </div>
                        <div style={{ padding: '4px 0' }}>
                          {rows.length === 0 && <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--t2)' }}>None detected</div>}
                          {rows.map((r) => (
                            <div key={r.entityId} onClick={() => {
                              const txns = (rawTransactions as Array<Record<string, unknown>>).filter(t => String(t.entity_id ?? '') === r.entityId || String(t.entity_name ?? '') === r.entityName);
                              onDrill({ title: `${section.label} — ${r.entityName}`, color: section.color, rows: txns, type: 'txn' });
                            }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 16px', borderBottom: '1px solid var(--s3)', cursor: 'pointer', transition: 'background 0.15s' }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(20,184,166,0.06)')}
                              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                            >
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 12, color: 'var(--t0)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.entityName}</div>
                                <div style={{ fontSize: 10, color: section.color, fontFamily: "'IBM Plex Mono', monospace", marginTop: 2 }}>{(r.pctBps / 100).toFixed(1)}% of category</div>
                              </div>
                              <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace", flexShrink: 0 }}>{formatCents(r.totalAbsCents)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Debit / Credit lists */}
              {rawTransactions.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                  {[
                    { label: 'TOP DEBITS', filter: (t: Record<string,unknown>) => Number(t.signed_amount_cents ?? 0) < 0, color: 'var(--red)' },
                    { label: 'TOP CREDITS', filter: (t: Record<string,unknown>) => Number(t.signed_amount_cents ?? 0) > 0, color: 'var(--green)' },
                  ].map((section) => {
                    const txns = (rawTransactions as Array<Record<string,unknown>>)
                      .filter(section.filter)
                      .sort((a, b) => Math.abs(Number(b.signed_amount_cents ?? 0)) - Math.abs(Number(a.signed_amount_cents ?? 0)))
                      .slice(0, 8);
                    return (
                      <div key={section.label} style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
                        <div onClick={() => {
                          const allTxns = (rawTransactions as Array<Record<string, unknown>>)
                            .filter(section.filter)
                            .sort((a, b) => Math.abs(Number(b.signed_amount_cents ?? 0)) - Math.abs(Number(a.signed_amount_cents ?? 0)));
                          onDrill({ title: section.label, color: section.color, rows: allTxns, type: 'txn' });
                        }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--s3)', borderLeft: `3px solid ${section.color}`, cursor: 'pointer', transition: 'background 0.15s' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(20,184,166,0.06)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>{section.label}</span>
                          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)', background: 'rgba(20,184,166,0.1)', border: '1px solid rgba(20,184,166,0.3)', borderRadius: 4, padding: '2px 8px', letterSpacing: '0.02em', flexShrink: 0 }}>View all →</span>
                        </div>
                        <div style={{ padding: '4px 0' }}>
                          {txns.map((t, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderBottom: '1px solid var(--s3)', gap: 8 }}>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 12, color: 'var(--t0)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(t.description || t.narrative || '—') as string}</div>
                                <div style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>{t.txn_date as string}</div>
                              </div>
                              <span style={{ fontSize: 13, fontWeight: 600, color: section.color, fontFamily: "'IBM Plex Mono', monospace", flexShrink: 0 }}>{formatCents(Math.abs(Number(t.signed_amount_cents ?? 0)))}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
