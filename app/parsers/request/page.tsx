'use client';

import { useState, useRef } from 'react';
import { useRouter } from 'next/navigation';

const COUNTRIES = [
  'Kenya', 'Nigeria', 'Uganda', 'Tanzania', 'Ghana',
  'South Africa', 'Rwanda', 'Ethiopia', 'Other',
];

const ACCOUNT_TYPES = [
  'Business Current', 'Business Savings', 'Personal Current',
  'Personal Savings', 'Mobile Money', 'Other',
];

export default function RequestParserPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [bankName, setBankName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [country, setCountry] = useState('Kenya');
  const [accountType, setAccountType] = useState('Business Current');
  const [notes, setNotes] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bankName.trim() || !contactEmail.trim() || !file) return;
    setIsSubmitting(true);
    setError('');

    try {
      const formData = new FormData();
      formData.append('bank_name', bankName.trim());
      formData.append('contact_email', contactEmail.trim());
      formData.append('country', country);
      formData.append('account_type', accountType);
      formData.append('notes', notes.trim());
      formData.append('sample_file', file);

      const res = await fetch('/api/request-parser', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { error?: string }).error ?? `Error ${res.status}`);
      }

      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed — please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  /* ── Confirmation screen ─────────────────────────────────────────────────── */
  if (submitted) {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'IBM Plex Sans', sans-serif" }}>
        <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 10, width: 480, maxWidth: '90vw', padding: 40, textAlign: 'center' }}>
          {/* Icon */}
          <div style={{ width: 52, height: 52, borderRadius: '50%', background: 'rgba(20,184,166,0.12)', border: '1px solid rgba(20,184,166,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px' }}>
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <path d="M4.5 11l5 5L17.5 6" stroke="#5EEAD4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--t0)', margin: '0 0 10px' }}>
            Format Submitted
          </h1>
          <p style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6, margin: '0 0 8px' }}>
            We&apos;re onboarding the format for{' '}
            <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{bankName}</span>.
          </p>
          <p style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6, margin: '0 0 28px' }}>
            We&apos;ll notify you at{' '}
            <span style={{ color: 'var(--t1)' }}>{contactEmail}</span> as soon as this format is ready
            — usually within a few hours.
          </p>

          <button
            onClick={() => router.push('/deals')}
            style={{ width: '100%', padding: '11px 0', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}
          >
            Return to Deals
          </button>
        </div>
      </div>
    );
  }

  /* ── Form ────────────────────────────────────────────────────────────────── */
  const canSubmit = bankName.trim() && contactEmail.trim() && file && !isSubmitting;

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, fontFamily: "'IBM Plex Sans', sans-serif" }}>
      <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 10, width: 520, maxWidth: '100%', padding: 36 }}>

        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, letterSpacing: '0.08em', fontWeight: 700 }}>
              <span style={{ color: 'var(--accent)' }}>P/</span> <span style={{ color: '#fff' }}>PARITY</span><span style={{ fontSize: 9, verticalAlign: 'super', color: 'var(--t2)' }}>v2.0</span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--b1)' }}>·</span>
            <span style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", letterSpacing: '0.06em' }}>FORMAT DESK</span>
          </div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--t0)', margin: '0 0 8px' }}>
            New Bank Format
          </h1>
          <p style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.6, margin: 0 }}>
            Upload a sample statement and we&apos;ll onboard this bank format. You&apos;ll be notified as soon as it&apos;s ready — usually within a few hours.
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

          {/* Bank Name */}
          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
              BANK NAME *
            </label>
            <input
              type="text"
              required
              value={bankName}
              onChange={(e) => setBankName(e.target.value)}
              placeholder="e.g. NCBA Bank Kenya"
              autoFocus
              style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', color: 'var(--t0)', fontSize: 13, outline: 'none', boxSizing: 'border-box', fontFamily: "'IBM Plex Sans', sans-serif" }}
            />
          </div>

          {/* Contact Email */}
          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
              CONTACT EMAIL *
            </label>
            <input
              type="email"
              required
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="your@email.com"
              style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', color: 'var(--t0)', fontSize: 13, outline: 'none', boxSizing: 'border-box', fontFamily: "'IBM Plex Sans', sans-serif" }}
            />
          </div>

          {/* Country + Account Type */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
                COUNTRY
              </label>
              <select
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', color: 'var(--t1)', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
              >
                {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
                ACCOUNT TYPE
              </label>
              <select
                value={accountType}
                onChange={(e) => setAccountType(e.target.value)}
                style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', color: 'var(--t1)', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
              >
                {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          {/* Sample File Upload */}
          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
              SAMPLE STATEMENT *
            </label>
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `1px dashed ${isDragging ? 'var(--accent)' : file ? 'rgba(74,222,128,0.4)' : 'var(--b1)'}`,
                borderRadius: 6,
                padding: '20px 16px',
                textAlign: 'center',
                cursor: 'pointer',
                background: isDragging ? 'rgba(20,184,166,0.05)' : file ? 'rgba(74,222,128,0.04)' : 'transparent',
                transition: 'all 0.15s',
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.xlsx,.xls,.csv"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }}
                style={{ display: 'none' }}
              />
              {file ? (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--green)', fontWeight: 700, letterSpacing: '0.08em', marginBottom: 4 }}>FILE ATTACHED</div>
                  <div style={{ fontSize: 13, color: 'var(--t1)', fontFamily: "'IBM Plex Mono', monospace" }}>{file.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--t2)', marginTop: 2 }}>{(file.size / 1024).toFixed(1)} KB</div>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFile(null); }}
                    style={{ marginTop: 8, fontSize: 11, color: 'var(--t2)', background: 'transparent', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: 22, marginBottom: 6 }}>📎</div>
                  <div style={{ fontSize: 13, color: 'var(--t2)' }}>Drag &amp; drop or click to upload</div>
                  <div style={{ fontSize: 11, color: 'var(--b1)', marginTop: 4, letterSpacing: '0.05em' }}>PDF · XLSX · CSV</div>
                </div>
              )}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--t2)', letterSpacing: '0.08em', marginBottom: 6 }}>
              NOTES <span style={{ color: 'var(--b1)', fontWeight: 400 }}>optional</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Any specific formatting quirks — e.g. PDF vs CSV, layout notes, column headers…"
              rows={3}
              style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--b1)', borderRadius: 6, padding: '10px 12px', color: 'var(--t1)', fontSize: 12, outline: 'none', resize: 'none', boxSizing: 'border-box', fontFamily: "'IBM Plex Sans', sans-serif' " }}
            />
          </div>

          {/* Error */}
          {error && (
            <div style={{ fontSize: 12, color: 'var(--red)', fontFamily: "'IBM Plex Mono', monospace", background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)', borderRadius: 6, padding: '8px 12px' }}>
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={!canSubmit}
            style={{ width: '100%', padding: '11px 0', background: canSubmit ? 'var(--accent)' : 'var(--s3)', color: canSubmit ? '#fff' : 'var(--t2)', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: canSubmit ? 'pointer' : 'not-allowed', fontFamily: "'IBM Plex Sans', sans-serif", transition: 'background 0.15s' }}
          >
            {isSubmitting ? 'Submitting…' : 'Submit Bank Format →'}
          </button>

          <p style={{ fontSize: 11, color: 'var(--b1)', textAlign: 'center', margin: 0 }}>
            We&apos;ll email you at {contactEmail || 'your address'} as soon as this format is ready
          </p>

        </form>
      </div>
    </div>
  );
}
