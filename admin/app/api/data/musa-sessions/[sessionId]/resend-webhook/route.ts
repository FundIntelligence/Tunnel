import { NextResponse } from 'next/server'
import { requireAdminSession } from '@/lib/require-admin-session'

// Backend gates POST /api/musa/admin/sessions/{id}/resend-webhook behind
// its own admin-only dependency (PAR-174): an "admin"-scoped x-api-key or
// a Supabase user JWT — deliberately narrower than the snapshot-pdf proxy's
// gate, since a Musa partner key must NOT be able to trigger this. This
// admin app has no per-deal user session to forward, so it proxies with
// the admin-scoped key instead, same pattern as snapshot-pdf/route.ts.
const BACKEND_API_URL = process.env.BACKEND_API_URL || 'https://parity-backend-prod-121148713552.us-central1.run.app'

export async function POST(_req: Request, { params }: { params: Promise<{ sessionId: string }> }) {
  const session = await requireAdminSession()
  if (session instanceof NextResponse) return session

  const adminApiKey = process.env.ADMIN_BACKEND_API_KEY
  if (!adminApiKey) {
    return NextResponse.json({ error: 'ADMIN_BACKEND_API_KEY is not configured' }, { status: 500 })
  }

  const { sessionId } = await params
  const upstream = await fetch(
    `${BACKEND_API_URL}/api/musa/admin/sessions/${encodeURIComponent(sessionId)}/resend-webhook`,
    { method: 'POST', headers: { 'x-api-key': adminApiKey } }
  )

  const data = await upstream.json().catch(() => null)
  if (!upstream.ok) {
    return NextResponse.json(
      { error: data?.detail || 'Failed to resend webhook' },
      { status: upstream.status }
    )
  }
  return NextResponse.json(data)
}
