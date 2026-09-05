import { NextResponse } from 'next/server'
import { requireAdminSession } from '@/lib/require-admin-session'

// Backend gates GET /v1/deals/{deal_id}/snapshot/pdf behind
// _require_snapshot_access (PAR-175): Musa x-api-key, an "admin"-scoped
// x-api-key, or a Supabase user JWT. This admin app has no per-deal user
// session to forward, so it proxies with the admin-scoped key instead —
// the browser keeps linking to this same-origin route (admin session
// cookie), and this route attaches the credential the backend actually
// wants server-side.
const BACKEND_API_URL = process.env.BACKEND_API_URL || 'https://parity-backend-prod-121148713552.us-central1.run.app'

export async function GET(_req: Request, { params }: { params: Promise<{ dealId: string }> }) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const adminApiKey = process.env.ADMIN_BACKEND_API_KEY
  if (!adminApiKey) {
    return NextResponse.json({ error: 'ADMIN_BACKEND_API_KEY is not configured' }, { status: 500 })
  }

  const { dealId } = await params
  const upstream = await fetch(`${BACKEND_API_URL}/v1/deals/${encodeURIComponent(dealId)}/snapshot/pdf`, {
    headers: { 'x-api-key': adminApiKey },
  })

  if (!upstream.ok) {
    const detail = await upstream.text().catch(() => '')
    return NextResponse.json({ error: 'Failed to fetch snapshot PDF', detail }, { status: upstream.status })
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/pdf',
      'Content-Disposition': upstream.headers.get('content-disposition') || `attachment; filename="parity_snapshot_${dealId}.pdf"`,
    },
  })
}
