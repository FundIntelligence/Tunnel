import { ExtractedRow } from './supabase';

export interface Anomaly {
  id: string;
  severity: 'high' | 'medium' | 'low';
  anomaly_type: string;
  description: string;
  row_index: number;
}

export interface Insights {
  revenueGrowth: number;      // MoM % change
  cashFlowStability: number;  // Volatility score 0-100
  expenseRatio: number;       // Expenses / Revenue ratio
  thesisFit: number;         // Placeholder score 0-100
  averageRevenue: number;
  totalExpenses: number;
  anomalyDensity: number;    // Anomalies per 100 rows
}

/**
 * Compute financial insights from extracted rows and anomalies
 */
export function computeInsights(
  rows: ExtractedRow[],
  anomalies: Anomaly[]
): Insights {
  if (!rows || rows.length === 0) {
    return {
      revenueGrowth: 0,
      cashFlowStability: 0,
      expenseRatio: 0,
      thesisFit: 0,
      averageRevenue: 0,
      totalExpenses: 0,
      anomalyDensity: 0
    };
  }

  // Calculate revenue growth (MoM)
  const revenueGrowth = calculateRevenueGrowth(rows);
  
  // Calculate cash flow stability (inverse of volatility)
  const cashFlowStability = calculateStability(rows);
  
  // Calculate expense ratio
  const expenseRatio = calculateExpenseRatio(rows);
  
  // Calculate thesis fit (placeholder - can be enhanced later)
  const thesisFit = calculateThesisFit(rows, anomalies);
  
  // Additional metrics
  const averageRevenue = calculateAverageRevenue(rows);
  const totalExpenses = calculateTotalExpenses(rows);
  const anomalyDensity = rows.length > 0 
    ? (anomalies.length / rows.length) * 100 
    : 0;
  
  return {
    revenueGrowth,
    cashFlowStability,
    expenseRatio,
    thesisFit,
    averageRevenue,
    totalExpenses,
    anomalyDensity
  };
}

/**
 * Calculate month-over-month revenue growth
 */
function calculateRevenueGrowth(rows: ExtractedRow[]): number {
  const revenueField = findRevenueField(rows);
  if (!revenueField) return 0;

  const revenues = extractNumericValues(rows, revenueField);
  if (revenues.length < 2) return 0;

  const firstHalf = revenues.slice(0, Math.floor(revenues.length / 2));
  const secondHalf = revenues.slice(Math.floor(revenues.length / 2));

  const firstAvg = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
  const secondAvg = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;

  if (firstAvg === 0) return 0;
  
  return ((secondAvg - firstAvg) / firstAvg) * 100;
}

/**
 * Calculate cash flow stability score (0-100)
 * Higher score = more stable
 */
function calculateStability(rows: ExtractedRow[]): number {
  const cashFlowFields = findCashFlowFields(rows);
  if (cashFlowFields.length === 0) return 50; // Neutral if no data

  const allValues: number[] = [];
  cashFlowFields.forEach(field => {
    allValues.push(...extractNumericValues(rows, field));
  });

  if (allValues.length < 2) return 50;

  // Calculate coefficient of variation
  const mean = allValues.reduce((a, b) => a + b, 0) / allValues.length;
  const variance = allValues.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / allValues.length;
  const stdDev = Math.sqrt(variance);
  const coefficientOfVariation = mean !== 0 ? stdDev / Math.abs(mean) : 0;

  // Convert to stability score (lower CV = higher stability)
  const stabilityScore = Math.max(0, Math.min(100, 100 - (coefficientOfVariation * 100)));
  
  return Math.round(stabilityScore);
}

/**
 * Calculate expense to revenue ratio
 */
function calculateExpenseRatio(rows: ExtractedRow[]): number {
  const revenueField = findRevenueField(rows);
  const expenseField = findExpenseField(rows);

  if (!revenueField || !expenseField) return 0;

  const revenues = extractNumericValues(rows, revenueField);
  const expenses = extractNumericValues(rows, expenseField);

  const totalRevenue = revenues.reduce((a, b) => a + b, 0);
  const totalExpenses = expenses.reduce((a, b) => a + b, 0);

  if (totalRevenue === 0) return 0;

  return (totalExpenses / totalRevenue) * 100;
}

/**
 * Calculate average revenue
 */
function calculateAverageRevenue(rows: ExtractedRow[]): number {
  const revenueField = findRevenueField(rows);
  if (!revenueField) return 0;

  const revenues = extractNumericValues(rows, revenueField);
  if (revenues.length === 0) return 0;

  const sum = revenues.reduce((a, b) => a + b, 0);
  return sum / revenues.length;
}

/**
 * Calculate total expenses
 */
function calculateTotalExpenses(rows: ExtractedRow[]): number {
  const expenseField = findExpenseField(rows);
  if (!expenseField) return 0;

  const expenses = extractNumericValues(rows, expenseField);
  return expenses.reduce((a, b) => a + b, 0);
}

/**
 * Calculate thesis fit score (placeholder algorithm)
 */
function calculateThesisFit(rows: ExtractedRow[], anomalies: Anomaly[]): number {
  // Placeholder algorithm:
  // Start with base score, reduce based on high-severity anomalies
  let score = 75; // Baseline optimistic score

  // Reduce score based on high-severity anomalies
  const highSeverityCount = anomalies.filter(a => a.severity === 'high').length;
  const mediumSeverityCount = anomalies.filter(a => a.severity === 'medium').length;

  score -= highSeverityCount * 15; // High severity hurts more
  score -= mediumSeverityCount * 5; // Medium severity hurts less

  // Boost score if data looks clean
  if (anomalies.length === 0) {
    score = 95;
  }

  // Ensure score stays within bounds
  return Math.max(0, Math.min(100, Math.round(score)));
}

/**
 * Helper functions to find fields by keywords
 */
function findRevenueField(rows: ExtractedRow[]): string | null {
  const keywords = ['revenue', 'income', 'sales', 'earning', 'turnover'];
  return findFieldByKeywords(rows, keywords);
}

function findExpenseField(rows: ExtractedRow[]): string | null {
  const keywords = ['expense', 'cost', 'payment', 'outgoing', 'spend'];
  return findFieldByKeywords(rows, keywords);
}

function findCashFlowFields(rows: ExtractedRow[]): string[] {
  const keywords = ['cash', 'flow', 'balance', 'capital'];
  const fields: string[] = [];
  
  if (rows.length === 0) return fields;

  const firstRow = rows[0];
  const rawJson = firstRow.raw_json || {};

  Object.keys(rawJson).forEach(key => {
    const keyLower = key.toLowerCase();
    if (keywords.some(kw => keyLower.includes(kw))) {
      if (!fields.includes(key)) {
        fields.push(key);
      }
    }
  });

  return fields;
}

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
 * Extract numeric values from a specific field across rows
 */
function extractNumericValues(rows: ExtractedRow[], field: string): number[] {
  const values: number[] = [];

  for (const row of rows) {
    const rawJson = row.raw_json || {};
    const value = rawJson[field];

    if (value === null || value === undefined || value === '') {
      continue;
    }

    const numValue = toNumber(value);
    if (numValue !== null && !isNaN(numValue)) {
      values.push(numValue);
    }
  }

  return values;
}

/**
 * Convert a value to a number, handling strings with commas, dollar signs, etc.
 */
function toNumber(value: any): number | null {
  if (typeof value === 'number') {
    return value;
  }

  if (typeof value === 'string') {
    // Remove common formatting
    const cleaned = value
      .replace(/[$,]/g, '')
      .replace(/\s+/g, '')
      .trim();
    
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? null : parsed;
  }

  return null;
}

