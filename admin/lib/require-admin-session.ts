import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { ALLOWED_EMAILS } from '@/lib/allowed-emails'

export type AdminSession = { email: string }

// Defense-in-depth: proxy.ts already gates every /api/data/* request with the
// same check before the handler runs. This mirrors it inside the handler so
// the route stays safe even if proxy.ts's matcher is ever narrowed or
// misconfigured (PAR-113).
export async function requireAdminSession(): Promise<AdminSession | NextResponse> {
  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll() {},
      },
    }
  )

  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const email = user.email?.toLowerCase() ?? ''
  if (!ALLOWED_EMAILS.includes(email)) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  return { email }
}
