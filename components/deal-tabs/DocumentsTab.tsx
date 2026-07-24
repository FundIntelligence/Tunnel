'use client';

import { useState, useCallback } from 'react';
import { deleteDocument, patchAuditedFinancials,removeAuditedFinancials, AuditedFinancialsRemoveError } from '@/lib/v1-api';
import type { Deal, AuditedFinancialsRecord } from '@/lib/v1-api';
import type { AnalysisState, QueuedStatement } from './types';
import AnalystStatus from '@/components/AnalystStatus';

const MAX_STATEMENTS = 20;

interface ParserRequestDoc { docId: string; fileName: string; errorMessage: string }

const FileRow = ({
  item,
  accent,
  isUnknownFormat,
  onRequestParser,
  canRemove,
  onRemove,
}: {
  item: { id: string; fileName: string; status: QueuedStatement['status'] };
  accent: string;
  isUnknownFormat?: boolean;
  onRequestParser?: () => void;
  canRemove?: boolean;
  onRemove?: () => void;
}) => {
  const [removing, setRemoving] = useState(false);
  const statusLabel = { ready: 'INDEXED', processing: 'PROCESSING', uploading: 'UPLOADING', failed: isUnknownFormat ? 'NO PARSER' : 'FAILED' }[item.status];
  const statusColor = { ready: 'var(--green)', processing: '#818CF8', uploading: '#818CF8', failed: isUnknownFormat ? 'var(--amber)' : 'var(--red)' }[item.status];
  const statusBg = { ready: 'rgba(74,222,128,0.08)', processing: 'rgba(129,140,248,0.12)', uploading: 'rgba(129,140,248,0.12)', failed: isUnknownFormat ? 'rgba(245,158,11,0.1)' : 'rgba(248,113,113,0.12)' }[item.status];

  const handleRemove = async () => {
    if (!onRemove || removing) return;
    setRemoving(true);
    try {
      await deleteDocument(item.id);
      onRemove();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Delete failed';
      alert(`Could not remove document: ${msg}`);
      setRemoving(false);
    }
  };

  

  return (
    <div style={{ borderBottom: '1px solid var(--s3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0' }}>
        <span style={{ width: 20, height: 20, borderRadius: 4, background: item.status === 'ready' ? 'rgba(74,222,128,0.15)' : 'var(--s3)', border: `1px solid ${item.status === 'ready' ? accent : isUnknownFormat ? 'var(--amber)' : 'var(--t2)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          {item.status === 'ready' && <svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M2 5.5l2.5 2.5L9 3" stroke={accent} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
          {(item.status === 'processing' || item.status === 'uploading') && <span style={{ width: 8, height: 8, borderRadius: '50%', borderTop: `2px solid ${accent}`, borderRight: `2px solid transparent`, animation: 'spin 0.8s linear infinite', display: 'inline-block' }} />}
          {item.status === 'failed' && <span style={{ fontSize: 10, color: isUnknownFormat ? 'var(--amber)' : 'var(--red)', fontWeight: 700 }}>!</span>}
        </span>
        <span style={{ flex: 1, fontSize: 13, color: 'var(--t0)', fontFamily: "'IBM Plex Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.fileName}</span>
        <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', color: statusColor, background: statusBg, padding: '2px 7px', borderRadius: 3, flexShrink: 0 }}>{statusLabel}</span>
        {canRemove && onRemove && item.status !== 'uploading' && (
          <button
            onClick={handleRemove}
            disabled={removing}
            title="Remove document"
            style={{ marginLeft: 4, padding: '2px 6px', fontSize: 11, color: removing ? 'var(--t1)' : 'var(--t1)', background: 'transparent', border: 'none', cursor: removing ? 'not-allowed' : 'pointer', borderRadius: 3, lineHeight: 1, flexShrink: 0 }}
          >
            {removing ? '…' : '✕'}
          </button>
        )}
      </div>
      {/* Inline CTA for unsupported bank format */}
      {item.status === 'failed' && isUnknownFormat && onRequestParser && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 10, paddingLeft: 30 }}>
          <span style={{ fontSize: 11, color: 'var(--t1)' }}>Format not supported —</span>
          <button
            onClick={onRequestParser}
            style={{ fontSize: 11, fontWeight: 600, color: 'var(--amber)', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
          >
            Request parser →
          </button>
        </div>
      )}
    </div>
  );
};

const DropZone = ({ onFileDrop, label, formats }: { onFileDrop: (f: File) => void; label: string; formats: string }) => {
  const [dragging, setDragging] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) onFileDrop(f); }}
      onClick={() => { const el = document.createElement('input'); el.type = 'file'; el.accept = '.pdf,.csv,.xlsx,.docx'; el.onchange = (ev) => { const f = (ev.target as HTMLInputElement).files?.[0]; if (f) onFileDrop(f); }; el.click(); }}
      style={{ border: `1px dashed ${dragging ? 'var(--accent)' : 'var(--t2)'}`, borderRadius: 6, padding: '14px 12px', textAlign: 'center', cursor: 'pointer', background: dragging ? 'rgba(20,184,166,0.05)' : 'transparent', transition: 'all 0.15s', marginTop: 8 }}
    >
      <div style={{ fontSize: 12, color: 'var(--t1)' }}>+ {label}</div>
      <div style={{ fontSize: 10, color: 'var(--t2)', marginTop: 4, letterSpacing: '0.05em' }}>{formats}</div>
    </div>
  );
};

export interface DocumentsTabProps {
  deal: Deal | null;
  statementQueue: QueuedStatement[];
  bankQueue: QueuedStatement[];
  bankReady: number;
  unknownFormatDocIds: Set<string>;
  onRequestParser: (doc: ParserRequestDoc) => void;
  analysisState: AnalysisState;
  onBankDrop: (file: File) => Promise<void>;
  onRemoveStatement: (id: string) => void;
  auditedFinancialsList: AuditedFinancialsRecord[];
  declarationType: 'audited' | 'management';
  setDeclarationType: (t: 'audited' | 'management') => void;
  auditedConfirmForm: AuditedFinancialsRecord | null;
  setAuditedConfirmForm: React.Dispatch<React.SetStateAction<AuditedFinancialsRecord | null>>;
  auditedUploading: boolean;
  auditedUploadError: string;
  setAuditedUploadError: (s: string) => void;
  onAuditedDrop: (file: File) => Promise<void>;
  auditedSaving: boolean;
  setAuditedSaving: (b: boolean) => void;
  loadAuditedFinancials: (dealIdOverride?: string) => Promise<void>;
  queueHasPending: boolean;
  isProcessing: boolean;
  onInitialiseAnalysis: () => void;
  errorMsg: string;
}

export default function DocumentsTab({
  deal,
  statementQueue,
  bankQueue,
  bankReady,
  unknownFormatDocIds,
  onRequestParser,
  analysisState,
  onBankDrop,
  onRemoveStatement,
  auditedFinancialsList,
  declarationType,
  setDeclarationType,
  auditedConfirmForm,
  setAuditedConfirmForm,
  auditedUploading,
  auditedUploadError,
  setAuditedUploadError,
  onAuditedDrop,
  auditedSaving,
  setAuditedSaving,
  loadAuditedFinancials,
  queueHasPending,
  isProcessing,
  onInitialiseAnalysis,
  errorMsg,
}: DocumentsTabProps) {
  const [afRemoveTarget, setAfRemoveTarget] = useState<number | null>(null);
  const [afRemoveReason, setAfRemoveReason] = useState('');
  const [afRemoveError, setAfRemoveError] = useState('');
  const [afRemoving, setAfRemoving] = useState(false);
  
   const handleRemoveAuditedFinancials = useCallback(async (af: AuditedFinancialsRecord) => {
    if (!deal?.id || af.financial_year == null || afRemoving) return;
    const isConfirmed = !!af.confirmed_at;
    const reason = afRemoveReason.trim();
    if (isConfirmed && !reason) {
      setAfRemoveError('A reason is required to remove a confirmed record.');
      return;
    }
    setAfRemoving(true);
    setAfRemoveError('');
    try {
      await removeAuditedFinancials(deal.id, af.financial_year, {
        supersede: isConfirmed,
        reason: reason || undefined,
      });
      setAfRemoveTarget(null);
      setAfRemoveReason('');
      await loadAuditedFinancials(deal.id);
    } catch (err) {
      const msg =
        err instanceof AuditedFinancialsRemoveError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not remove record';
      setAfRemoveError(msg);
    } finally {
      setAfRemoving(false);
    }
  }, [deal, afRemoveReason, afRemoving, loadAuditedFinancials]);

  return (
    <div>
      {!deal && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: 'var(--t2)' }}>
          <div style={{ fontSize: 13, fontFamily: "'IBM Plex Mono', monospace" }}>No deal loaded — navigate from Deals →</div>
        </div>
      )}
      {deal && (
        <>
          {/* Two-column: Bank Statements + Audited Accounts */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {/* Bank Statements */}
            <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 20, borderTop: '2px solid var(--green)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>BANK STATEMENTS</span>
                {bankQueue.length > 0 && (
                  <span style={{ fontSize: 11, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace" }}>
                    {bankReady} / {bankQueue.length} ready
                  </span>
                )}
              </div>
              {bankQueue.map((item) => (
                <FileRow
                  key={item.id}
                  item={item}
                  accent="var(--green)"
                  isUnknownFormat={unknownFormatDocIds.has(item.id)}
                  onRequestParser={() => onRequestParser({ docId: item.id, fileName: item.fileName, errorMessage: 'Bank format not recognised' })}
                  canRemove={analysisState === 'idle' || analysisState === 'checking' || item.status === 'failed'}
                  onRemove={() => onRemoveStatement(item.id)}
                />
              ))}
              {bankQueue.length < MAX_STATEMENTS && (
                <DropZone onFileDrop={onBankDrop} label="Add bank statement" formats="KCB · EQUITY · NCBA · CO-OP · MPESA · PDF" />
              )}
            </div>

            {/* Audited / Management Accounts */}
            <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 20, borderTop: '2px solid var(--green)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>FINANCIAL ACCOUNTS</span>
                {auditedFinancialsList.length > 0 && (
                  <span style={{ fontSize: 11, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace" }}>
                    {auditedFinancialsList.length} FY record{auditedFinancialsList.length > 1 ? 's' : ''}
                  </span>
                )}
              </div>

              {/* Declaration type selector */}
              {!auditedConfirmForm && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 10, color: 'var(--t1)', marginBottom: 6, letterSpacing: '0.05em' }}>DECLARATION TYPE</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {(['audited', 'management'] as const).map((type) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => setDeclarationType(type)}
                        style={{
                          flex: 1,
                          padding: '7px 0',
                          fontSize: 11,
                          fontWeight: 600,
                          borderRadius: 5,
                          border: declarationType === type ? '1px solid var(--accent)' : '1px solid var(--b1)',
                          background: declarationType === type ? 'rgba(20,184,166,0.12)' : 'transparent',
                          color: declarationType === type ? 'var(--accent)' : 'var(--t1)',
                          cursor: 'pointer',
                          letterSpacing: '0.05em',
                        }}
                      >
                        {type === 'audited' ? 'Audited' : 'Management'}
                      </button>
                    ))}
                  </div>
                  {declarationType === 'management' && (
                    <div style={{ marginTop: 8, padding: '8px 10px', background: 'rgba(251,191,36,0.07)', border: '1px solid rgba(251,191,36,0.25)', borderRadius: 5 }}>
                      <div style={{ fontSize: 11, color: 'var(--amber)', fontWeight: 600, marginBottom: 2 }}>Management accounts — Parity Review required</div>
                      <div style={{ fontSize: 10, color: '#92400E' }}>Internally prepared statements apply stricter variance thresholds. Snapshot generation is blocked until Parity Review is complete.</div>
                    </div>
                  )}
                </div>
              )}

              {/* Existing extracted records */}
                {auditedFinancialsList.map((af) => (
                  <div key={af.financial_year} style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--t0)', fontFamily: "'IBM Plex Mono', monospace" }}>
                          FY {af.financial_year ?? '—'}
                        </span>
                        {af.declaration_type === 'management' && (
                          <span style={{ fontSize: 9, background: 'rgba(251,191,36,0.15)', color: 'var(--amber)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 3, padding: '1px 5px', letterSpacing: '0.05em' }}>MGMT</span>
                        )}
                        {!af.confirmed_at && (
                          <span style={{ fontSize: 9, background: 'rgba(245,158,11,0.12)', color: 'var(--amber)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 3, padding: '1px 5px', letterSpacing: '0.05em' }}>UNCONFIRMED</span>
                        )}
                      </div>
                      <span style={{ fontSize: 10, color: af.extraction_confidence && af.extraction_confidence >= 70 ? 'var(--green)' : 'var(--amber)', fontFamily: "'IBM Plex Mono', monospace" }}>
                        {af.extraction_confidence != null ? `${af.extraction_confidence}% confidence` : 'manual'}
                      </span>
                    </div>
                    <div style={{ marginTop: 6, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
                      {af.turnover_cents != null && (
                        <span style={{ fontSize: 11, color: 'var(--t1)' }}>Revenue: KES {(af.turnover_cents / 100).toLocaleString()}</span>
                      )}
                      {af.cash_and_equivalents_cents != null && (
                        <span style={{ fontSize: 11, color: 'var(--t1)' }}>Cash: KES {(af.cash_and_equivalents_cents / 100).toLocaleString()}</span>
                      )}
                      {af.profit_after_tax_cents != null && (
                        <span style={{ fontSize: 11, color: 'var(--t1)' }}>PAT: KES {(af.profit_after_tax_cents / 100).toLocaleString()}</span>
                      )}
                      {af.total_assets_cents != null && (
                        <span style={{ fontSize: 11, color: 'var(--t1)' }}>Assets: KES {(af.total_assets_cents / 100).toLocaleString()}</span>
                      )}
                    </div>
                    <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 14 }}>
                      <button
                        type="button"
                        onClick={() => setAuditedConfirmForm({ ...af })}
                        style={{ fontSize: 10, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      >
                        Edit details →
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setAfRemoveTarget(af.financial_year ?? null);
                          setAfRemoveReason('');
                          setAfRemoveError('');
                        }}
                        style={{ fontSize: 10, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      >
                        Remove
                      </button>
                    </div>

                    {afRemoveTarget === af.financial_year && (
                      <div style={{ marginTop: 8, padding: 10, background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.25)', borderRadius: 6 }}>
                        <div style={{ fontSize: 11, color: '#FCA5A5', marginBottom: 6, lineHeight: 1.4 }}>
                          {af.confirmed_at
                            ? `FY ${af.financial_year} is confirmed. Removing it supersedes a confirmed record — this is logged and attributed, and a reason is required.`
                            : `Remove FY ${af.financial_year} from this deal? It is taken out of the queue (retained for audit) and the analysis gate re-evaluates.`}
                        </div>
                        <input
                          type="text"
                          value={afRemoveReason}
                          onChange={(e) => setAfRemoveReason(e.target.value)}
                          placeholder={af.confirmed_at ? 'Reason (required)' : 'Reason (optional)'}
                          style={{ width: '100%', boxSizing: 'border-box', fontSize: 11, padding: '6px 8px', background: 'var(--s1)', border: '1px solid var(--t2)', borderRadius: 4, color: 'var(--t0)', marginBottom: 6 }}
                        />
                        {afRemoveError && (
                          <div style={{ fontSize: 10, color: 'var(--red)', marginBottom: 6 }}>{afRemoveError}</div>
                        )}
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            type="button"
                            disabled={afRemoving || (!!af.confirmed_at && !afRemoveReason.trim())}
                            onClick={() => handleRemoveAuditedFinancials(af)}
                            style={{ fontSize: 10, fontWeight: 600, color: '#fff', background: afRemoving || (!!af.confirmed_at && !afRemoveReason.trim()) ? '#7F1D1D' : 'var(--red)', border: 'none', borderRadius: 4, padding: '5px 10px', cursor: afRemoving || (!!af.confirmed_at && !afRemoveReason.trim()) ? 'not-allowed' : 'pointer' }}
                          >
                            {afRemoving ? 'Removing…' : af.confirmed_at ? 'Supersede & remove' : 'Remove'}
                          </button>
                          <button
                            type="button"
                            disabled={afRemoving}
                            onClick={() => { setAfRemoveTarget(null); setAfRemoveReason(''); setAfRemoveError(''); }}
                            style={{ fontSize: 10, color: 'var(--t1)', background: 'none', border: '1px solid var(--t2)', borderRadius: 4, padding: '5px 10px', cursor: 'pointer' }}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

              {/* Upload zone */}
              {!auditedConfirmForm && (
                auditedUploading ? (
                  <div style={{ padding: '14px 12px', textAlign: 'center', border: '1px dashed var(--t2)', borderRadius: 6, marginTop: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--accent)' }}>
                      {declarationType === 'management' ? 'Processing management accounts…' : 'Extracting financial data…'}
                    </span>
                  </div>
                ) : (
                  <DropZone
                    onFileDrop={onAuditedDrop}
                    label={auditedFinancialsList.length > 0 ? 'Add another year' : (declarationType === 'management' ? 'Add management accounts' : 'Add audited accounts')}
                    formats="PDF · CSV · XLSX · Auto-extracts revenue, cash & FY dates"
                  />
                )
              )}

              {/* Upload error */}
              {auditedUploadError && !auditedConfirmForm && (
                <p style={{ fontSize: 11, color: 'var(--red)', marginTop: 6 }}>{auditedUploadError} — fill in details manually below</p>
              )}

              {/* Confirmation / manual fill form */}
              {auditedConfirmForm && (
                <div style={{ background: 'var(--s1)', border: '1px solid var(--accent)', borderRadius: 8, padding: 16, marginTop: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.08em' }}>
                      {auditedConfirmForm.extraction_confidence != null
                        ? `CONFIRM EXTRACTED DETAILS — ${auditedConfirmForm.extraction_confidence}% confidence`
                        : 'ENTER FINANCIAL DETAILS'}
                    </div>
                    {auditedConfirmForm.declaration_type === 'management' && (
                      <span style={{ fontSize: 9, background: 'rgba(251,191,36,0.15)', color: 'var(--amber)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 3, padding: '2px 6px', letterSpacing: '0.05em' }}>MANAGEMENT</span>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {([
                      { key: 'company_name', label: 'Company name', type: 'text', placeholder: 'e.g. Buildex Ltd' },
                      { key: 'financial_year', label: 'Financial year', type: 'number', placeholder: 'e.g. 2024' },
                      { key: 'financial_year_start', label: 'FY start date', type: 'text', placeholder: 'YYYY-MM-DD' },
                      { key: 'financial_year_end', label: 'FY end date', type: 'text', placeholder: 'YYYY-MM-DD' },
                    ] as const).map(({ key, label, type, placeholder }) => (
                      <div key={key}>
                        <label style={{ fontSize: 10, color: 'var(--t1)', display: 'block', marginBottom: 4 }}>{label}</label>
                        <input
                          type={type}
                          value={(auditedConfirmForm[key as keyof AuditedFinancialsRecord] as string | undefined) ?? ''}
                          onChange={(e) => setAuditedConfirmForm((prev) => prev ? { ...prev, [key]: e.target.value } : prev)}
                          placeholder={placeholder}
                          style={{ width: '100%', background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.25)', borderRadius: 5, padding: '6px 8px', fontSize: 12, color: 'var(--t0)', outline: 'none', boxSizing: 'border-box' }}
                        />
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--t1)', marginTop: 10, marginBottom: 6 }}>Amounts in KES (whole numbers)</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    {([
                      { key: 'turnover_cents', label: 'Annual revenue (KES)' },
                      { key: 'cash_and_equivalents_cents', label: 'Cash at year-end (KES)' },
                      { key: 'profit_after_tax_cents', label: 'Profit after tax (KES)' },
                      { key: 'total_assets_cents', label: 'Total assets (KES)' },
                      { key: 'total_expenses_cents', label: 'Total expenses (KES)' },
                      { key: 'total_liabilities_cents', label: 'Total liabilities (KES)' },
                    ] as const).map(({ key, label }) => {
                      const rawVal = auditedConfirmForm[key as keyof AuditedFinancialsRecord] as number | null | undefined;
                      const displayVal = rawVal != null ? String(Math.round((rawVal as number) / 100)) : '';
                      return (
                        <div key={key}>
                          <label style={{ fontSize: 10, color: 'var(--t1)', display: 'block', marginBottom: 4 }}>{label}</label>
                          <input
                            type="text"
                            value={displayVal}
                            onChange={(e) => {
                              const kes = parseFloat(e.target.value.replace(/,/g, ''));
                              setAuditedConfirmForm((prev) => prev ? { ...prev, [key]: isNaN(kes) ? null : Math.round(kes * 100) } : prev);
                            }}
                            placeholder="0"
                            style={{ width: '100%', background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.25)', borderRadius: 5, padding: '6px 8px', fontSize: 12, color: 'var(--t0)', outline: 'none', boxSizing: 'border-box' }}
                          />
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                    <button
                      type="button"
                      disabled={auditedSaving}
                      onClick={async () => {
                        if (!deal || !auditedConfirmForm) return;
                        const fy = Number(auditedConfirmForm.financial_year);
                        if (!fy) { alert('Financial year is required'); return; }
                        setAuditedSaving(true);
                        try {
                          const { financial_year: _fy, deal_id: _did, extraction_confidence: _ec, id: _id, ...patch } = auditedConfirmForm;
                          await patchAuditedFinancials(deal.id, fy, patch);
                          await loadAuditedFinancials(deal.id);
                          setAuditedConfirmForm(null);
                          setAuditedUploadError('');
                        } catch (err) {
                          alert(err instanceof Error ? err.message : 'Save failed');
                        } finally {
                          setAuditedSaving(false);
                        }
                      }}
                      style={{ flex: 1, padding: '8px 0', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: auditedSaving ? 'not-allowed' : 'pointer', opacity: auditedSaving ? 0.6 : 1 }}
                    >
                      {auditedSaving ? 'Saving…' : 'Save financial details'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setAuditedConfirmForm(null); setAuditedUploadError(''); }}
                      style={{ padding: '8px 14px', background: 'transparent', color: 'var(--t1)', border: '1px solid var(--b1)', borderRadius: 6, fontSize: 12, cursor: 'pointer' }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Application Documents */}
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 20, marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t0)' }}>APPLICATION DOCUMENTS</span>
              <span style={{ fontSize: 11, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>optional</span>
            </div>
            {[
              { label: 'Business registration certificate', formats: 'PDF · DOCX' },
              { label: 'KRA PIN certificate', formats: 'PDF' },
              { label: 'Director ID / Passport', formats: 'PDF · JPG' },
            ].map((doc) => (
              <div key={doc.label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--s3)' }}>
                <span style={{ width: 20, height: 20, borderRadius: 4, background: 'var(--s1)', border: '1px dashed var(--t2)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <span style={{ fontSize: 11, color: 'var(--t2)' }}>—</span>
                </span>
                <span style={{ flex: 1, fontSize: 13, color: 'var(--t1)' }}>{doc.label}</span>
                <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', color: 'var(--t2)', background: 'var(--s1)', border: '1px solid var(--b1)', padding: '2px 7px', borderRadius: 3 }}>PENDING</span>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {(() => {
              // PAR-91: don't offer this as an active "first-time setup" action
              // while we haven't confirmed the deal's real state yet (checking),
              // and don't frame it as first-time setup at all once analysis has
              // already completed — the label/enabled-state must reflect what we
              // actually know, not default to "never analysed" framing.
              const isChecking = analysisState === 'checking';
              const hasExistingAnalysis = analysisState === 'done';
              const isDisabled = isChecking || statementQueue.length === 0 || queueHasPending || isProcessing || !!auditedConfirmForm;
              const label = hasExistingAnalysis
                ? 'Add documents & re-run analysis'
                : 'Initialise analysis pipeline';
              return (
                <button
                  onClick={onInitialiseAnalysis}
                  disabled={isDisabled}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 20px', background: isDisabled ? 'var(--s3)' : 'var(--accent)', color: isDisabled ? 'var(--t2)' : '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: isDisabled ? 'not-allowed' : 'pointer', fontFamily: "'IBM Plex Sans', sans-serif", transition: 'background 0.15s' }}
                >
                  {isChecking || isProcessing ? <AnalystStatus stage={isChecking ? 'checking' : 'generic'} size={16} /> : label}
                  {!isChecking && !isProcessing && <span style={{ fontSize: 16 }}>→</span>}
                </button>
              );
            })()}
            {statementQueue.length > 0 && (
              <span style={{ fontSize: 12, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>
                {statementQueue.filter(i => i.status === 'ready').length} documents indexed{queueHasPending ? ` · ${statementQueue.filter(i => i.status === 'processing' || i.status === 'uploading').length} pending` : ''}
              </span>
            )}
          </div>
          {auditedConfirmForm && (
            <div style={{ marginTop: 12, fontSize: 12, color: 'var(--amber)', fontFamily: "'IBM Plex Mono', monospace" }}>
              Save or cancel the financial details form above before initialising analysis.
            </div>
          )}
          {errorMsg && <div style={{ marginTop: 12, fontSize: 12, color: 'var(--red)', fontFamily: "'IBM Plex Mono', monospace" }}>{errorMsg}</div>}
        </>
      )}
    </div>
  );
}
