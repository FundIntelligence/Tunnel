'use client'

type Status = string

interface StatusBadgeProps {
  status: Status
}

function getStatusStyle(status: string): React.CSSProperties {
  const s = status?.toLowerCase() ?? ''
  if (s === 'pending' || s === 'processing') {
    return { background: 'var(--amber-d)', color: 'var(--amber)', borderColor: 'rgba(200,150,12,0.20)' }
  }
  if (s === 'completed' || s === 'done' || s === 'processed' || s === 'active' || s === 'true') {
    return { background: 'var(--green-d)', color: 'var(--green)', borderColor: 'rgba(21,128,61,0.18)' }
  }
  if (s === 'failed' || s === 'error' || s === 'false') {
    return { background: 'var(--red-d)', color: 'var(--red)', borderColor: 'rgba(220,38,38,0.16)' }
  }
  if (s === 'in_progress' || s === 'inprogress') {
    return { background: 'var(--teal-d)', color: 'var(--teal)', borderColor: 'rgba(13,148,136,0.20)' }
  }
  return { background: 'var(--bg2)', color: 'var(--t1)', borderColor: 'var(--border)' }
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const style = getStatusStyle(status)
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: 4,
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 11,
      fontWeight: 500,
      letterSpacing: '0.04em',
      border: '1px solid',
      ...style,
    }}>
      {status}
    </span>
  )
}
