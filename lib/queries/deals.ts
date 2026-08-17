'use client';

import { useQuery } from '@tanstack/react-query';
import { listDeals, getDeal, listDocuments } from '@/lib/v1-api';

/**
 * Shared query keys so /deals and /v1/deal read from the same cache entries —
 * navigating between them within staleTime should not re-fetch.
 */
export const dealsListKey = (userId: string | undefined) => ['deals', userId] as const;
export const dealDetailKey = (dealId: string | undefined) => ['deal', dealId] as const;
export const dealDocumentsKey = (dealId: string | undefined) => ['documents', dealId] as const;

export function useDealsListQuery(userId: string | undefined) {
  return useQuery({
    queryKey: dealsListKey(userId),
    queryFn: () => listDeals(userId as string),
    enabled: !!userId,
  });
}

export function useDealDetailQuery(dealId: string | undefined) {
  return useQuery({
    queryKey: dealDetailKey(dealId),
    queryFn: () => getDeal(dealId as string),
    enabled: !!dealId,
  });
}

export function useDealDocumentsQuery(dealId: string | undefined) {
  return useQuery({
    queryKey: dealDocumentsKey(dealId),
    queryFn: () => listDocuments(dealId as string),
    enabled: !!dealId,
  });
}
