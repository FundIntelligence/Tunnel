'use client'

import { useRef } from 'react'
import posthog from 'posthog-js'

const projectToken = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN
const host = process.env.NEXT_PUBLIC_POSTHOG_HOST

function configurePostHog() {
  if (posthog.__loaded) return

  if (!projectToken) {
    if (process.env.NODE_ENV !== 'production') {
      throw new Error('NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN is configured')
    }
    return
  }

  if (!host) {
    if (process.env.NODE_ENV !== 'production') {
      throw new Error('NEXT_PUBLIC_POSTHOG_HOST variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once NEXT_PUBLIC_POSTHOG_HOST is configured')
    }
    return
  }

  posthog.init(projectToken, {
    api_host: host,
    defaults: '2026-05-30',
    capture_exceptions: true,
  })
}

export function PostHogProvider({ children }: { children: React.ReactNode }) {
  const configured = useRef(false)
  if (!configured.current) {
    configurePostHog()
    configured.current = true
  }

  return <>{children}</>
}
