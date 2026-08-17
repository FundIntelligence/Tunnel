'use client';

import type { ParserRequestDoc, ParserRequestForm } from './types';

export interface UnknownParserModalProps {
  doc: ParserRequestDoc | null;
  form: ParserRequestForm;
  setForm: React.Dispatch<React.SetStateAction<ParserRequestForm>>;
  submitting: boolean;
  submitted: boolean;
  onSubmit: () => Promise<void>;
  onClose: () => void;
}

export default function UnknownParserModal({
  doc,
  form,
  setForm,
  submitting,
  submitted,
  onSubmit,
  onClose,
}: UnknownParserModalProps) {
  if (!doc) return null;
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(8,12,24,0.85)', backdropFilter: 'blur(4px)' }}>
      <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 10, width: 480, maxWidth: '90vw', padding: 28, boxShadow: '0 24px 64px rgba(0,0,0,0.6)' }}>
        {!submitted ? (
          <>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--amber)', display: 'inline-block' }} />
                  <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', letterSpacing: '0.1em', fontFamily: "'IBM Plex Mono', monospace" }}>UNKNOWN FORMAT</span>
                </div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--t0)', margin: 0 }}>Parser not found for this bank</h3>
                <p style={{ fontSize: 12, color: 'var(--t2)', marginTop: 6, lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace" }}>{doc.fileName}</span> uses a format we don't currently support. Request a parser and we'll add it to the pipeline.
                </p>
              </div>
              <button
                onClick={onClose}
                style={{ background: 'transparent', border: 'none', color: 'var(--t2)', fontSize: 18, cursor: 'pointer', padding: '0 0 0 12px', lineHeight: 1, flexShrink: 0 }}
              >×</button>
            </div>

            {/* Form */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 11, color: 'var(--t2)', marginBottom: 5, letterSpacing: '0.06em' }}>BANK NAME *</label>
                <input
                  type="text"
                  value={form.bankName}
                  onChange={(e) => setForm((p) => ({ ...p, bankName: e.target.value }))}
                  placeholder="e.g. Stanbic Bank, Absa, DTB"
                  autoFocus
                  style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '8px 12px', color: 'var(--t0)', fontSize: 13, outline: 'none', boxSizing: 'border-box', fontFamily: "'IBM Plex Sans', sans-serif" }}
                />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 11, color: 'var(--t2)', marginBottom: 5, letterSpacing: '0.06em' }}>COUNTRY</label>
                  <select
                    value={form.country}
                    onChange={(e) => setForm((p) => ({ ...p, country: e.target.value }))}
                    style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '8px 12px', color: 'var(--t1)', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
                  >
                    {['Kenya', 'Nigeria', 'Uganda', 'Tanzania', 'Ghana', 'South Africa', 'Rwanda', 'Ethiopia', 'Other'].map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 11, color: 'var(--t2)', marginBottom: 5, letterSpacing: '0.06em' }}>ACCOUNT TYPE</label>
                  <select
                    value={form.accountType}
                    onChange={(e) => setForm((p) => ({ ...p, accountType: e.target.value }))}
                    style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '8px 12px', color: 'var(--t1)', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
                  >
                    {['Business Current', 'Business Savings', 'Personal Current', 'Personal Savings', 'Mobile Money', 'Other'].map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 11, color: 'var(--t2)', marginBottom: 5, letterSpacing: '0.06em' }}>NOTES <span style={{ color: 'var(--b1)' }}>optional</span></label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
                  placeholder="Any additional info about the format — e.g. PDF vs CSV, layout description…"
                  rows={2}
                  style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '8px 12px', color: 'var(--t1)', fontSize: 12, outline: 'none', resize: 'none', boxSizing: 'border-box', fontFamily: "'IBM Plex Sans', sans-serif" }}
                />
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              <button
                onClick={onSubmit}
                disabled={!form.bankName.trim() || submitting}
                style={{ flex: 1, padding: '10px 0', background: !form.bankName.trim() || submitting ? 'var(--s3)' : 'var(--accent)', color: !form.bankName.trim() || submitting ? 'var(--t2)' : '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: !form.bankName.trim() || submitting ? 'not-allowed' : 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
              >
                {submitting ? 'Submitting…' : 'Request parser →'}
              </button>
              <button
                onClick={onClose}
                style={{ padding: '10px 16px', background: 'transparent', color: 'var(--t2)', border: '1px solid var(--b1)', borderRadius: 6, fontSize: 13, cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
              >
                Dismiss
              </button>
            </div>
          </>
        ) : (
          /* Confirmation */
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'rgba(20,184,166,0.12)', border: '1px solid rgba(20,184,166,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M4 10l4.5 4.5L16 6" stroke="#5EEAD4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--t0)', margin: '0 0 8px' }}>Parser request submitted</h3>
            <p style={{ fontSize: 13, color: 'var(--t2)', margin: '0 0 20px', lineHeight: 1.5 }}>
              We've logged <strong style={{ color: 'var(--accent)' }}>{form.bankName}</strong> ({form.country}) for the engineering queue. You'll be able to re-upload once the parser is live.
            </p>
            <button
              onClick={onClose}
              style={{ padding: '9px 20px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
