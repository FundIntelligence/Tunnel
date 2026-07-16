export function toEAT(utcString: string): string {
  if (!utcString) return '—'
  const d = new Date(utcString)
  const formatted = d.toLocaleString('en-GB', {
    timeZone: 'Africa/Nairobi',
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
  return formatted.replace(', ', ' · ') + ' EAT'
}

export function timeSince(utcString: string): { label: string; severity: 'ok' | 'warn' | 'alert' } {
  if (!utcString) return { label: '—', severity: 'ok' }
  const ms = Date.now() - new Date(utcString).getTime()
  const mins = Math.floor(ms / 60000)
  const hours = Math.floor(mins / 60)
  const days = Math.floor(hours / 24)

  let label: string
  if (mins < 1) label = 'just now'
  else if (mins < 60) label = `${mins}m`
  else if (hours < 24) label = `${hours}h ${mins % 60}m`
  else label = `${days}d ${hours % 24}h`

  const severity: 'ok' | 'warn' | 'alert' = days >= 3 ? 'alert' : hours >= 24 ? 'warn' : 'ok'
  return { label, severity }
}

export function refreshedLabel(isoString: string): string {
  const secs = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (secs < 60) return `Refreshed ${secs}s ago`
  return `Refreshed ${Math.floor(secs / 60)}m ago`
}
