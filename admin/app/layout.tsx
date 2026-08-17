import type { Metadata } from 'next'
import './globals.css'
import './layout.css'
import { Sidebar } from '@/components/Sidebar'

export const metadata: Metadata = {
  title: 'Parity Admin',
  description: 'Parity SME internal admin dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ height: '100%' }}>
      <body style={{ height: '100%', display: 'flex' }}>
        <Sidebar />
        <main style={{
          flex: 1,
          minHeight: '100vh',
          background: 'var(--bg)',
          overflow: 'auto',
        }}>
          {children}
        </main>
      </body>
    </html>
  )
}
