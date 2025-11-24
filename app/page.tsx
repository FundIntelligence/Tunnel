'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to connect-data page
    router.push('/connect-data');
  }, [router]);

  return (
    <div className="min-h-screen bg-[#0D0F12] flex items-center justify-center">
      <div className="text-white">Redirecting...</div>
    </div>
  );
}
