'use client';

import { useState, useEffect } from 'react';
import { 
  TrendingUp, Activity, Wallet, Target, FileDown 
} from 'lucide-react';
import { 
  LineChart, Line, BarChart, Bar, XAxis, YAxis, 
  CartesianGrid, Tooltip, ResponsiveContainer, Legend 
} from 'recharts';
import { Document, ExtractedRow } from '@/lib/supabase';
import { computeInsights, Anomaly, Insights } from '@/lib/evaluate';
import { prepareRevenueChartData, prepareExpenseBreakdown } from '@/lib/chart-utils';

interface EvaluateViewProps {
  document: Document;
  rows: ExtractedRow[];
  onGenerateReport: () => void;
}

interface InsightCardProps {
  title: string;
  value: number;
  icon: React.ReactNode;
  unit?: string;
  trend?: 'positive' | 'negative' | 'neutral';
}

function InsightCard({ title, value, icon, unit = '', trend = 'neutral' }: InsightCardProps) {
  const formattedValue = typeof value === 'number' 
    ? value.toLocaleString('en-US', { 
        maximumFractionDigits: value < 100 ? 1 : 0 
      })
    : '0';
  
  const iconColor = trend === 'positive' ? 'text-green-400' 
    : trend === 'negative' ? 'text-red-400' 
    : 'text-cyan-400';
  
  const valueColor = trend === 'positive' ? 'text-green-400' 
    : trend === 'negative' ? 'text-red-400' 
    : 'text-gray-100';

  return (
    <div className="bg-[#1B1E23] border border-gray-700 rounded-xl shadow-md hover:shadow-lg transition-shadow p-6">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-400">{title}</span>
        <div className={iconColor}>{icon}</div>
      </div>
      <div className={`text-3xl font-bold ${valueColor}`}>
        {formattedValue}{unit}
        {trend === 'positive' && ' ↗️'}
        {trend === 'negative' && ' ↘️'}
      </div>
    </div>
  );
}

export default function EvaluateView({ document, rows, onGenerateReport }: EvaluateViewProps) {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAnomaliesAndComputeInsights();
  }, [document.id, rows]);

  const loadAnomaliesAndComputeInsights = async () => {
    try {
      setLoading(true);
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/api/anomalies?doc_id=${document.id}`);
      
      if (!response.ok) throw new Error('Failed to load anomalies');
      
      const data = await response.json();
      const anomalyList = data.anomalies || [];
      setAnomalies(anomalyList);
      
      // Compute insights
      const computedInsights = computeInsights(rows, anomalyList);
      setInsights(computedInsights);
    } catch (err: any) {
      console.error('Error loading evaluate data:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading insights...</div>
      </div>
    );
  }

  if (!insights) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Unable to compute insights</p>
      </div>
    );
  }

  // Prepare chart data
  const revenueData = prepareRevenueChartData(rows, anomalies);
  const expenseBreakdown = prepareExpenseBreakdown(rows);

  // Determine trends
  const revenueTrend = insights.revenueGrowth > 0 ? 'positive' : 'negative';
  const stabilityTrend = insights.cashFlowStability > 60 ? 'positive' : 'neutral';
  const expenseTrend = insights.expenseRatio < 70 ? 'positive' : 'negative';
  const thesisTrend = insights.thesisFit > 70 ? 'positive' : 'negative';

  return (
    <div className="p-6 space-y-6">
      {/* Hero Section */}
      <div className="text-center">
        <h1 className="text-3xl font-bold mb-2 text-gray-200">Evaluate</h1>
        <p className="text-gray-400 italic">
          "The devil is in the details — FundIQ finds the devil."
        </p>
      </div>

      {/* Insight Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <InsightCard
          title="Revenue Growth"
          value={insights.revenueGrowth}
          icon={<TrendingUp className="h-6 w-6" />}
          unit="%"
          trend={revenueTrend}
        />
        <InsightCard
          title="Cash Flow Stability"
          value={insights.cashFlowStability}
          icon={<Activity className="h-6 w-6" />}
          unit="/100"
          trend={stabilityTrend}
        />
        <InsightCard
          title="Expense Efficiency"
          value={insights.expenseRatio}
          icon={<Wallet className="h-6 w-6" />}
          unit="%"
          trend={expenseTrend}
        />
        <InsightCard
          title="Thesis Fit"
          value={insights.thesisFit}
          icon={<Target className="h-6 w-6" />}
          unit="/100"
          trend={thesisTrend}
        />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Revenue Trend Chart */}
        <div className="bg-[#1B1E23] border border-gray-700 rounded-xl shadow-md p-6">
          <h3 className="text-lg font-semibold mb-4 text-gray-200">Revenue Trend</h3>
          {revenueData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={revenueData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis 
                  dataKey="period" 
                  stroke="#6b7280"
                  style={{ fontSize: '12px' }}
                />
                <YAxis 
                  stroke="#6b7280"
                  style={{ fontSize: '12px' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'white',
                    border: '1px solid #e5e7eb',
                    borderRadius: '8px'
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="revenue"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ fill: '#3b82f6', r: 4 }}
                  name="Revenue"
                />
                {/* Anomaly indicators */}
                {revenueData.map((point, index) => (
                  point.hasAnomaly && (
                    <circle
                      key={`anomaly-${index}`}
                      cx={index * (300 / revenueData.length)}
                      cy={30}
                      r={4}
                      fill="#ef4444"
                    />
                  )
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[300px] text-gray-500">
              No revenue data available
            </div>
          )}
        </div>

        {/* Expenses vs Income Chart */}
        <div className="bg-[#1B1E23] border border-gray-700 rounded-xl shadow-md p-6">
          <h3 className="text-lg font-semibold mb-4 text-gray-200">Expenses vs Income</h3>
          {expenseBreakdown.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={expenseBreakdown}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="category"
                  stroke="#6b7280"
                  style={{ fontSize: '12px' }}
                  angle={-45}
                  textAnchor="end"
                  height={80}
                />
                <YAxis
                  stroke="#6b7280"
                  style={{ fontSize: '12px' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'white',
                    border: '1px solid #e5e7eb',
                    borderRadius: '8px'
                  }}
                />
                <Legend />
                <Bar
                  dataKey="expenses"
                  fill="#ef4444"
                  name="Expenses"
                  radius={[8, 8, 0, 0]}
                />
                <Bar
                  dataKey="income"
                  fill="#22c55e"
                  name="Income"
                  radius={[8, 8, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[300px] text-gray-500">
              No expense data available
            </div>
          )}
        </div>
      </div>

      {/* Export Button */}
      <div className="flex justify-center pt-4">
        <button
          onClick={onGenerateReport}
          className="px-6 py-3 bg-gradient-to-r from-cyan-400 to-green-400 text-[#0D0F12] font-semibold rounded-lg hover:opacity-90 transition-opacity flex items-center space-x-2 shadow-md hover:shadow-lg"
        >
          <FileDown className="h-5 w-5" />
          <span>📄 Generate IC Report</span>
        </button>
      </div>

      {/* Additional Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#1B1E23] border border-gray-700 rounded-xl p-4">
          <div className="text-sm text-gray-400 font-medium mb-1">Average Revenue</div>
          <div className="text-2xl font-bold text-gray-100">
            ${insights.averageRevenue.toLocaleString()}
          </div>
        </div>
        <div className="bg-[#1B1E23] border border-gray-700 rounded-xl p-4">
          <div className="text-sm text-gray-400 font-medium mb-1">Total Expenses</div>
          <div className="text-2xl font-bold text-gray-100">
            ${insights.totalExpenses.toLocaleString()}
          </div>
        </div>
        <div className="bg-[#1B1E23] border border-gray-700 rounded-xl p-4">
          <div className="text-sm text-gray-400 font-medium mb-1">Anomaly Density</div>
          <div className="text-2xl font-bold text-gray-100">
            {insights.anomalyDensity.toFixed(1)}%
          </div>
        </div>
      </div>
    </div>
  );
}

