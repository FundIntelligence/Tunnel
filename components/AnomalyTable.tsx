'use client';

import { useState, useEffect } from 'react';
import { AlertTriangle, AlertCircle, Info, ChevronDown, ChevronUp } from 'lucide-react';

interface Anomaly {
  id: string;
  document_id: string;
  row_index: number;
  anomaly_type: string;
  severity: 'high' | 'medium' | 'low';
  description: string;
  detected_at?: string;
}

interface AnomalyTableProps {
  documentId: string;
  onRowClick?: (rowIndex: number) => void;
}

export default function AnomalyTable({ documentId, onRowClick }: AnomalyTableProps) {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [filterType, setFilterType] = useState<string>('all');
  const [sortColumn, setSortColumn] = useState<string>('severity');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    loadAnomalies();
  }, [documentId]);

  const loadAnomalies = async () => {
    try {
      setLoading(true);
      setError(null);
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/api/anomalies?doc_id=${documentId}`);
      if (!response.ok) throw new Error('Failed to load anomalies');
      const data = await response.json();
      setAnomalies(data.anomalies || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load anomalies');
    } finally {
      setLoading(false);
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'high':
        return <AlertCircle className="h-4 w-4 text-red-600" />;
      case 'medium':
        return <AlertTriangle className="h-4 w-4 text-yellow-600" />;
      case 'low':
        return <Info className="h-4 w-4 text-blue-600" />;
      default:
        return null;
    }
  };

  const getSeverityBadge = (severity: string) => {
    const colors = {
      high: 'bg-red-100 text-red-800 border-red-300',
      medium: 'bg-yellow-100 text-yellow-800 border-yellow-300',
      low: 'bg-blue-100 text-blue-800 border-blue-300'
    };
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium border ${colors[severity as keyof typeof colors]}`}>
        {severity.toUpperCase()}
      </span>
    );
  };

  const getAnomalyTypeName = (type: string) => {
    const names: Record<string, string> = {
      revenue_anomaly: 'Revenue Anomaly',
      expense_integrity: 'Expense Integrity',
      cashflow_consistency: 'Cash Flow Consistency',
      payroll_pattern: 'Payroll Pattern',
      declared_mismatch: 'Declared Mismatch'
    };
    return names[type] || type.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const getSuggestedAction = (type: string, severity: string) => {
    const actions: Record<string, string> = {
      revenue_anomaly: severity === 'high' 
        ? 'Verify data entry and check for refunds or reversals'
        : 'Review trend and confirm with business owner',
      expense_integrity: severity === 'high'
        ? 'Investigate potential duplicate charges or fraud'
        : 'Add missing descriptions or verify amounts',
      cashflow_consistency: 'Reconcile balance jumps with transaction log',
      payroll_pattern: severity === 'high'
        ? 'Verify employee count and payment authorization'
        : 'Check for overtime, bonuses, or seasonal factors',
      declared_mismatch: 'Reconcile declared totals with detailed breakdown'
    };
    return actions[type] || 'Review data for accuracy';
  };

  const filteredAnomalies = anomalies.filter(a => {
    if (filterSeverity !== 'all' && a.severity !== filterSeverity) return false;
    if (filterType !== 'all' && a.anomaly_type !== filterType) return false;
    return true;
  });

  const sortedAnomalies = [...filteredAnomalies].sort((a, b) => {
    let aVal: any, bVal: any;
    
    switch (sortColumn) {
      case 'severity':
        const severityOrder = { high: 3, medium: 2, low: 1 };
        aVal = severityOrder[a.severity as keyof typeof severityOrder] || 0;
        bVal = severityOrder[b.severity as keyof typeof severityOrder] || 0;
        break;
      case 'type':
        aVal = a.anomaly_type;
        bVal = b.anomaly_type;
        break;
      case 'row':
        aVal = a.row_index;
        bVal = b.row_index;
        break;
      default:
        aVal = a.description;
        bVal = b.description;
    }
    
    if (sortDirection === 'asc') {
      return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
    } else {
      return aVal < bVal ? 1 : aVal > bVal ? -1 : 0;
    }
  });

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection('desc');
    }
  };

  const uniqueTypes = Array.from(new Set(anomalies.map(a => a.anomaly_type)));

  if (loading) {
    return (
      <div className="p-4 bg-white rounded-lg shadow">
        <div className="animate-pulse">Loading anomalies...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-red-800">Error: {error}</p>
      </div>
    );
  }

  if (anomalies.length === 0) {
    return (
      <div className="p-4 bg-white rounded-lg shadow">
        <h3 className="font-semibold mb-2">Anomalies</h3>
        <p className="text-gray-500">No anomalies detected. Data appears clean.</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-white rounded-lg shadow">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Detected Anomalies ({anomalies.length})</h3>
        <button
          onClick={loadAnomalies}
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Severity</label>
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value as any)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="all">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="all">All Types</option>
            {uniqueTypes.map(type => (
              <option key={type} value={type}>{getAnomalyTypeName(type)}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b">
              <th
                className="text-left p-2 cursor-pointer hover:bg-gray-50"
                onClick={() => handleSort('severity')}
              >
                <div className="flex items-center gap-1">
                  Severity
                  {sortColumn === 'severity' && (
                    sortDirection === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                  )}
                </div>
              </th>
              <th
                className="text-left p-2 cursor-pointer hover:bg-gray-50"
                onClick={() => handleSort('type')}
              >
                <div className="flex items-center gap-1">
                  Type
                  {sortColumn === 'type' && (
                    sortDirection === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                  )}
                </div>
              </th>
              <th className="text-left p-2">Description</th>
              <th className="text-left p-2">Suggested Action</th>
              <th
                className="text-left p-2 cursor-pointer hover:bg-gray-50"
                onClick={() => handleSort('row')}
              >
                <div className="flex items-center gap-1">
                  Row
                  {sortColumn === 'row' && (
                    sortDirection === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                  )}
                </div>
              </th>
              <th className="text-left p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedAnomalies.map((anomaly) => (
              <tr key={anomaly.id} className="border-b hover:bg-gray-50">
                <td className="p-2">
                  <div className="flex items-center gap-2">
                    {getSeverityIcon(anomaly.severity)}
                    {getSeverityBadge(anomaly.severity)}
                  </div>
                </td>
                <td className="p-2">{getAnomalyTypeName(anomaly.anomaly_type)}</td>
                <td className="p-2">{anomaly.description}</td>
                <td className="p-2 text-gray-600 text-xs">{getSuggestedAction(anomaly.anomaly_type, anomaly.severity)}</td>
                <td className="p-2">{anomaly.row_index >= 0 ? `Row ${anomaly.row_index + 1}` : 'N/A'}</td>
                <td className="p-2">
                  {anomaly.row_index >= 0 && onRowClick && (
                    <button
                      onClick={() => onRowClick(anomaly.row_index)}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      View Row
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sortedAnomalies.length === 0 && (
        <p className="text-center text-gray-500 py-4">No anomalies match the selected filters.</p>
      )}
    </div>
  );
}


