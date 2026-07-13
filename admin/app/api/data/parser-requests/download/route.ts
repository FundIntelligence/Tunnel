import { getSupabaseAdmin, parseEnv } from '@/lib/supabase-env'
import { NextRequest, NextResponse } from 'next/server'

// GET /api/data/parser-requests/download?path=<storage_path>&env=<prod|staging>
//
// Parser-request sample files live in the private `parser-requests` bucket. The
// admin reads them with the service-role client and hands back a short-lived
// signed URL — the bucket itself stays private (no public policies), matching
// the post-incident storage posture.
export async function GET(request: NextRequest) {
  const env = parseEnv(request)
  const path = request.nextUrl.searchParams.get('path')
  if (!path) {
    return NextResponse.json({ error: 'path is required' }, { status: 400 })
  }

  const supabase = getSupabaseAdmin(env)
  const { data, error } = await supabase.storage
    .from('parser-requests')
    .createSignedUrl(path, 300) // 5 minutes

  if (error || !data?.signedUrl) {
    return NextResponse.json(
      { error: error?.message ?? 'could not sign url' },
      { status: 404 },
    )
  }
  return NextResponse.json({ url: data.signedUrl })
}
