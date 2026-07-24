'use client';

import { useEffect, useState } from 'react';

// Keep in sync with the "PIPELINE STAGES" names in lib/deal-analytics.ts —
// 'ingestion' covers both Document ingestion and Transaction parsing (they
// read as one continuous step to an analyst), 'classification' covers both
// Classification and Entity extraction (matching counterparties IS entity
// resolution), 'reconciliation' covers both Reconciliation and Confidence
// scoring (no dedicated copy exists for the latter — it's a direct
// consequence of the reconciliation delta).
export type AnalystStatusStage =
  | 'ingestion'
  | 'classification'
  | 'reconciliation'
  | 'snapshot'
  | 'checking'
  | 'generic';

const PHRASES: Record<AnalystStatusStage, string[]> = {
  ingestion: ['Reading statement…', 'Parsing line items…', 'Canonicalising records…'],
  classification: ['Applying classification rules…', 'Matching counterparties…', 'Resolving entities…'],
  reconciliation: ['Reconciling declared vs. observed…', 'Cross-checking balances…'],
  snapshot: ['Sealing snapshot…', 'Computing hash…', 'Generating export…'],
  checking: ['Confirming prior analysis…', 'Retrieving saved results…'],
  generic: [
    'Reviewing transaction history…',
    'Cross-referencing entries…',
    'Checking the ledger…',
    'Tracing cash flow…',
  ],
};

const FADE_MS = 220;

export interface AnalystStatusProps {
  /** Which real pipeline stage this wait corresponds to. Defaults to the generic fallback pool. */
  stage?: AnalystStatusStage;
  /** Time each phrase is shown before cross-fading to the next, in ms. */
  intervalMs?: number;
  /** Size (px) of the Parity mark. */
  size?: number;
  className?: string;
}

/**
 * Rotating, finance/analyst-themed status line for any generic wait state,
 * with the Parity mark ("P/") as the spinner. Mount this only while
 * genuinely waiting — unmounting (the caller's job, not this component's)
 * is what stops the rotation the instant real data arrives. This component
 * never gates or delays anything itself; it only fills the wait.
 */
export default function AnalystStatus({
  stage = 'generic',
  intervalMs = 2000,
  size = 20,
  className,
}: AnalystStatusProps) {
  const phrases = PHRASES[stage] ?? PHRASES.generic;
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  // Reset to the start of the new stage's phrase set immediately — never show
  // a leftover phrase from a different stage while the rotation catches up.
  useEffect(() => {
    setIndex(0);
    setVisible(true);
  }, [stage]);

  useEffect(() => {
    if (phrases.length <= 1) return;
    let fadeTimeout: ReturnType<typeof setTimeout>;
    const rotation = setInterval(() => {
      setVisible(false);
      fadeTimeout = setTimeout(() => {
        setIndex((i) => (i + 1) % phrases.length);
        setVisible(true);
      }, FADE_MS);
    }, intervalMs);
    return () => {
      clearInterval(rotation);
      clearTimeout(fadeTimeout);
    };
  }, [phrases, intervalMs]);

  // Colors come from --mark-ink / --mark-teal (app/globals.css), which flip with
  // the .dark class exactly like every other themed color in the app. Deriving
  // this from next-themes' useTheme() instead would race the hydration-safe
  // resolvedTheme (undefined until mount), causing a real flash of invisible
  // ink on a dark background on first paint — CSS vars are correct at first paint.
  const height = size * (52 / 56);

  return (
    <span className={className} style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <svg
        className="analyst-status-mark"
        aria-hidden="true"
        viewBox="0 0 56 52"
        width={size}
        height={height}
        xmlns="http://www.w3.org/2000/svg"
      >
        <text x="0" y="40" fontFamily="'IBM Plex Sans',sans-serif" fontWeight={600} fontSize="44" fill="var(--mark-ink)">P</text>
        <text x="30" y="40" fontFamily="'IBM Plex Sans',sans-serif" fontWeight={600} fontSize="44" fill="var(--mark-teal)">/</text>
      </svg>
      <span
        className="analyst-status-phrase"
        role="status"
        aria-live="polite"
        style={{ fontSize: 13, color: 'var(--t2)', opacity: visible ? 1 : 0 }}
      >
        {phrases[index]}
      </span>
    </span>
  );
}
