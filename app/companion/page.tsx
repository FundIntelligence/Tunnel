'use client';

import { motion } from 'framer-motion';
import AppLayout from '@/components/Layout/AppLayout';
import FeatureCard from '@/components/FeatureCard';
import { Bot } from 'lucide-react';

export default function CompanionPage() {
  return (
    <AppLayout>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="max-w-2xl mx-auto"
      >
        <h1 className="text-3xl font-bold text-white mb-8">Companion</h1>
        
        <FeatureCard
          icon={Bot}
          title="Your AI Investment Companion"
          description="Automates portfolio monitoring, routine summaries, risk flagging, and due diligence search."
          comingSoon
        />
      </motion.div>
    </AppLayout>
  );
}

