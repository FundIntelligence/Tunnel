'use client';

import { motion } from 'framer-motion';
import { X, TrendingUp, PieChart, LayoutDashboard, Leaf, Shield } from 'lucide-react';
import { ReportTemplates, ReportTemplate } from '@/lib/reportTemplates';

interface TemplateSelectorProps {
  onSelect: (template: ReportTemplate) => void;
  onClose: () => void;
}

const templateIcons = {
  performance: TrendingUp,
  annualFund: PieChart,
  dashboard: LayoutDashboard,
  esgImpact: Leaf,
  dueDiligence: Shield,
};

export default function TemplateSelector({ onSelect, onClose }: TemplateSelectorProps) {
  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
        className="bg-[#1B1E23] border border-gray-700 rounded-2xl p-6 max-w-4xl w-full max-h-[90vh] overflow-y-auto"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-white">Select Report Template</h2>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-[#23272E] rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Template Grid */}
        <motion.div
          initial="hidden"
          animate="visible"
          variants={{
            visible: {
              transition: {
                staggerChildren: 0.1,
              },
            },
          }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {ReportTemplates.map((template) => {
            const Icon = templateIcons[template.id as keyof typeof templateIcons];

            return (
              <motion.div
                key={template.id}
                variants={{
                  hidden: { opacity: 0, y: 20 },
                  visible: { opacity: 1, y: 0 },
                }}
                whileHover={{
                  scale: 1.05,
                  boxShadow: "0 0 15px rgba(34,211,238,0.3)",
                }}
                whileTap={{ scale: 0.98 }}
                onClick={() => onSelect(template)}
                className="bg-[#23272E] border border-gray-700 rounded-xl p-6 cursor-pointer transition-colors hover:bg-[#2A2F36]"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="p-2 bg-cyan-400/10 rounded-lg">
                    {Icon && <Icon className="h-6 w-6 text-cyan-400" />}
                  </div>
                  <h3 className="text-lg font-semibold text-gray-200">{template.name}</h3>
                </div>
                <p className="text-sm text-gray-400">{template.description}</p>
              </motion.div>
            );
          })}
        </motion.div>
      </motion.div>
    </div>
  );
}

