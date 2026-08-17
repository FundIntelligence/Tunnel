'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { SignOutButton } from '@/components/SignOutButton'
import { getSupabaseBrowser } from '@/lib/supabase-browser'
import { isOntologyQaAllowed } from '@/lib/ontology-qa-access'

const navItems = [
  { href: '/parser-requests', label: 'Parser Requests' },
  { href: '/musa-sessions', label: 'Musa Sessions' },
  { href: '/deals', label: 'Deal Pipeline' },
  { href: '/api-keys', label: 'API Keys' },
  { href: '/sandbox-keys', label: 'Sandbox Keys' },
]

export function Sidebar() {
  const [showOntologyQa, setShowOntologyQa] = useState(false)

  useEffect(() => {
    getSupabaseBrowser().auth.getUser().then(({ data: { user } }) => {
      setShowOntologyQa(isOntologyQaAllowed(user?.email))
    })
  }, [])

  return (
    <aside style={{
      width: 220,
      minHeight: '100vh',
      background: 'var(--navy)',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
      padding: '0',
    }}>
      <div style={{
        padding: '24px 20px 20px',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontWeight: 500,
          fontSize: 13,
          letterSpacing: '0.08em',
          color: 'var(--teal)',
        }}>
          PARITY
        </span>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontWeight: 400,
          fontSize: 13,
          letterSpacing: '0.08em',
          color: 'rgba(255,255,255,0.5)',
        }}>
          {' '}ADMIN
        </span>
      </div>
      <nav style={{ padding: '12px 0', flex: 1 }}>
        {navItems.map((item) => (
          <Link key={item.href} href={item.href} className="nav-link">
            {item.label}
          </Link>
        ))}
        {showOntologyQa && (
          <Link href="/ontology-qa" className="nav-link">
            Ontology QA
          </Link>
        )}
      </nav>
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '8px 0' }}>
        <SignOutButton />
      </div>
    </aside>
  )
}
