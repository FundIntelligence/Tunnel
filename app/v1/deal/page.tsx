'use client';

import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { useDropzone } from 'react-dropzone';
import { supabase } from '@/lib/supabase';
import {
  createDeal,
  uploadDocument,
  uploadAuditedFinancials,
  getAuditedFinancials,
  getDocumentStatus,
  exportSnapshot,
  getDocumentTransactions,
  listDealTransactions,
  addOverride,
  listOverrides,
  listDocuments,
  deleteDocument,
  askParity,
  // askParityReview moved to ParityReviewChat component
  exportTransactionsCsv,
  getNeedsReview,
  getMonthlyCashflow,
  getCreditScoringInputs,
  getReconciliation,
  downloadReport,
  getLatestAnalysis,
} from '@/lib/v1-api';
import type { DealListItem } from '@/lib/v1-api';
import { useDealsListQuery, useDealDetailQuery, useDealDocumentsQuery, dealDocumentsKey, dealDetailKey, dealsListKey } from '@/lib/queries/deals';
import { BatchUpload } from '@/components/BatchUpload';
import DocumentsTab from '@/components/deal-tabs/DocumentsTab';
import AnalysisTab from '@/components/deal-tabs/AnalysisTab';
import ParityReviewTab from '@/components/deal-tabs/ParityReviewTab';
import ReviewQueueTab from '@/components/deal-tabs/ReviewQueueTab';
import SnapshotTab from '@/components/deal-tabs/SnapshotTab';
import DealSidebar from '@/components/deal-tabs/DealSidebar';
import UnknownParserModal from '@/components/deal-tabs/UnknownParserModal';
import TransactionDrillModal from '@/components/deal-tabs/TransactionDrillModal';
import { apiDocumentStatus, computeEntityBreakdownByCategory, computePipelineStages } from '@/lib/deal-analytics';
import type {
  Deal,
  AnalysisRun,
  Snapshot,
  Entity,
  TxnEntityMapping,
  ExportResponse,
  DocumentListItem,
  AuditedFinancialsRecord,
  ReconciliationSection,
} from '@/lib/v1-api';
import type { AnalysisState, EntityBreakdownRow, QueuedStatement, PipelineStage, DrillModalState, ParserRequestDoc } from '@/components/deal-tabs/types';
const CURRENCIES = ['USD', 'EUR', 'GBP', 'KES', 'NGN'];

// Keyed by dealId in the shared QueryClient cache (via queryClient.fetchQuery
// below) rather than a plain in-memory Map — this dedupes concurrent double
// mounts (a fresh/cold navigation to a deal URL can mount this component more
// than once in quick succession under <Suspense>'s useSearchParams() path)
// exactly like the old module-level Map did, but also persists across full
// page reloads (the QueryClient is synced to localStorage — see
// ReactQueryProvider) and expires on its own after staleTime instead of
// living forever until an explicit retry.
type RehydrationResult =
  | { ok: true; analysis_run: AnalysisRun | null; exportData?: ExportResponse; rawTransactions?: Array<Record<string, unknown>>; creditScoringInputs?: Record<string, unknown> | null }
  | { ok: false; message: string };
const rehydrationKey = (dealId: string) => ['rehydration', dealId] as const;

async function fetchRehydration(dealId: string): Promise<RehydrationResult> {
  try {
    const { analysis_run } = await getLatestAnalysis(dealId);
    if (!analysis_run) return { ok: true, analysis_run: null };
    const data = await exportSnapshot(dealId);
    const txRes = await listDealTransactions(dealId);
    let creditScoringInputs: Record<string, unknown> | null = null;
    try {
      creditScoringInputs = await getCreditScoringInputs(dealId);
    } catch (e) {
      console.error('getCreditScoringInputs failed on rehydrate:', e);
    }
    return {
      ok: true,
      analysis_run,
      exportData: data,
      rawTransactions: txRes.transactions as unknown as Array<Record<string, unknown>>,
      creditScoringInputs,
    };
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) };
  }
}

function V1DealPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState<string | undefined>(undefined);
  const urlDealId = searchParams.get('deal_id') ?? undefined;

  useEffect(() => {
    if (!supabase) { router.replace('/login'); return; }
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace('/login'); return; }
      const email = session.user.email ?? '';
      if (email) setUserInitials(email.slice(0, 2).toUpperCase());
      setUserId(session.user.id);
    });
  }, [router]);

  // Reads the same ['deals', userId] cache the /deals dashboard populates —
  // opening a deal from there doesn't re-fetch the sidebar list within staleTime.
  const dealsListQuery = useDealsListQuery(userId);
  useEffect(() => {
    if (dealsListQuery.data) setSidebarDeals(dealsListQuery.data.deals);
  }, [dealsListQuery.data]);

  // Pre-load deal from URL param (set by /deals/new)
  useEffect(() => {
    if (!urlDealId || deal) return;
    setDeal({ id: urlDealId });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlDealId]);

  // Initial setDeal above only has `id` (from the URL param) — rehydrate the
  // rest of the row (name, currency, etc.) from the shared ['deal', id] cache,
  // the same one the dashboard already populated, so a deal opened from there
  // reads from cache instead of re-fetching within staleTime.
  const dealDetailQuery = useDealDetailQuery(urlDealId);
  useEffect(() => {
    const fullDeal = dealDetailQuery.data?.deal;
    if (fullDeal) setDeal((prev) => (prev ? { ...prev, ...fullDeal } : fullDeal));
  }, [dealDetailQuery.data]);

  // Same for the document list — shares ['documents', id] with the dashboard.
  const dealDocumentsQuery = useDealDocumentsQuery(urlDealId);
  useEffect(() => {
    if (dealDocumentsQuery.data) setDealDocuments(dealDocumentsQuery.data.documents);
  }, [dealDocumentsQuery.data]);

  const [file, setFile] = useState<File | null>(null);
  const [currency, setCurrency] = useState<string | null>(null);
  const [dealName, setDealName] = useState('');
  const [accrualRevenueCents, setAccrualRevenueCents] = useState('');
  const [accrualPeriodStart, setAccrualPeriodStart] = useState('');
  const [accrualPeriodEnd, setAccrualPeriodEnd] = useState('');
  const [deal, setDeal] = useState<Deal | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [analysisState, setAnalysisState] = useState<AnalysisState>('checking');
  const [errorMsg, setErrorMsg] = useState('');
  const [exportData, setExportData] = useState<ExportResponse | null>(null);
  const [overrideEntityId, setOverrideEntityId] = useState('');
  const [overrideRole, setOverrideRole] = useState('supplier');
  const [overrideNote, setOverrideNote] = useState('');
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideSuccess, setOverrideSuccess] = useState('');
  const [overrideError, setOverrideError] = useState('');
  const [overridesList, setOverridesList] = useState<Array<Record<string, unknown>>>([]);
  const [exportSuccess, setExportSuccess] = useState('');
  const [exportError, setExportError] = useState('');
  const [lastExportedAt, setLastExportedAt] = useState<Date | null>(null);
  const [rawTransactions, setRawTransactions] = useState<Array<Record<string, unknown>>>([]);
  const [monthlyCashflow, setMonthlyCashflow] = useState<Array<Record<string, unknown>>>([]);
  const [creditScoringInputs, setCreditScoringInputs] = useState<Record<string, unknown> | null>(null);
  const [monthlyEntityBreakdown, setMonthlyEntityBreakdown] = useState<Array<Record<string, unknown>>>([]);
  const [reconciliationDetail, setReconciliationDetail] = useState<ReconciliationSection | null>(null);
  // Chat state moved to ParityReviewChat component for performance
  const [dealDocuments, setDealDocuments] = useState<DocumentListItem[]>([]);
  const [auditedFinancialsList, setAuditedFinancialsList] = useState<AuditedFinancialsRecord[]>([]);
  const [auditedConfirmForm, setAuditedConfirmForm] = useState<AuditedFinancialsRecord | null>(null);
  const [auditedUploading, setAuditedUploading] = useState(false);
  const [auditedUploadError, setAuditedUploadError] = useState('');
  const [auditedSaving, setAuditedSaving] = useState(false);
  const [declarationType, setDeclarationType] = useState<'audited' | 'management'>('audited');
  const [statementQueue, setStatementQueue] = useState<QueuedStatement[]>([]);
  const [activeTab, setActiveTab] = useState<'documents' | 'analysis' | 'review' | 'queue' | 'snapshot'>('documents');
  const docTypeByDocId = useRef<Map<string, 'bank' | 'audited'>>(new Map());
  // ChatMessage type, chatHistory, conversationHistory, proactiveTriggered — moved to ParityReviewChat
  const [needsReviewItems, setNeedsReviewItems] = useState<Array<Record<string, unknown>>>([]);
  // parityInputInteracted — moved to ParityReviewChat

  // Unknown-parser request modal state
  const [unknownParserDoc, setUnknownParserDoc] = useState<ParserRequestDoc | null>(null);
  const [parserRequestForm, setParserRequestForm] = useState({ bankName: '', country: 'Kenya', accountType: 'Business Current', notes: '' });
  const [parserRequestSubmitting, setParserRequestSubmitting] = useState(false);
  const [parserRequestSubmitted, setParserRequestSubmitted] = useState(false);
  const checkedFailedDocs = useRef<Set<string>>(new Set());
  // Tracks doc IDs confirmed as "unsupported format" — used to show inline CTA in FileRow
  const [unknownFormatDocIds, setUnknownFormatDocIds] = useState<Set<string>>(new Set());
  const [sidebarDeals, setSidebarDeals] = useState<DealListItem[]>([]);
  const [userInitials, setUserInitials] = useState('AN');
  const userSelectedTabRef = useRef(false);

  // Derive real currency from the already-loaded deal list (no separate fetch needed)
  useEffect(() => {
    const urlDealId = searchParams.get('deal_id');
    if (!urlDealId || currency !== null) return;
    const match = sidebarDeals.find((d) => d.id === urlDealId);
    if (match?.currency) setCurrency(match.currency);
  }, [searchParams, sidebarDeals, currency]);

  // Drill-down modal for clickable analysis tables
  const [drillModal, setDrillModal] = useState<DrillModalState | null>(null);

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted.length) setFile(accepted[0]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/pdf': ['.pdf'],
      'application/octet-stream': ['.pdf'],
    },
    maxFiles: 1,
  });

  const refreshBatchUploadCount = useCallback(
    async (dealIdOverride?: string): Promise<DocumentListItem[] | undefined> => {
      const id = dealIdOverride ?? deal?.id;
      if (!id) return undefined;
      try {
        const { documents } = await listDocuments(id);
        setDealDocuments(documents);
        // Keep the shared ['documents', id] cache in sync with this imperative
        // read (post-upload/delete, polling) so navigating back to /deals reads
        // fresh data from cache instead of re-fetching.
        queryClient.setQueryData(dealDocumentsKey(id), { documents });
        return documents;
      } catch {
        setDealDocuments([]);
        return undefined;
      }
    },
    [deal, queryClient]
  );

  const loadAuditedFinancials = useCallback(async (dealIdOverride?: string) => {
    const id = dealIdOverride ?? deal?.id;
    if (!id) return;
    try {
      const { records } = await getAuditedFinancials(id);
      setAuditedFinancialsList(records);
    } catch {
      // non-fatal
    }
  }, [deal]);

  useEffect(() => {
    if (!deal?.id) return;
    void loadAuditedFinancials();
  }, [deal?.id, loadAuditedFinancials]);

  // Rehydrate the Analysis tab from an existing run when a deal is (re)opened.
  // analysisState/exportData are pure client state — without this, reloading a
  // deal page always shows "No analysis run yet" even if analysis already
  // completed in a prior session. Read-only check first (analysis/latest) so we
  // never call the export endpoint on a deal that has no run at all; exportSnapshot
  // itself short-circuits to the existing snapshot when nothing changed, so this
  // doesn't create a new analysis_run.
  //
  // analysisState starts at 'checking' (not 'idle') specifically so "haven't
  // looked yet" and "confirmed no analysis exists" can never be the same
  // value — every UI surface that used to key off 'idle' to mean "no
  // analysis" must never see that state before this effect has conclusively
  // resolved one way or another. Real fetch work is delegated to
  // queryClient.fetchQuery under ['rehydration', dealId] so a genuine
  // double-mount on a cold navigation shares one fetch chain instead of
  // racing two, and a later revisit within staleTime reads the cached result
  // instead of re-issuing /export, /transactions and /credit-scoring-inputs —
  // this effect just applies the (possibly cached) result to local state, and
  // the two state updates below happen back-to-back with no intervening
  // await, so React batches them into a single render (no transient
  // "run truthy but analysisState still checking" flash either).
  useEffect(() => {
    if (!deal?.id || analysisState !== 'checking') return;
    const dealId = deal.id;
    let cancelled = false;
    queryClient
      .fetchQuery({ queryKey: rehydrationKey(dealId), queryFn: () => fetchRehydration(dealId) })
      .then((result) => {
        if (cancelled) return;
        if (!result.ok) {
          console.error('Rehydration failed:', result.message);
          setErrorMsg("Could not check this deal's analysis status (a temporary network or server issue). If analysis already completed, your results are safe — retry to check again.");
          setAnalysisState('error');
          return;
        }
        if (!result.analysis_run) {
          setAnalysisState('idle');
          return;
        }
        setExportData(result.exportData!);
        setRawTransactions(result.rawTransactions ?? []);
        if (result.creditScoringInputs) setCreditScoringInputs(result.creditScoringInputs);
        setAnalysisState('done');
      });
    return () => { cancelled = true; };
  }, [deal?.id, analysisState, queryClient]);

  const retryRehydrate = useCallback(() => {
    if (deal?.id) queryClient.removeQueries({ queryKey: rehydrationKey(deal.id) });
    setErrorMsg('');
    setAnalysisState('checking');
  }, [deal?.id, queryClient]);

  // PAR-91: land on Analysis (not Documents) by default for a deal that
  // already has completed results — Documents is for adding new files, not
  // the "start here" landing page for an already-analysed deal. Only fires
  // once rehydration conclusively confirms 'done', and only if the user
  // hasn't already picked a tab themselves (so this never yanks someone away
  // from wherever they intentionally navigated).
  useEffect(() => {
    if (analysisState === 'done' && !userSelectedTabRef.current) {
      setActiveTab('analysis');
    }
  }, [analysisState]);

  useEffect(() => {
    setStatementQueue((prev) => {
      const mapPrevById = new Map(prev.map((item) => [item.id, item]));
      return dealDocuments.map((doc, idx) => {
        const previous = mapPrevById.get(doc.id);
        const ns = apiDocumentStatus(doc);
        const normalizedStatus: QueuedStatement['status'] =
          ns === 'completed' ? 'ready' : ns === 'failed' ? 'failed' : 'processing';
        return {
          id: doc.id,
          fileName: previous?.fileName ?? `Statement ${idx + 1}`,
          status: previous?.status === 'uploading' ? 'uploading' : normalizedStatus,
        };
      });
    });
  }, [dealDocuments]);

  const handleStatementDrop = useCallback(
    async (nextFile: File) => {
      if (!deal) return;
      // Statement queue: pass the dropped File through to uploadDocument as multipart (no JSON).
      const tempId = crypto.randomUUID();
      setStatementQueue((prev) => [
        ...prev,
        {
          id: tempId,
          fileName: nextFile.name,
          status: 'uploading',
        },
      ]);
      try {
        const result = await uploadDocument(deal.id, nextFile);
        const docId = result.ingestion.document_id;
        setStatementQueue((prev) =>
          prev.map((item) =>
            item.id === tempId ? { ...item, id: docId, status: 'processing' } : item
          )
        );
        void refreshBatchUploadCount(deal.id);
      } catch {
        setStatementQueue((prev) =>
          prev.map((item) => (item.id === tempId ? { ...item, status: 'failed' } : item))
        );
      }
    },
    [deal, refreshBatchUploadCount]
  );

  const handleBankDrop = useCallback(async (nextFile: File) => {
    if (!deal) return;
    const tempId = crypto.randomUUID();
    docTypeByDocId.current.set(tempId, 'bank');
    setStatementQueue((prev) => [...prev, { id: tempId, fileName: nextFile.name, status: 'uploading' }]);
    try {
      const result = await uploadDocument(deal.id, nextFile);
      const docId = result.ingestion.document_id;
      docTypeByDocId.current.delete(tempId);
      docTypeByDocId.current.set(docId, 'bank');
      setStatementQueue((prev) => prev.map((item) => item.id === tempId ? { ...item, id: docId, status: 'processing' } : item));
      void refreshBatchUploadCount(deal.id);
    } catch {
      setStatementQueue((prev) => prev.map((item) => item.id === tempId ? { ...item, status: 'failed' } : item));
    }
  }, [deal, refreshBatchUploadCount]);

  const handleAuditedDrop = useCallback(async (nextFile: File) => {
    if (!deal) return;
    setAuditedUploading(true);
    setAuditedUploadError('');
    try {
      const result = await uploadAuditedFinancials(deal.id, nextFile, declarationType);
      // Pre-populate the confirmation form with extracted fields
      setAuditedConfirmForm({
        deal_id: deal.id,
        financial_year: result.financial_year,
        financial_year_start: result.financial_year_start,
        financial_year_end: result.financial_year_end,
        company_name: result.company_name ?? '',
        declaration_type: declarationType,
        turnover_cents: result.turnover_cents ?? null,
        profit_after_tax_cents: result.profit_after_tax_cents ?? null,
        total_assets_cents: result.total_assets_cents ?? null,
        cash_and_equivalents_cents: result.cash_and_equivalents_cents ?? null,
        extraction_confidence: result.extraction_confidence,
      });
      void loadAuditedFinancials(deal.id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      setAuditedUploadError(msg);
      // Still open the form for manual entry
      setAuditedConfirmForm({ deal_id: deal.id, declaration_type: declarationType });
    } finally {
      setAuditedUploading(false);
    }
  }, [deal, declarationType, loadAuditedFinancials]);

  // One listDocuments poll at a time (sequential), not overlapping setInterval + async —
  // slow responses were stacking many pending /documents requests and starving the worker.
  const statementQueueHasProcessing = useMemo(
    () => statementQueue.some((item) => item.status === 'processing'),
    [statementQueue]
  );

  useEffect(() => {
    if (!deal?.id || !statementQueueHasProcessing) return;

    const POLL_MS = 5000;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    const scheduleNext = () => {
      timeoutId = setTimeout(run, POLL_MS);
    };

    const run = async () => {
      if (cancelled) return;
      try {
        const { documents } = await listDocuments(deal.id);
        if (cancelled) return;
        setDealDocuments(documents);
        const byId = new Map(documents.map((d) => [d.id, d]));

        // Collect newly-failed bank docs to check for unknown parser
        const newlyFailed: Array<{ id: string; fileName: string }> = [];

        setStatementQueue((prev) => {
          const next = prev.map((q) => {
            if (q.status !== 'processing') return q;
            const doc = byId.get(q.id);
            if (!doc) return q;
            const ns = apiDocumentStatus(doc);
            if (ns === 'completed') return { ...q, status: 'ready' as const };
            if (ns === 'failed') {
              // Only check bank docs (not audited), and only once per doc
              if (docTypeByDocId.current.get(q.id) !== 'audited' && !checkedFailedDocs.current.has(q.id)) {
                newlyFailed.push({ id: q.id, fileName: q.fileName });
              }
              return { ...q, status: 'failed' as const };
            }
            return q;
          });
          return next;
        });

        // Outside setStatementQueue to avoid React state updates inside updater
        for (const { id, fileName } of newlyFailed) {
          if (cancelled || checkedFailedDocs.current.has(id)) continue;
          checkedFailedDocs.current.add(id);
          try {
            const statusRes = await getDocumentStatus(id);
            const errType = statusRes.error_type ?? '';
            const errMsg = (statusRes.error_message ?? statusRes.error ?? '').toLowerCase();
            const isUnknownParser =
              errType === 'InvalidSchemaError' &&
              (errMsg.includes('not recognised') || errMsg.includes('not recognized') || errMsg.includes('unsupported') || errMsg.includes('no valid transactions'));
            if (isUnknownParser) {
              setUnknownParserDoc({ docId: id, fileName, errorMessage: statusRes.error_message ?? statusRes.error ?? 'Bank format not recognised' });
              setUnknownFormatDocIds((prev) => new Set([...prev, id]));
            }
          } catch {
            // silently skip — this is a best-effort enrichment
          }
        }
      } catch {
        // ignore poll errors (network / transient 503)
      }
      if (!cancelled) scheduleNext();
    };

    void run();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [deal?.id, statementQueueHasProcessing]);

  const runAnalysis = async () => {
    setErrorMsg('');
    try {
      let activeDeal = deal;

      if (!activeDeal) {
        if (!file) {
          setErrorMsg('Please select a file');
          return;
        }
        setAnalysisState('uploading');
        const accrual =
          accrualRevenueCents && accrualPeriodStart && accrualPeriodEnd
            ? {
                accrual_revenue_cents: parseInt(accrualRevenueCents, 10) || 0,
                accrual_period_start: accrualPeriodStart,
                accrual_period_end: accrualPeriodEnd,
              }
            : undefined;

        const { deal: createdDeal } = await createDeal(currency ?? 'KES', dealName || undefined, accrual);
        setDeal(createdDeal);
        activeDeal = createdDeal;

        const { ingestion } = await uploadDocument(createdDeal.id, file);
        setDocumentId(ingestion.document_id);

        setAnalysisState('polling');
        const POLL_INTERVAL_MS = 3000;
        const MAX_WAIT_MS = 30 * 60 * 1000;
        const pollDeadline = Date.now() + MAX_WAIT_MS;
        let status = await getDocumentStatus(ingestion.document_id);
        while (status.status !== 'completed') {
          if (status.status === 'failed') {
            const errType = status.error_type || 'UnknownError';
            const errMsg = status.error_message || status.error || 'Document processing failed';
            const stage = status.stage || '';
            const nextAction = status.next_action || '';
            setErrorMsg(
              stage
                ? `${errType}: ${errMsg} (stage: ${stage}, next: ${nextAction})`
                : `${errType}: ${errMsg}`
            );
            setAnalysisState('error');
            return;
          }
          if (Date.now() >= pollDeadline) {
            setErrorMsg(
              'Still processing after 30 minutes. Large PDFs can be slow on a cold server—try again in a few minutes, or use Batch upload for monthly statements. The document may still complete in the background.'
            );
            setAnalysisState('error');
            return;
          }
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          status = await getDocumentStatus(ingestion.document_id);
        }
        if (status.currency_detected) {
          setCurrency(status.currency_detected);
        }
        if (status.analytics?.monthly_cashflow) {
          setMonthlyCashflow(status.analytics.monthly_cashflow);
        }
        if ((status as any).analytics?.monthly_entity_breakdown) {
          setMonthlyEntityBreakdown((status as any).analytics.monthly_entity_breakdown);
        }
      } else {
        const docs = await refreshBatchUploadCount(activeDeal.id);
        const allComplete = (docs ?? []).every((doc) => doc.status === 'completed');
        if (!allComplete) {
          const stillProcessing = (docs ?? []).filter(
            (doc) => doc.status === 'processing' || doc.status === 'pending'
          );
          setErrorMsg(
            stillProcessing.length > 0
              ? `${stillProcessing.length} document(s) still processing. Please wait a moment and try again.`
              : 'Some documents are not ready. Please wait a moment and try again.'
          );
          return;
        }
      }

      setAnalysisState('exporting');
      const data = await exportSnapshot(activeDeal.id);
      setExportData(data);
      setLastExportedAt(new Date());
      setOverridesList([]);
      await refreshBatchUploadCount(activeDeal.id);
      const txRes = await listDealTransactions(activeDeal.id);
      const rawTx = txRes.transactions as unknown as Array<Record<string, unknown>>;
      setRawTransactions(rawTx);
      try {
        const mcRes = await getMonthlyCashflow(activeDeal.id);
        setMonthlyCashflow(mcRes.monthly_cashflow as unknown as Array<Record<string, unknown>>);
      } catch (e) {
        console.error('getMonthlyCashflow failed after export:', e);
      }
      let csi: Record<string, unknown> | null = null;
      try {
        csi = await getCreditScoringInputs(activeDeal.id);
        setCreditScoringInputs(csi);
      } catch (e) {
        console.error('getCreditScoringInputs failed after export:', e);
      }
      setAnalysisState('done');
      // Seed the rehydration cache with what we just fetched so a later revisit
      // (this session or after a reload) reads it from cache instead of
      // re-issuing /export, /transactions and /credit-scoring-inputs.
      const rehydrationResult: RehydrationResult = {
        ok: true,
        analysis_run: data.analysis_run,
        exportData: data,
        rawTransactions: rawTx,
        creditScoringInputs: csi,
      };
      queryClient.setQueryData(rehydrationKey(activeDeal.id), rehydrationResult);
      // A run changes deal status/pipeline stage — refresh the detail cache and
      // the dashboard list (which reads the same status) instead of leaving
      // them stale for the rest of the (now unbounded) cache lifetime.
      queryClient.invalidateQueries({ queryKey: dealDetailKey(activeDeal.id) });
      queryClient.invalidateQueries({ queryKey: dealsListKey(userId) });
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Analysis failed');
      setAnalysisState('error');
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!deal) return;
    try {
      await deleteDocument(docId);
      setStatementQueue((prev) => prev.filter((item) => item.id !== docId));
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Could not remove document');
    }
  };

  const handleAddOverride = async () => {
    if (!deal || !overrideEntityId || !overrideRole) return;
    setOverrideSaving(true);
    setOverrideSuccess('');
    setOverrideError('');
    try {
      const { override } = await addOverride(deal.id, overrideEntityId, overrideRole, overrideNote || undefined);
      setOverridesList((prev) => [override, ...prev]);
      const data = await exportSnapshot(deal.id);
      setExportData(data);
      setLastExportedAt(new Date());
      setOverrideEntityId('');
      setOverrideNote('');
      setOverrideSuccess('Override saved — analysis updated.');
      setTimeout(() => setOverrideSuccess(''), 4000);
      // An override can shift entity classification, so everything derived
      // from it (rehydration snapshot, needs-review queue, reconciliation) is
      // now stale — mark it so the next read refetches instead of serving a
      // pre-override cache.
      queryClient.invalidateQueries({ queryKey: rehydrationKey(deal.id) });
      queryClient.invalidateQueries({ queryKey: ['needsReview', deal.id] });
      queryClient.invalidateQueries({ queryKey: ['reconciliation', deal.id] });
    } catch (e) {
      setOverrideError(e instanceof Error ? e.message : 'Override failed');
    } finally {
      setOverrideSaving(false);
    }
  };

  const handleDownloadCSV = async () => {
    if (!deal?.id) return;
    try {
      const res = await exportTransactionsCsv(deal.id);
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `parity_transactions_${deal.id.slice(0, 8)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('CSV export failed:', e);
    }
  };

  const handleReExport = async () => {
    if (!deal) return;
    if (analysisState === 'exporting') return; // job already in flight for this deal — ignore repeat clicks
    setAnalysisState('exporting');
    setExportSuccess('');
    setExportError('');
    try {
      // Server snapshot write happens here. PDF only generates after this resolves.
      const data = await exportSnapshot(deal.id);
      setExportData(data);
      try {
        const mcRes = await getMonthlyCashflow(deal.id);
        setMonthlyCashflow(mcRes.monthly_cashflow as unknown as Array<Record<string, unknown>>);
      } catch (e) {
        console.error('getMonthlyCashflow failed after re-export:', e);
      }

      // PDF now comes from the server-rendered snapshot (QR + verify page +
      // co-branding), not a client-side rebuild — see GET /deals/{id}/report.
      // Stay in 'exporting' (button disabled) until the PDF is actually in hand —
      // "complete" must never be shown before the file the user asked for exists.
      const res = await downloadReport(deal.id);
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `parity-snapshot-${deal.id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);

      setLastExportedAt(new Date());
      setAnalysisState('done');
      setExportSuccess('Snapshot saved. PDF downloading.');
      setTimeout(() => setExportSuccess(''), 5000);
      // Re-export writes a fresh snapshot server-side — invalidate so a later
      // revisit refetches instead of serving the pre-export cache.
      queryClient.invalidateQueries({ queryKey: rehydrationKey(deal.id) });
      queryClient.invalidateQueries({ queryKey: dealDetailKey(deal.id) });
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Export failed');
      setAnalysisState('done');
    }
  };

  // handleAsk — moved to ParityReviewChat component

  // Load needs-review items when analysis completes. Shares the ['needsReview', dealId]
  // cache with ReviewQueue.tsx — a revisit within staleTime reads from cache, and
  // resolving an item there invalidates this key so the next read is fresh.
  useEffect(() => {
    if (analysisState === 'done' && deal?.id) {
      const dealId = deal.id;
      queryClient
        .fetchQuery({ queryKey: ['needsReview', dealId], queryFn: () => getNeedsReview(dealId) })
        .then((res) => setNeedsReviewItems(res.transactions as unknown as Array<Record<string, unknown>>))
        .catch(() => {});
      if (monthlyCashflow.length === 0) {
        getMonthlyCashflow(dealId)
          .then((r) => setMonthlyCashflow(r.monthly_cashflow as unknown as Array<Record<string, unknown>>))
          .catch((e) => console.error('useEffect getMonthlyCashflow failed:', e));
      }
    }
  }, [analysisState, deal?.id, queryClient]);

  // Load fiscal-year reconciliation breakdown when analysis completes and audited
  // financials exist. Cached under ['reconciliation', dealId] so a revisit within
  // staleTime doesn't re-hit the backend.
  useEffect(() => {
    if (analysisState === 'done' && deal?.id && auditedFinancialsList.length > 0) {
      const dealId = deal.id;
      queryClient
        .fetchQuery({ queryKey: ['reconciliation', dealId], queryFn: () => getReconciliation(dealId) })
        .then((r) => setReconciliationDetail(r.reconciliation))
        .catch((e) => console.error('getReconciliation failed:', e));
    }
  }, [analysisState, deal?.id, auditedFinancialsList.length, queryClient]);

  // parityInputInteracted, proactive analysis trigger — moved to ParityReviewChat

  const handleParserRequestSubmit = async () => {
    if (!unknownParserDoc || !parserRequestForm.bankName.trim()) return;
    setParserRequestSubmitting(true);
    try {
      // 1. Persist to Supabase (existing behaviour)
      const sbClient = supabase;
      if (sbClient) {
        await (sbClient as any).from('pds_parser_requests').insert({
          deal_id: deal?.id ?? null,
          document_id: unknownParserDoc.docId,
          original_filename: unknownParserDoc.fileName,
          bank_name: parserRequestForm.bankName.trim(),
          country: parserRequestForm.country,
          account_type: parserRequestForm.accountType,
          notes: parserRequestForm.notes.trim() || null,
          error_type: 'InvalidSchemaError',
          error_message: unknownParserDoc.errorMessage,
        });
      }

      // 2. Send email notification (best-effort — don't block on failure)
      fetch('/api/request-parser', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bank_name: parserRequestForm.bankName.trim(),
          country: parserRequestForm.country,
          account_type: parserRequestForm.accountType,
          notes: parserRequestForm.notes.trim() || '',
          deal_id: deal?.id ?? '',
          document_id: unknownParserDoc.docId,
          original_filename: unknownParserDoc.fileName,
        }),
      }).catch(() => {/* silently ignore email errors */});

      setParserRequestSubmitted(true);
    } catch {
      setParserRequestSubmitted(true); // still show confirmation even if insert fails
    } finally {
      setParserRequestSubmitting(false);
    }
  };

  const run = exportData?.analysis_run;
  const snapshot = exportData?.snapshot;
  const entities = exportData?.entities ?? [];
  const txnMap = exportData?.txn_entity_map ?? [];

  const entityBreakdownByCategory = computeEntityBreakdownByCategory(exportData, rawTransactions, entities, txnMap);

  const entityBreakdown: EntityBreakdownRow[] = entityBreakdownByCategory.flatMap((c) => c.rows);

  const totalOutflow = entityBreakdown
    .filter((r) => ['supplier', 'payroll'].includes(r.role))
    .reduce((s, r) => s + r.totalAbsCents, 0);
  const payrollTotal = entityBreakdown
    .filter((r) => r.role === 'payroll')
    .reduce((s, r) => s + r.totalAbsCents, 0);
  const topSuppliers = entityBreakdown
    .filter((r) => r.role === 'supplier')
    .slice(0, 5);
  const topRevenue = entityBreakdown
    .filter((r) =>
      ['revenue_operational', 'revenue_non_operational'].includes(r.role)
    )
    .slice(0, 5);
  const largestRevenuePct =
    topRevenue.length > 0
      ? entityBreakdown
          .filter((r) =>
            ['revenue_operational', 'revenue_non_operational'].includes(r.role)
          )
          .reduce((max, r) => Math.max(max, r.pctBps / 100), 0)
      : 0;

  const queueHasPending = statementQueue.some(
    (item) => item.status === 'processing' || item.status === 'uploading'
  );
  const queueHasFailures = statementQueue.some((item) => item.status === 'failed');
  const queueAllReady = statementQueue.length > 0 && statementQueue.every((item) => item.status === 'ready');

  const formatCents = (c: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency ?? deal?.currency ?? 'KES',
      minimumFractionDigits: 2,
    }).format(c / 100);

  const dealId = deal?.id ?? searchParams.get('deal_id') ?? null;
  const dealShortId = dealId ? dealId.slice(0, 16).toUpperCase() : '—';
  const isProcessing = analysisState === 'uploading' || analysisState === 'polling' || analysisState === 'exporting';

  const bankQueue = statementQueue.filter((item) => docTypeByDocId.current.get(item.id) !== 'audited');
  const auditedQueue = statementQueue.filter((item) => docTypeByDocId.current.get(item.id) === 'audited');
  const bankReady = bankQueue.filter((i) => i.status === 'ready').length;
  const auditedReady = auditedQueue.filter((i) => i.status === 'ready').length;

  // Pipeline stage derived from analysisState
  const pipelineStages: PipelineStage[] = computePipelineStages(analysisState, statementQueue, rawTransactions, entities, run, snapshot);

  const confidence = snapshot?.confidence_score ?? (run as any)?.confidence_score ?? null;

  const TABS = ['documents', 'analysis', 'review', 'queue', 'snapshot'] as const;
  const TAB_LABELS: Record<string, string> = { documents: 'Documents', analysis: 'Analysis', review: 'Parity Review', queue: 'Review Queue', snapshot: 'Snapshot' };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--bg)', fontFamily: "'IBM Plex Sans', sans-serif", color: 'var(--t0)' }}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
      `}</style>

      {/* Sidebar */}
      <DealSidebar
        deal={deal}
        dealName={dealName}
        dealId={dealId}
        activeTab={activeTab}
        setActiveTab={(tab) => { userSelectedTabRef.current = true; setActiveTab(tab); }}
        needsReviewCount={needsReviewItems.length}
      />

      {/* Main */}
      <div style={{ marginLeft: 200, flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        {/* Top bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 40px', height: 48, borderBottom: '1px solid var(--s3)', background: 'var(--s2)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.08em' }}>
            <span style={{ cursor: 'pointer', color: 'var(--t2)' }} onClick={() => router.push('/deals/new')}>DEALS</span>
            {dealShortId !== '—' && <><span>·</span><span style={{ color: 'var(--t2)' }}>{dealShortId}</span></>}
            <span>·</span>
            <span style={{ color: 'var(--t1)' }}>{TAB_LABELS[activeTab].toUpperCase()}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {isProcessing && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: '#818CF8', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.1em' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#818CF8', display: 'inline-block', animation: 'blink 1.2s ease-in-out infinite' }} />
                PROCESSING
              </div>
            )}
            {analysisState === 'done' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--green)', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.1em' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--green)', display: 'inline-block' }} />
                COMPLETE
              </div>
            )}
          </div>
        </div>

        {/* Content */}
        <div style={{ flex: 1, padding: '32px 40px 48px', maxWidth: 1100, width: '100%' }}>
          {/* Deal header */}
          <div style={{ marginBottom: 24 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--t0)', margin: 0, letterSpacing: '-0.01em' }}>
              {deal?.name || dealName || 'New Deal'}
            </h1>
            {dealId && (
              <div style={{ marginTop: 6, fontSize: 12, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span>{dealShortId}</span>
                <span style={{ color: 'var(--b1)' }}>·</span>
                <span>{currency ?? deal?.currency ?? 'KES'}</span>
                {statementQueue.length > 0 && <><span style={{ color: 'var(--b1)' }}>·</span><span>{statementQueue.length} document{statementQueue.length !== 1 ? 's' : ''}</span></>}
                {rawTransactions.length > 0 && <><span style={{ color: 'var(--b1)' }}>·</span><span>{rawTransactions.length} transactions</span></>}
              </div>
            )}
          </div>

          {/* Tab nav */}
          <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--s3)', marginBottom: 28 }}>
            {TABS.map((tab) => (
              <button
                key={tab}
                onClick={() => { userSelectedTabRef.current = true; setActiveTab(tab); }}
                style={{ padding: '10px 20px', fontSize: 13, fontWeight: 500, color: activeTab === tab ? 'var(--accent)' : 'var(--t2)', background: 'transparent', border: 'none', borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent', cursor: 'pointer', transition: 'all 0.15s', fontFamily: "'IBM Plex Sans', sans-serif", marginBottom: -1 }}
              >
                {TAB_LABELS[tab]}
              </button>
            ))}
          </div>

          {/* ── DOCUMENTS TAB ── */}
          {activeTab === 'documents' && (
            <DocumentsTab
              deal={deal}
              statementQueue={statementQueue}
              bankQueue={bankQueue}
              bankReady={bankReady}
              unknownFormatDocIds={unknownFormatDocIds}
              onRequestParser={setUnknownParserDoc}
              analysisState={analysisState}
              onBankDrop={handleBankDrop}
              onRemoveStatement={(id) => {
                setStatementQueue((prev) => prev.filter((q) => q.id !== id));
                if (deal) queryClient.invalidateQueries({ queryKey: dealDocumentsKey(deal.id) });
              }}
              auditedFinancialsList={auditedFinancialsList}
              declarationType={declarationType}
              setDeclarationType={setDeclarationType}
              auditedConfirmForm={auditedConfirmForm}
              setAuditedConfirmForm={setAuditedConfirmForm}
              auditedUploading={auditedUploading}
              auditedUploadError={auditedUploadError}
              setAuditedUploadError={setAuditedUploadError}
              onAuditedDrop={handleAuditedDrop}
              auditedSaving={auditedSaving}
              setAuditedSaving={setAuditedSaving}
              loadAuditedFinancials={loadAuditedFinancials}
              queueHasPending={queueHasPending}
              isProcessing={isProcessing}
              onInitialiseAnalysis={() => { userSelectedTabRef.current = true; setActiveTab('analysis'); void runAnalysis(); }}
              errorMsg={errorMsg}
            />
          )}

          {/* ── ANALYSIS TAB ── */}
          {activeTab === 'analysis' && (
            <AnalysisTab
              analysisState={analysisState}
              run={run}
              isProcessing={isProcessing}
              statementQueue={statementQueue}
              rawTransactions={rawTransactions}
              pipelineStages={pipelineStages}
              monthlyCashflow={monthlyCashflow}
              creditScoringInputs={creditScoringInputs}
              currency={currency}
              dealCurrency={deal?.currency}
              formatCents={formatCents}
              reconciliationDetail={reconciliationDetail}
              auditedFinancialsList={auditedFinancialsList}
              entityBreakdownByCategory={entityBreakdownByCategory}
              entityBreakdown={entityBreakdown}
              needsReviewItems={needsReviewItems}
              onGoToDocuments={() => { userSelectedTabRef.current = true; setActiveTab('documents'); }}
              onGoToQueue={() => { userSelectedTabRef.current = true; setActiveTab('queue'); }}
              onDrill={setDrillModal}
              errorMsg={errorMsg}
              onRetry={retryRehydrate}
            />
          )}

          {/* ── PARITY REVIEW TAB ── Intelligence Console */}
          {/* Keep mounted at all times so ParityReviewChat never loses its state
              (chat history, conversation context) when the user switches tabs. */}
          <div style={{ display: activeTab === 'review' ? 'block' : 'none' }}>
            <ParityReviewTab
              deal={deal}
              entities={entities}
              rawTransactions={rawTransactions}
              creditScoringInputs={creditScoringInputs}
              confidence={confidence}
              analysisState={analysisState}
              statementQueue={statementQueue}
              needsReviewItems={needsReviewItems}
              onGoToQueue={() => { userSelectedTabRef.current = true; setActiveTab('queue'); }}
              onGoToSnapshot={() => { userSelectedTabRef.current = true; setActiveTab('snapshot'); }}
            />
          </div>

          {/* ── REVIEW QUEUE TAB ── Override / Reclassify */}
          {activeTab === 'queue' && (
            <ReviewQueueTab
              deal={deal}
              analystInitials={userInitials}
              onQueueUpdate={(remaining) => {
                setNeedsReviewItems(prev => {
                  if (prev.length === remaining) return prev;
                  return prev.slice(0, remaining);
                });
              }}
            />
          )}

          {/* ── SNAPSHOT TAB ── */}
          {activeTab === 'snapshot' && (
            <SnapshotTab
              run={run}
              snapshot={snapshot}
              analysisState={analysisState}
              onReExport={handleReExport}
              onDownloadCSV={handleDownloadCSV}
              exportSuccess={exportSuccess}
              exportError={exportError}
              lastExportedAt={lastExportedAt}
            />
          )}

        </div>
      </div>

      {/* ── Unknown Parser Modal ── */}
      <UnknownParserModal
        doc={unknownParserDoc}
        form={parserRequestForm}
        setForm={setParserRequestForm}
        submitting={parserRequestSubmitting}
        submitted={parserRequestSubmitted}
        onSubmit={handleParserRequestSubmit}
        onClose={() => { setUnknownParserDoc(null); setParserRequestSubmitted(false); setParserRequestForm({ bankName: '', country: 'Kenya', accountType: 'Business Current', notes: '' }); }}
      />

      {/* ── Transaction Drill-Down Modal ── */}
      <TransactionDrillModal
        drillModal={drillModal}
        onClose={() => setDrillModal(null)}
        formatCents={formatCents}
      />

    </div>
  );
}

export default function V1DealPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>LOADING…</div>}>
      <V1DealPageInner />
    </Suspense>
  );
}
