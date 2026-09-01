'use client'

type Env = 'prod' | 'staging' | 'sandbox'

const STYLES: Record<Env, { border: string; background: string; color: string; label: string }> = {
  prod: { border: '#E24B4A44', background: '#2C1515', color: '#E24B4A', label: '● PROD' },
  staging: { border: '#1D9E7544', background: '#122117', color: '#1D9E75', label: '● STAGING' },
  // Sandbox is a third, distinct environment (ParitySandbox project) — not
  // a point on the prod/staging binary, so it gets its own color rather
  // than reusing either of theirs.
  sandbox: { border: '#C9A22744', background: '#241D0D', color: '#C9A227', label: '● SANDBOX' },
}

export function EnvBadge({ env }: { env: Env }) {
  const s = STYLES[env]
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10,
      fontWeight: 500,
      padding: '2px 8px',
      borderRadius: 3,
      border: `1px solid ${s.border}`,
      background: s.background,
      color: s.color,
      letterSpacing: '0.05em',
    }}>
      {s.label}
    </span>
  )
}
