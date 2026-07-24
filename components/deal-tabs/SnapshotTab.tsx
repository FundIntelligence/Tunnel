'use client';

import type { AnalysisRun, Snapshot } from '@/lib/v1-api';
import type { AnalysisState } from './types';
import AnalystStatus from '@/components/AnalystStatus';

export interface SnapshotTabProps {
  run: AnalysisRun | undefined;
  snapshot: Snapshot | undefined;
  analysisState: AnalysisState;
  onReExport: () => Promise<void>;
  onDownloadCSV: () => Promise<void>;
  exportSuccess: string;
  exportError: string;
  lastExportedAt: Date | null;
}

export default function SnapshotTab({
  run,
  snapshot,
  analysisState,
  onReExport,
  onDownloadCSV,
  exportSuccess,
  exportError,
  lastExportedAt,
}: SnapshotTabProps) {
  return (
    <div style={{ maxWidth: 720 }}>
      {analysisState === 'checking' && !run ? (
        // Same false-negative class as PR #101/#102: 'checking' means we haven't
        // confirmed a snapshot's absence yet, so this must never render the
        // "no snapshot" copy — that would be a confirmed-negative claim before
        // the check has actually resolved.
        <div style={{ padding: '48px 0', display: 'flex', justifyContent: 'center' }}>
          <AnalystStatus stage="checking" />
        </div>
      ) : !run ? (
        <div style={{ padding: '48px 0', textAlign: 'center', color: 'var(--t2)', fontSize: 13 }}>
          Run analysis first to generate a snapshot.
        </div>
      ) : (
        <>
          <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 20, marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t1)', marginBottom: 14 }}>EXPORT SNAPSHOT</div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
              <button onClick={onReExport} disabled={analysisState === 'exporting'}
                style={{ padding: '9px 18px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: analysisState === 'exporting' ? 'not-allowed' : 'pointer', opacity: analysisState === 'exporting' ? 0.6 : 1 }}>
                {analysisState === 'exporting' ? 'Generating PDF…' : 'Save & Export PDF'}
              </button>
              <button onClick={onDownloadCSV}
                style={{ padding: '9px 18px', background: 'transparent', color: 'var(--t1)', border: '1px solid var(--b1)', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                Download CSV
              </button>
            </div>
            {analysisState === 'exporting' && <div style={{ marginBottom: 10 }}><AnalystStatus stage="snapshot" size={16} /></div>}
            {exportSuccess && <div style={{ fontSize: 12, color: 'var(--green)', marginBottom: 10 }}>{exportSuccess}</div>}
            {exportError && <div style={{ fontSize: 12, color: 'var(--red)', marginBottom: 10 }}>{exportError}</div>}
            {lastExportedAt && <div style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>Last exported {lastExportedAt.toLocaleTimeString()}</div>}
          </div>

          {snapshot && (
            <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 8, padding: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--t1)', marginBottom: 14 }}>SNAPSHOT HASHES</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[
                  { label: 'snapshot_id', value: snapshot.id },
                  { label: 'sha256_hash', value: snapshot.sha256_hash },
                  { label: 'financial_state_hash', value: snapshot.financial_state_hash },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div style={{ fontSize: 10, color: 'var(--t2)', marginBottom: 3, letterSpacing: '0.08em' }}>{label}</div>
                    <div style={{ fontSize: 12, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", wordBreak: 'break-all' }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
