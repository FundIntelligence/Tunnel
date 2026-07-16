'use client'

export function EnvBadge({ env }: { env: 'prod' | 'staging' }) {
  const isProd = env === 'prod'
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10,
      fontWeight: 500,
      padding: '2px 8px',
      borderRadius: 3,
      border: `1px solid ${isProd ? '#E24B4A44' : '#1D9E7544'}`,
      background: isProd ? '#2C1515' : '#122117',
      color: isProd ? '#E24B4A' : '#1D9E75',
      letterSpacing: '0.05em',
    }}>
      {isProd ? '● PROD' : '● STAGING'}
    </span>
  )
}
