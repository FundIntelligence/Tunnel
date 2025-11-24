'use client';

import { motion } from 'framer-motion';
import AppLayout from '@/components/Layout/AppLayout';
import FeatureCard from '@/components/FeatureCard';
import { FileCheck, Share2, Shield } from 'lucide-react';

export default function RulesPage() {
  return (
    <AppLayout>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <h1 className="text-3xl font-bold text-white mb-8">Rules & Settings</h1>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Thesis Definition */}
          <FeatureCard
            icon={FileCheck}
            title="Thesis Definition"
            description="Define and manage investment thesis rules and criteria for automated analysis."
            comingSoon
          />

          {/* File Sharing Rights */}
          <FeatureCard
            icon={Share2}
            title="File Sharing Rights"
            description="Configure permissions and access controls for shared documents and data."
            comingSoon
          />

          {/* Companion Access Control */}
          <FeatureCard
            icon={Shield}
            title="Companion Access Control"
            description="Manage AI companion permissions and scope of analysis capabilities."
            comingSoon
          />
        </div>
      </motion.div>
    </AppLayout>
  );
}

