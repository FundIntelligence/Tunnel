'use client';

import type { DrillModalState } from './types';

export interface TransactionDrillModalProps {
  drillModal: DrillModalState | null;
  onClose: () => void;
  formatCents: (c: number) => string;
}

export default function TransactionDrillModal({ drillModal, onClose, formatCents }: TransactionDrillModalProps) {
  if (!drillModal) return null;
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(8,12,24,0.85)', backdropFilter: 'blur(4px)' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 10, width: 680, maxWidth: '92vw', maxHeight: '80vh', display: 'flex', flexDirection: 'column', boxShadow: '0 24px 64px rgba(0,0,0,0.6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 24px', borderBottom: '1px solid var(--s3)', borderLeft: `3px solid ${drillModal.color}`, flexShrink: 0 }}>
          <div>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--t1)' }}>{drillModal.title}</span>
            <span style={{ fontSize: 11, color: 'var(--t2)', marginLeft: 10, fontFamily: "'IBM Plex Mono', monospace" }}>{drillModal.rows.length} transaction{drillModal.rows.length !== 1 ? 's' : ''}</span>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--t2)', fontSize: 18, cursor: 'pointer', padding: '0 0 0 12px', lineHeight: 1 }}>×</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 120px', gap: 8, padding: '10px 24px', borderBottom: '1px solid var(--s3)', flexShrink: 0 }}>
          {['DATE', 'DESCRIPTION', 'AMOUNT'].map((h) => <span key={h} style={{ fontSize: 9, fontWeight: 700, color: 'var(--t1)', letterSpacing: '0.1em' }}>{h}</span>)}
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {drillModal.rows.length === 0 && (
            <div style={{ padding: '32px 24px', textAlign: 'center', color: 'var(--t2)', fontSize: 12 }}>No transactions found for this entity.</div>
          )}
          {drillModal.rows.map((t, i) => {
            const amt = Number(t.signed_amount_cents ?? 0);
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '100px 1fr 120px', gap: 8, padding: '9px 24px', borderBottom: '1px solid var(--s3)', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>{(t.txn_date ?? '') as string}</span>
                <span style={{ fontSize: 12, color: 'var(--t1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(t.description || t.narrative || '—') as string}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: amt >= 0 ? 'var(--green)' : 'var(--red)', fontFamily: "'IBM Plex Mono', monospace", textAlign: 'right' }}>{formatCents(Math.abs(amt))}</span>
              </div>
            );
          })}
        </div>
        {drillModal.rows.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 24px', borderTop: '1px solid var(--s3)', flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: 'var(--t2)' }}>Total</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: drillModal.color, fontFamily: "'IBM Plex Mono', monospace" }}>
              {formatCents(drillModal.rows.reduce((s, t) => s + Math.abs(Number(t.signed_amount_cents ?? 0)), 0))}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
