import { ExtractedRow } from './supabase';
import { Anomaly } from './evaluate';

export interface ChartDataPoint {
  period: string;
  revenue: number;
  expenses: number;
  hasAnomaly: boolean;
}

export interface ExpenseBreakdown {
  category: string;
  expenses: number;
  income: number;
  percentage: number;
}

/**
 * Prepare revenue trend data for line chart
 */
export function prepareRevenueChartData(
  rows: ExtractedRow[],
  anomalies: Anomaly[] = []
): ChartDataPoint[] {
  if (!rows || rows.length === 0) {
    return [];
  }

  const dataPoints: ChartDataPoint[] = [];
  
  // Get field names
  const revenueField = findFieldByKeywords(rows, ['revenue', 'income', 'sales']);
  const expenseField = findFieldByKeywords(rows, ['expense', 'cost', 'payment']);
  
  if (!revenueField) {
    return [];
  }

  // Create a set of row indices with anomalies for quick lookup
  const anomalyRowIndices = new Set(anomalies.map(a => a.row_index));

  // Process rows
  rows.forEach((row, index) => {
    const rawJson = row.raw_json || {};
    
    const revenue = toNumber(rawJson[revenueField]) || 0;
    const expenses = expenseField ? (toNumber(rawJson[expenseField]) || 0) : 0;
    
    // Create period label
    const period = `Period ${index + 1}`;
    
    // Check if this row has an anomaly
    const hasAnomaly = anomalyRowIndices.has(index);
    
    dataPoints.push({
      period,
      revenue,
      expenses,
      hasAnomaly
    });
  });

  // If we have too many points, sample them
  if (dataPoints.length > 20) {
    return sampleDataPoints(dataPoints, 20);
  }

  return dataPoints;
}

/**
 * Prepare expense breakdown data for bar chart
 */
export function prepareExpenseBreakdown(rows: ExtractedRow[]): ExpenseBreakdown[] {
  if (!rows || rows.length === 0) {
    return [];
  }

  const categoryMap: Map<string, { expenses: number; income: number }> = new Map();

  const expenseField = findFieldByKeywords(rows, ['expense', 'cost', 'payment']);
  const revenueField = findFieldByKeywords(rows, ['revenue', 'income', 'sales']);
  const categoryField = findFieldByKeywords(rows, ['category', 'type', 'class']);

  rows.forEach(row => {
    const rawJson = row.raw_json || {};
    
    const category = categoryField 
      ? (rawJson[categoryField]?.toString() || 'Other')
      : 'Uncategorized';
    
    const expenses = expenseField ? (toNumber(rawJson[expenseField]) || 0) : 0;
    const income = revenueField ? (toNumber(rawJson[revenueField]) || 0) : 0;

    if (!categoryMap.has(category)) {
      categoryMap.set(category, { expenses: 0, income: 0 });
    }

    const current = categoryMap.get(category)!;
    current.expenses += expenses;
    current.income += income;
  });

  // Convert to array
  const breakdown: ExpenseBreakdown[] = [];
  let totalExpenses = 0;
  let totalIncome = 0;

  categoryMap.forEach((values, category) => {
    totalExpenses += values.expenses;
    totalIncome += values.income;
  });

  categoryMap.forEach((values, category) => {
    const percentage = totalExpenses > 0 
      ? (values.expenses / totalExpenses) * 100 
      : 0;

    breakdown.push({
      category,
      expenses: values.expenses,
      income: values.income,
      percentage
    });
  });

  // Sort by expense amount (descending)
  breakdown.sort((a, b) => b.expenses - a.expenses);

  // Limit to top 5 categories
  return breakdown.slice(0, 5);
}

/**
 * Sample data points to reduce chart clutter
 */
function sampleDataPoints(
  dataPoints: ChartDataPoint[],
  maxPoints: number
): ChartDataPoint[] {
  if (dataPoints.length <= maxPoints) {
    return dataPoints;
  }

  const sampled: ChartDataPoint[] = [];
  const step = Math.floor(dataPoints.length / maxPoints);

  for (let i = 0; i < dataPoints.length; i += step) {
    sampled.push(dataPoints[i]);
    
    if (sampled.length >= maxPoints) {
      break;
    }
  }

  // Always include the last point
  if (sampled[sampled.length - 1] !== dataPoints[dataPoints.length - 1]) {
    sampled[sampled.length - 1] = dataPoints[dataPoints.length - 1];
  }

  return sampled;
}

/**
 * Helper function to find field by keywords
 */
function findFieldByKeywords(rows: ExtractedRow[], keywords: string[]): string | null {
  if (rows.length === 0) return null;

  const firstRow = rows[0];
  const rawJson = firstRow.raw_json || {};

  // Try exact match first
  for (const keyword of keywords) {
    for (const key of Object.keys(rawJson)) {
      if (key.toLowerCase() === keyword) {
        return key;
      }
    }
  }

  // Try partial match
  for (const keyword of keywords) {
    for (const key of Object.keys(rawJson)) {
      if (key.toLowerCase().includes(keyword)) {
        return key;
      }
    }
  }

  return null;
}

/**
 * Convert a value to a number
 */
function toNumber(value: any): number | null {
  if (typeof value === 'number') {
    return value;
  }

  if (typeof value === 'string') {
    const cleaned = value
      .replace(/[$,]/g, '')
      .replace(/\s+/g, '')
      .trim();
    
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? null : parsed;
  }

  return null;
}

