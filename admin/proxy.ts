import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { ALLOWED_EMAILS } from '@/lib/allowed-emails'
import { isOntologyQaAllowed } from '@/lib/ontology-qa-access'

export async function proxy(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  const { data: { user } } = await supabase.auth.getUser()
  const path = request.nextUrl.pathname
  const isLoginPage = path.startsWith('/login')
  const isAuthCallback = path.startsWith('/auth/callback')

  if (!user) {
    if (!isLoginPage && !isAuthCallback) {
      return NextResponse.redirect(new URL('/login', request.url))
    }
    return supabaseResponse
  }

  const email = user.email?.toLowerCase() ?? ''
  if (!ALLOWED_EMAILS.includes(email)) {
    const url = new URL('/login?error=unauthorized', request.url)
    const res = NextResponse.redirect(url)
    await supabase.auth.signOut()
    return res
  }

  if (isLoginPage) {
    return NextResponse.redirect(new URL('/parser-requests', request.url))
  }

  const isOntologyQaPath = path.startsWith('/ontology-qa') || path.startsWith('/api/data/ontology-qa')
  if (isOntologyQaPath && !isOntologyQaAllowed(email)) {
    if (path.startsWith('/api/')) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
    }
    return NextResponse.redirect(new URL('/parser-requests', request.url))
  }

  return supabaseResponse
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
}
