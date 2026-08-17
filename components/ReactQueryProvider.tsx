'use client'

import { useState, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { persistQueryClient, experimental_createQueryPersister } from '@tanstack/react-query-persist-client'

export default function ReactQueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 2 * 60 * 1000, // 2 minutes
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  }))

  // Persist the query cache to localStorage so data survives full page reloads
  useEffect(() => {
    if (typeof window === 'undefined') return
    const store = window.localStorage
    // Build a persister using the experimental helper which provides query-level persistence
    const queryPersister = experimental_createQueryPersister({ storage: store })

    // Wrap into a client-level persister expected by persistQueryClient
    const persister = {
      persistClient: async (payload: any) => {
        try {
          // use localStorage directly to store the dehydrated client
          store.setItem('react-query-client', JSON.stringify(payload));
        } catch (e) { /* ignore */ }
      },
      restoreClient: async () => {
        try {
          const raw = store.getItem('react-query-client')
          if (!raw) return null
          return JSON.parse(raw)
        } catch (e) { return null }
      },
      removeClient: async () => {
        try { store.removeItem('react-query-client') } catch (e) { /* ignore */ }
      },
      // expose query-level helpers for restore/save if needed
      restoreQueries: queryPersister.restoreQueries,
      persistQuery: queryPersister.persistQuery,
      removeQueries: queryPersister.removeQueries,
    }

    const [unsubscribe] = persistQueryClient({ queryClient, persister })
    return () => { try { unsubscribe?.(); } catch {} }
  }, [queryClient])

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
