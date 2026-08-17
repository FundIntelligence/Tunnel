'use client';

import { useState, useEffect, useCallback, useMemo, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import {
  listDealTransactions,
  getLatestEnrichment,
  createEnrichment,
  finalizeEnrichment,
  downloadEnrichedPdf,
  type DealTransaction,
  type ClassificationOverride,
  type CustomFlag,
  type Enrichment,
} from '@/lib/v1-api';

const ALL_ROLES = [
  'revenue_operational',
  'revenue_non_operational',
  'payroll',
  'supplier',
  'transfer',
  'other',
  'needs_review',
];

const FLAG_METRICS = [
  { value: 'closing_balance', label: 'Month-end closing balance' },
  { value: 'overdraft_days', label: 'Days balance went negative' },
  { value: 'single_transaction_amount', label: 'Single transaction amount' },
];

const FLAG_COMPARISONS = [
  { value: 'less_than', label: '<' },
  { value: 'less_than_or_equal', label: '≤' },
  { value: 'greater_than', label: '>' },
  { value: 'greater_than_or_equal', label: '≥' },
];

const SEVERITY_COLORS: Record<string, string> = {
  info: 'text-blue-400 border-blue-700',
  warning: 'text-yellow-400 border-yellow-700',
  critical: 'text-red-400 border-red-700',
};

function fmtAmount(cents: number, currency = 'KES') {
  const abs = Math.abs(cents) / 100;
  const sign = cents < 0 ? '-' : '+';
  return `${sign}${currency} ${abs.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

// ── Transaction Override Modal ────────────────────────────────────────────────

function OverrideModal({
  txn,
  existing,
  onSave,
  onClose,
}: {
  txn: DealTransaction;
  existing?: ClassificationOverride;
  onSave: (o: ClassificationOverride) => void;
  onClose: () => void;
}) {
  const [role, setRole] = useState(existing?.override_role ?? txn.role ?? 'other');
  const [reason, setReason] = useState(existing?.override_reason ?? '');

  const handleSave = () => {
    if (!reason.trim()) return;
    onSave({
      txn_id: txn.id,
      original_role: txn.role || 'other',
      override_role: role,
      override_reason: reason.trim(),
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-lg">
        <div className="p-5 border-b border-gray-700">
          <h3 className="font-semibold">Override Classification</h3>
          <p className="text-xs text-gray-400 mt-1">{txn.id}</p>
        </div>

        <div className="p-5 space-y-4">
          <div className="bg-gray-800 rounded p-3 text-sm space-y-1">
            <p className="text-gray-300">{txn.description}</p>
            <p className="text-gray-400">{txn.txn_date} · {fmtAmount(txn.signed_amount_cents)}</p>
            {txn.entity_name && <p className="text-gray-500">{txn.entity_name}</p>}
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Original classification</label>
            <span className="font-mono text-sm text-gray-300">{txn.role || '—'}</span>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">New classification</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
            >
              {ALL_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Reason <span className="text-red-400">*</span>
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why you're overriding the automated classification"
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm resize-none focus:outline-none focus:border-gray-500"
            />
          </div>
        </div>

        <div className="p-5 border-t border-gray-700 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!reason.trim() || role === txn.role}
            className="px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:opacity-40 rounded text-sm font-medium"
          >
            Save override
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Add Flag Form ─────────────────────────────────────────────────────────────

function AddFlagForm({ onAdd }: { onAdd: (f: CustomFlag) => void }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [severity, setSeverity] = useState<'info' | 'warning' | 'critical'>('warning');
  const [metric, setMetric] = useState('closing_balance');
  const [comparison, setComparison] = useState('less_than');
  const [thresholdStr, setThresholdStr] = useState('');
  const [open, setOpen] = useState(false);

  const handleAdd = () => {
    const threshold = Math.round(parseFloat(thresholdStr) * 100);
    if (!name.trim() || !thresholdStr || isNaN(threshold)) return;
    onAdd({
      flag_type: 'threshold',
      flag_name: name.trim().toLowerCase().replace(/\s+/g, '_'),
      flag_severity: severity,
      flag_description: desc.trim() || name.trim(),
      criteria: { metric, comparison, threshold_cents: threshold },
    });
    setName(''); setDesc(''); setThresholdStr(''); setOpen(false);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-3 py-2 text-sm border border-dashed border-gray-600 rounded hover:border-gray-400 text-gray-400 hover:text-gray-200"
      >
        + Add threshold alert
      </button>
    );
  }

  return (
    <div className="border border-gray-700 rounded-lg p-4 space-y-3 bg-gray-800">
      <p className="text-sm font-medium">New threshold alert</p>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Alert name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Cash below 500k"
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Severity</label>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as 'info' | 'warning' | 'critical')}
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
          >
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">Description (optional)</label>
        <input
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="Human-readable description"
          className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
        />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Metric</label>
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
          >
            {FLAG_METRICS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Condition</label>
          <select
            value={comparison}
            onChange={(e) => setComparison(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
          >
            {FLAG_COMPARISONS.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Amount (KES)</label>
          <input
            value={thresholdStr}
            onChange={(e) => setThresholdStr(e.target.value)}
            type="number"
            placeholder="500000"
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      <div className="flex justify-end gap-3 pt-1">
        <button
          onClick={() => setOpen(false)}
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          Cancel
        </button>
        <button
          onClick={handleAdd}
          disabled={!name.trim() || !thresholdStr}
          className="px-4 py-1.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-40 rounded text-sm"
        >
          Add alert
        </button>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ParityReviewPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center">
        <p className="text-gray-400">Loading…</p>
      </div>
    }>
      <ParityReviewContent />
    </Suspense>
  );
}

function ParityReviewContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const dealId = searchParams.get('dealId') ?? '';

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [transactions, setTransactions] = useState<DealTransaction[]>([]);
  const [existingEnrichment, setExistingEnrichment] = useState<Enrichment | null>(null);

  // Draft state
  const [overrides, setOverrides] = useState<ClassificationOverride[]>([]);
  const [flags, setFlags] = useState<CustomFlag[]>([]);
  const [narrative, setNarrative] = useState('');
  const [enrichmentReason, setEnrichmentReason] = useState('');

  // UI state
  const [txnFilter, setTxnFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [modalTxn, setModalTxn] = useState<DealTransaction | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [saveError, setSaveError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [userEmail, setUserEmail] = useState('');

  // Auth guard
  useEffect(() => {
    if (!supabase) { router.replace('/login'); return; }
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.replace('/login'); return; }
      setUserEmail(data.session.user.email ?? '');
    });
  }, [router]);

  // Load data
  useEffect(() => {
    if (!dealId || !userEmail) return;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [txnRes, enrichRes] = await Promise.all([
          listDealTransactions(dealId),
          getLatestEnrichment(dealId),
        ]);
        setTransactions(txnRes.transactions);
        if (enrichRes.enrichment) {
          setExistingEnrichment(enrichRes.enrichment);
          // Pre-populate draft from existing enrichment
          setOverrides((enrichRes.enrichment.overrides as ClassificationOverride[]) ?? []);
          setFlags((enrichRes.enrichment.flags as CustomFlag[]) ?? []);
          setNarrative(enrichRes.enrichment.narrative ?? '');
          setEnrichmentReason(enrichRes.enrichment.enrichment_reason ?? '');
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [dealId, userEmail]);

  const overrideByTxnId = useMemo(() => {
    const m: Record<string, ClassificationOverride> = {};
    for (const o of overrides) m[o.txn_id] = o;
    return m;
  }, [overrides]);

  const handleSaveOverride = useCallback((override: ClassificationOverride) => {
    setOverrides((prev) => {
      const next = prev.filter((o) => o.txn_id !== override.txn_id);
      return [...next, override];
    });
  }, []);

  const handleRemoveOverride = (txnId: string) => {
    setOverrides((prev) => prev.filter((o) => o.txn_id !== txnId));
  };

  const handleAddFlag = (flag: CustomFlag) => {
    setFlags((prev) => [...prev, flag]);
  };

  const handleRemoveFlag = (index: number) => {
    setFlags((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async (isFinal = false) => {
    if (!dealId || !userEmail) return;
    setSaving(true);
    setSaveMsg('');
    setSaveError('');
    try {
      const result = await createEnrichment(dealId, {
        analyst_id: userEmail,
        overrides,
        flags,
        narrative,
        enrichment_reason: enrichmentReason,
        is_final: isFinal,
      });
      if (isFinal && !result.created) {
        // Already exists with same hash — finalize separately
        await finalizeEnrichment(result.enrichment_id);
      }
      setSaveMsg(isFinal ? 'Enrichment finalized and ready for export.' : `Enrichment saved. (${result.enrichment_id.slice(0, 8)}…)`);
      // Refresh existing enrichment
      const enrichRes = await getLatestEnrichment(dealId);
      setExistingEnrichment(enrichRes.enrichment);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (!dealId) return;
    setDownloading(true);
    setSaveError('');
    try {
      const res = await downloadEnrichedPdf(dealId, existingEnrichment?.id);
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `parity_${dealId.slice(0, 8)}_enriched.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setDownloading(false);
    }
  };

  // Filtered transactions
  const filteredTxns = useMemo(() => {
    return transactions.filter((t) => {
      const matchesText = !txnFilter || t.description.toLowerCase().includes(txnFilter.toLowerCase()) || t.entity_name.toLowerCase().includes(txnFilter.toLowerCase());
      const effectiveRole = overrideByTxnId[t.id]?.override_role ?? t.role;
      const matchesRole = !roleFilter || effectiveRole === roleFilter;
      return matchesText && matchesRole;
    });
  }, [transactions, txnFilter, roleFilter, overrideByTxnId]);

  if (!dealId) {
    return (
      <div className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center">
        <p className="text-gray-400">No deal ID specified. Add <code>?dealId=...</code> to the URL.</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <button
            onClick={() => router.back()}
            className="text-sm text-gray-400 hover:text-gray-200 mb-2 flex items-center gap-1"
          >
            ← Back
          </button>
          <h1 className="text-xl font-semibold">Parity Review — Analyst Enrichment</h1>
          <p className="text-xs text-gray-400 mt-0.5">Deal: <code className="font-mono">{dealId}</code></p>
        </div>
        {existingEnrichment && (
          <div className="text-right text-xs text-gray-500">
            <p>Last enrichment</p>
            <p className="font-mono">{existingEnrichment.enriched_hash.slice(0, 16)}…</p>
            <p>{existingEnrichment.is_final ? '✓ Finalized' : 'Draft'}</p>
          </div>
        )}
      </div>

      {loading && <p className="text-gray-400">Loading transactions…</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      {!loading && !error && (
        <>
          {/* ── Architecture notice ── */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 mb-6 text-xs text-gray-400 font-mono">
            <p className="text-gray-300 font-medium mb-1">Layer 2: Analyst Enrichment</p>
            <p>Base snapshot is immutable. Changes here create a new enrichment record that references the base — determinism is preserved.</p>
          </div>

          {/* ── Section 1: Transaction overrides ── */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-5">
            <h2 className="font-semibold mb-1">Classification Overrides</h2>
            <p className="text-xs text-gray-400 mb-4">
              Click any transaction to override its automated classification. Reason required.
            </p>

            {/* Filters */}
            <div className="flex gap-3 mb-3">
              <input
                value={txnFilter}
                onChange={(e) => setTxnFilter(e.target.value)}
                placeholder="Search description or entity…"
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-gray-500"
              />
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
              >
                <option value="">All roles</option>
                {ALL_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>

            {/* Stats bar */}
            <div className="flex gap-4 text-xs text-gray-500 mb-3">
              <span>{filteredTxns.length} of {transactions.length} transactions</span>
              {overrides.length > 0 && (
                <span className="text-teal-400">{overrides.length} override{overrides.length !== 1 ? 's' : ''} staged</span>
              )}
            </div>

            {/* Transaction table */}
            <div className="overflow-x-auto rounded border border-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-800 text-gray-400 text-xs">
                    <th className="text-left px-3 py-2 font-medium">Date</th>
                    <th className="text-left px-3 py-2 font-medium">Description</th>
                    <th className="text-left px-3 py-2 font-medium">Entity</th>
                    <th className="text-right px-3 py-2 font-medium">Amount</th>
                    <th className="text-left px-3 py-2 font-medium">Role</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTxns.slice(0, 200).map((t) => {
                    const ov = overrideByTxnId[t.id];
                    const displayRole = ov?.override_role ?? t.role;
                    const isOverridden = !!ov;
                    return (
                      <tr
                        key={t.id}
                        className={`border-t border-gray-800 hover:bg-gray-800 cursor-pointer transition-colors ${isOverridden ? 'bg-teal-950/20' : ''}`}
                        onClick={() => setModalTxn(t)}
                      >
                        <td className="px-3 py-2 text-gray-400 whitespace-nowrap">{t.txn_date}</td>
                        <td className="px-3 py-2 max-w-xs truncate" title={t.description}>{t.description}</td>
                        <td className="px-3 py-2 text-gray-400 max-w-[120px] truncate" title={t.entity_name}>{t.entity_name || '—'}</td>
                        <td className={`px-3 py-2 text-right font-mono whitespace-nowrap ${t.signed_amount_cents >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {fmtAmount(t.signed_amount_cents)}
                        </td>
                        <td className="px-3 py-2">
                          {isOverridden ? (
                            <span className="flex items-center gap-1">
                              <span className="line-through text-gray-500 text-xs">{t.role}</span>
                              <span className="text-teal-300">{displayRole}</span>
                            </span>
                          ) : (
                            <span className="text-gray-300">{displayRole || '—'}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {isOverridden && (
                            <button
                              onClick={(e) => { e.stopPropagation(); handleRemoveOverride(t.id); }}
                              className="text-xs text-gray-500 hover:text-red-400"
                            >
                              remove
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filteredTxns.length > 200 && (
                <p className="text-xs text-gray-500 text-center py-2">
                  Showing first 200. Refine your filter to see more.
                </p>
              )}
            </div>

            {/* Staged overrides summary */}
            {overrides.length > 0 && (
              <div className="mt-4">
                <p className="text-xs text-gray-400 mb-2">Staged overrides:</p>
                <ul className="space-y-1">
                  {overrides.map((o) => {
                    const txn = transactions.find((t) => t.id === o.txn_id);
                    return (
                      <li key={o.txn_id} className="flex items-start gap-2 text-xs bg-gray-800 rounded px-3 py-2">
                        <span className="text-gray-400 truncate max-w-[200px]">{txn?.description ?? o.txn_id.slice(0, 8)}</span>
                        <span className="text-gray-500">·</span>
                        <span className="line-through text-gray-500">{o.original_role}</span>
                        <span className="text-gray-500">→</span>
                        <span className="text-teal-300">{o.override_role}</span>
                        <span className="text-gray-500 italic truncate flex-1">{o.override_reason}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </section>

          {/* ── Section 2: Custom threshold flags ── */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-5">
            <h2 className="font-semibold mb-1">Custom Threshold Alerts</h2>
            <p className="text-xs text-gray-400 mb-4">
              Define conditions that will be evaluated against the base snapshot and included in the export.
            </p>

            <div className="space-y-3">
              {flags.map((f, i) => (
                <div
                  key={i}
                  className={`border rounded-lg px-4 py-3 flex items-start justify-between gap-4 ${SEVERITY_COLORS[f.flag_severity] ?? 'text-gray-300 border-gray-700'}`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-medium text-sm">{f.flag_description || f.flag_name}</span>
                      <span className="text-xs uppercase opacity-60">{f.flag_severity}</span>
                      {f.triggered !== undefined && (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${f.triggered ? 'bg-red-900/50 text-red-300' : 'bg-green-900/30 text-green-400'}`}>
                          {f.triggered ? `Triggered (${f.trigger_count}×)` : 'Not triggered'}
                        </span>
                      )}
                    </div>
                    <p className="text-xs opacity-70 font-mono">
                      {f.criteria.metric} {FLAG_COMPARISONS.find(c => c.value === f.criteria.comparison)?.label ?? f.criteria.comparison} {(f.criteria.threshold_cents / 100).toLocaleString()} KES
                    </p>
                  </div>
                  <button
                    onClick={() => handleRemoveFlag(i)}
                    className="text-xs text-gray-500 hover:text-red-400 shrink-0"
                  >
                    remove
                  </button>
                </div>
              ))}
              <AddFlagForm onAdd={handleAddFlag} />
            </div>
          </section>

          {/* ── Section 3: Analyst narrative ── */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-5">
            <h2 className="font-semibold mb-1">Analyst Narrative</h2>
            <p className="text-xs text-gray-400 mb-3">
              Optional commentary on this deal. Included verbatim in enriched exports.
            </p>
            <textarea
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              placeholder="e.g. Revenue is primarily driven by export invoices. Confirmed with client that EUR-converted inflows in June and December represent seasonal export revenue…"
              rows={5}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm resize-none focus:outline-none focus:border-gray-500"
            />
            <div className="mt-2">
              <label className="block text-xs text-gray-400 mb-1">Reason for this enrichment</label>
              <input
                value={enrichmentReason}
                onChange={(e) => setEnrichmentReason(e.target.value)}
                placeholder="e.g. Pre-IC enrichment — reclassified FX receipts and added cash threshold alerts"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
              />
            </div>
          </section>

          {/* ── Save / Finalize ── */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <div className="flex flex-wrap gap-3 items-center">
              <button
                onClick={() => handleSave(false)}
                disabled={saving}
                className="px-5 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded font-medium"
              >
                {saving ? 'Saving…' : 'Save draft'}
              </button>
              <button
                onClick={() => handleSave(true)}
                disabled={saving}
                className="px-5 py-2 bg-teal-500 hover:bg-teal-600 disabled:opacity-40 rounded font-medium"
              >
                {saving ? 'Saving…' : 'Finalize for export'}
              </button>
              <button
                onClick={handleDownloadPdf}
                disabled={downloading}
                className="px-5 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded font-medium"
              >
                {downloading ? 'Generating…' : 'Download enriched PDF'}
              </button>
              {saveMsg && <span className="text-sm text-green-400">{saveMsg}</span>}
              {saveError && <span className="text-sm text-red-400">{saveError}</span>}
            </div>

            {existingEnrichment && (
              <div className="mt-4 font-mono text-xs text-gray-500 space-y-0.5">
                <p>enrichment_id: {existingEnrichment.id}</p>
                <p>enriched_hash: {existingEnrichment.enriched_hash}</p>
                <p>base_snapshot: {existingEnrichment.base_snapshot_id}</p>
                <p>analyst: {existingEnrichment.analyst_id}</p>
                <p>status: {existingEnrichment.is_final ? 'FINAL' : 'DRAFT'}</p>
              </div>
            )}
          </section>
        </>
      )}

      {/* Override modal */}
      {modalTxn && (
        <OverrideModal
          txn={modalTxn}
          existing={overrideByTxnId[modalTxn.id]}
          onSave={handleSaveOverride}
          onClose={() => setModalTxn(null)}
        />
      )}
    </div>
  );
}
