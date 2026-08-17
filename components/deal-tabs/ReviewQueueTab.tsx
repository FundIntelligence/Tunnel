'use client';

import ReviewQueue from '@/components/ReviewQueue';
import type { Deal } from '@/lib/v1-api';

export interface ReviewQueueTabProps {
  deal: Deal | null;
  analystInitials: string;
  onQueueUpdate: (remaining: number) => void;
}

export default function ReviewQueueTab({ deal, analystInitials, onQueueUpdate }: ReviewQueueTabProps) {
  if (!deal) return null;
  return (
    <div style={{ maxWidth: 820 }}>
      <ReviewQueue
        dealId={deal.id}
        analystInitials={analystInitials}
        onQueueUpdate={onQueueUpdate}
      />
    </div>
  );
}
