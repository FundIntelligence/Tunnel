export function toEAT(utcString: string): string {
  if (!utcString) return '—'
  const d = new Date(utcString)
  const formatted = d.toLocaleString('en-GB', {
    timeZone: 'Africa/Nairobi', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  return formatted.replace(', ', ' · ') + ' EAT'
}
