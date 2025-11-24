'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import AppLayout from '@/components/Layout/AppLayout';
import FeatureCard from '@/components/FeatureCard';
import TemplateSelector from '@/components/TemplateSelector';
import { FileText, Clock, Archive, Users } from 'lucide-react';
import { ReportTemplate } from '@/lib/reportTemplates';

export default function ReportsPage() {
  const [showTemplateSelector, setShowTemplateSelector] = useState(false);

  const handleGenerateReport = () => {
    setShowTemplateSelector(true);
  };

  const handleTemplateSelect = (template: ReportTemplate) => {
    console.log('Selected template:', template);
    // TODO: Implement report generation logic
    setShowTemplateSelector(false);
    // Show success message or navigate to report generation page
  };

  const handleCloseSelector = () => {
    setShowTemplateSelector(false);
  };

  return (
    <AppLayout>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <h1 className="text-3xl font-bold text-white mb-8">Reports</h1>
        
        {/* Historic Reports Section */}
        <div className="mb-8">
          <h2 className="text-xl font-semibold text-gray-200 mb-4">Historic Reports</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* Generate Report */}
            <FeatureCard
              icon={FileText}
              title="Generate Report"
              description="Create custom reports from your financial data with automated analysis and insights."
            >
              <button
                onClick={handleGenerateReport}
                className="mt-4 w-full px-4 py-2 bg-gradient-to-r from-cyan-400 to-green-400 text-[#0D0F12] font-semibold rounded-lg hover:opacity-90 transition-opacity"
              >
                Generate Report
              </button>
            </FeatureCard>

            {/* Active Reports */}
            <FeatureCard
              icon={Clock}
              title="Active Reports"
              description="View and manage currently running report generation tasks."
              comingSoon
            />

            {/* Team Templates */}
            <FeatureCard
              icon={Users}
              title="Team Templates"
              description="Share and reuse report templates across your team."
              comingSoon
            />
          </div>
        </div>

        {/* Report Library Section */}
        <div>
          <h2 className="text-xl font-semibold text-gray-200 mb-4">Report Library</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <FeatureCard
              icon={Archive}
              title="Historic Reports"
              description="Access previously generated reports and analysis history."
              comingSoon
            />
          </div>
        </div>
      </motion.div>

      {/* Template Selector Modal */}
      {showTemplateSelector && (
        <TemplateSelector
          onSelect={handleTemplateSelect}
          onClose={handleCloseSelector}
        />
      )}
    </AppLayout>
  );
}

