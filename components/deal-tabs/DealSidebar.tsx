'use client';

import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import type { Deal } from '@/lib/v1-api';
import { ThemeToggle } from '@/components/ThemeToggle';

export type DealTab = 'documents' | 'analysis' | 'review' | 'queue' | 'snapshot';

export interface DealSidebarProps {
  deal: Deal | null;
  dealName: string;
  dealId: string | null;
  activeTab: DealTab;
  setActiveTab: (tab: DealTab) => void;
  needsReviewCount: number;
}

export default function DealSidebar({
  deal,
  dealName,
  dealId,
  activeTab,
  setActiveTab,
  needsReviewCount,
}: DealSidebarProps) {
  const router = useRouter();

  return (
    <aside style={{ width: 200, background: 'var(--s1)', borderRight: '1px solid var(--s3)', display: 'flex', flexDirection: 'column', padding: '20px 0', position: 'fixed', top: 0, left: 0, bottom: 0, zIndex: 50, flexShrink: 0 }}>
      <div style={{ padding: '0 16px 20px', borderBottom: '1px solid var(--s3)' }}>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, letterSpacing: '0.08em', fontWeight: 700 }}><span style={{ color: 'var(--accent)' }}>P/</span> <span style={{ color: '#fff' }}>PARITY</span><span style={{ fontSize: 9, verticalAlign: 'super', color: 'var(--t1)' }}>v2.0</span></div>
        {dealName && <div style={{ fontSize: 10, color: 'var(--t1)', marginTop: 6, letterSpacing: '0.08em', background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 4, padding: '3px 8px', display: 'inline-flex', gap: 6 }}>{dealName.toUpperCase()}</div>}
      </div>
      <nav style={{ flex: 1, padding: '12px 0', overflowY: 'auto' }}>
        <button
          onClick={() => router.push('/deals')}
          style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', padding: '6px 16px 12px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--t1)', fontSize: 12, fontFamily: "'IBM Plex Sans', sans-serif" }}
        >
          <span style={{ fontSize: 13 }}>←</span>
          All deals
        </button>

        {/* Divider */}
        {deal && <div style={{ margin: '4px 16px 8px', borderTop: '1px solid var(--s3)' }} />}

        {[
          { label: 'Documents', tab: 'documents' as const },
          { label: 'Analysis', tab: 'analysis' as const },
          { label: 'Parity Review', tab: 'review' as const },
          { label: 'Review Queue', tab: 'queue' as const, badge: needsReviewCount > 0 ? needsReviewCount : undefined },
          { label: 'Snapshot', tab: 'snapshot' as const },
        ].map((item) => (
          <button
            key={item.tab}
            onClick={() => setActiveTab(item.tab)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: '9px 16px', background: activeTab === item.tab ? 'rgba(20,184,166,0.1)' : 'transparent', borderLeft: activeTab === item.tab ? '2px solid var(--accent)' : '2px solid transparent', border: 'none', color: activeTab === item.tab ? 'var(--accent)' : 'var(--t1)', fontSize: 13, fontFamily: "'IBM Plex Sans', sans-serif", cursor: 'pointer', textAlign: 'left' }}
          >
            <span>{item.label}</span>
            {'badge' in item && item.badge != null && (
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--amber)', background: 'rgba(245,158,11,0.1)', padding: '1px 5px', borderRadius: 3, fontFamily: "'IBM Plex Mono', monospace" }}>{item.badge}</span>
            )}
          </button>
        ))}
        <div style={{ margin: '12px 0 4px', padding: '0 16px', fontSize: 9, color: 'var(--t2)', letterSpacing: '0.1em' }}>DEAL TOOLS</div>
        {['Benchmark', 'Monitor', 'Registry'].map((label) => (
          <div key={label} style={{ padding: '9px 16px', color: 'var(--t2)', fontSize: 13, borderLeft: '2px solid transparent', display: 'flex', alignItems: 'center', gap: 8 }}>
            {label}
            <span style={{ fontSize: 9, background: 'var(--s1)', color: 'var(--t2)', padding: '1px 4px', borderRadius: 2 }}>SOON</span>
          </div>
        ))}
        <div style={{ margin: '12px 0 4px', padding: '0 16px', fontSize: 9, color: 'var(--t2)', letterSpacing: '0.1em' }}>FORMAT DESK</div>
        <button
          onClick={() => router.push('/parsers/request')}
          style={{ display: 'flex', alignItems: 'center', width: '100%', padding: '9px 16px', background: 'transparent', borderLeft: '2px solid transparent', border: 'none', color: 'var(--t1)', fontSize: 13, fontFamily: "'IBM Plex Sans', sans-serif", cursor: 'pointer', textAlign: 'left', gap: 6 }}
        >
          <span style={{ fontSize: 11, lineHeight: 1, fontFamily: "'IBM Plex Mono', monospace", color: 'var(--t2)' }}>//</span>
          New Bank Format
        </button>
      </nav>
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--s3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          {dealId && (
            <div style={{ fontSize: 10, color: 'var(--t2)', fontFamily: "'IBM Plex Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {dealId.slice(0, 8)}…
            </div>
          )}
          <ThemeToggle />
        </div>
        <button onClick={() => { if (supabase) supabase.auth.signOut(); router.push('/login'); }} style={{ width: '100%', padding: '6px 0', background: 'transparent', border: '1px solid var(--s3)', borderRadius: 4, color: 'var(--t2)', fontSize: 12, cursor: 'pointer', fontFamily: "'IBM Plex Sans', sans-serif" }}>
          Sign out
        </button>
      </div>
    </aside>
  );
}
