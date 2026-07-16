import { createClient } from '@supabase/supabase-js'
import { NextRequest } from 'next/server'

export type Env = 'prod' | 'staging'

export function parseEnv(request: NextRequest): Env {
  return request.nextUrl.searchParams.get('env') === 'staging' ? 'staging' : 'prod'
}

export function getSupabaseAdmin(env: Env) {
  const url = env === 'prod'
    ? (process.env.NEXT_PUBLIC_SUPABASE_URL_PROD ?? process.env.NEXT_PUBLIC_SUPABASE_URL)
    : (process.env.NEXT_PUBLIC_SUPABASE_URL_STAGING ?? process.env.NEXT_PUBLIC_SUPABASE_URL)

  const key = env === 'prod'
    ? (process.env.SUPABASE_SERVICE_KEY_PROD ?? process.env.SUPABASE_SERVICE_ROLE_KEY)
    : (process.env.SUPABASE_SERVICE_KEY_STAGING ?? process.env.SUPABASE_SERVICE_ROLE_KEY)

  if (!url || !key) throw new Error(`Missing Supabase env vars for ${env}`)

  return createClient(url, key, { auth: { persistSession: false } })
}
