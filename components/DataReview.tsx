'use client';

import { useState, useEffect, useMemo } from 'react';
import { Download, X, Search, ArrowUpDown, ChevronLeft, ChevronRight, RefreshCw, AlertTriangle } from 'lucide-react';
import { getExtractedRows, Document, ExtractedRow } from '@/lib/supabase';
import AnomalyTable from './AnomalyTable';
import EvaluateView from './EvaluateView';

interface DataReviewProps {
  document: Document;
  onClose: () => void;
}

export default function DataReview({ document, onClose }: DataReviewProps) {
  const [rows, setRows] = useState<ExtractedRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [currentPage, setCurrentPage] = useState(1);
  const [viewMode, setViewMode] = useState<'table' | 'json' | 'anomalies' | 'evaluate'>('table');
  const [rerunLoading, setRerunLoading] = useState(false);
  const rowsPerPage = 50;

  useEffect(() => {
    loadRows();
  }, [document.id]);

  const loadRows = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getExtractedRows(document.id);
      setRows(data);
    } catch (err: any) {
      console.error('Error loading rows:', err);
      setError(err.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const rerunDetection = async () => {
    try {
      setRerunLoading(true);
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/api/anomalies/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_id: document.id })
      });
      
      if (!response.ok) throw new Error('Failed to rerun detection');
      
      // Refresh the page to show updated data
      window.location.reload();
    } catch (err: any) {
      console.error('Error rerunning detection:', err);
      setError(err.message || 'Failed to rerun detection');
    } finally {
      setRerunLoading(false);
    }
  };

  const generateReport = async () => {
    try {
      setRerunLoading(true);
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/api/report?doc_id=${document.id}`);
      
      if (!response.ok) throw new Error('Failed to generate report');
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `${document.file_name}_IC_Report.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error('Error generating report:', err);
      setError(err.message || 'Failed to generate report');
    } finally {
      setRerunLoading(false);
    }
  };

  // Get all unique columns from the data
  const columns = useMemo(() => {
    if (rows.length === 0) return [];
    const allKeys = new Set<string>();
    rows.forEach(row => {
      Object.keys(row.raw_json).forEach(key => allKeys.add(key));
    });
    return Array.from(allKeys);
  }, [rows]);

  // Filter and sort rows
  const processedRows = useMemo(() => {
    let filtered = rows;

    // Search filter
    if (searchTerm) {
      filtered = filtered.filter(row => {
        const searchLower = searchTerm.toLowerCase();
        return Object.values(row.raw_json).some(value => 
          String(value).toLowerCase().includes(searchLower)
        );
      });
    }

    // Sort
    if (sortColumn) {
      filtered = [...filtered].sort((a, b) => {
        const aVal = a.raw_json[sortColumn];
        const bVal = b.raw_json[sortColumn];
        
        if (aVal === bVal) return 0;
        if (aVal == null) return 1;
        if (bVal == null) return -1;
        
        const comparison = aVal < bVal ? -1 : 1;
        return sortDirection === 'asc' ? comparison : -comparison;
      });
    }

    return filtered;
  }, [rows, searchTerm, sortColumn, sortDirection]);

  // Pagination
  const totalPages = Math.ceil(processedRows.length / rowsPerPage);
  const paginatedRows = processedRows.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  );

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  const downloadCSV = () => {
    if (rows.length === 0) return;

    // Create CSV content
    const headers = columns.join(',');
    const csvRows = rows.map(row => 
      columns.map(col => {
        const value = row.raw_json[col];
        // Escape quotes and wrap in quotes if contains comma
        const stringValue = String(value ?? '');
        return stringValue.includes(',') || stringValue.includes('"')
          ? `"${stringValue.replace(/"/g, '""')}"`
          : stringValue;
      }).join(',')
    );
    
    const csv = [headers, ...csvRows].join('\n');
    
    // Download
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = window.document.createElement('a');
    a.href = url;
    a.download = `${document.file_name}_extracted.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const downloadJSON = () => {
    const json = JSON.stringify(rows.map(r => r.raw_json), null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = window.document.createElement('a');
    a.href = url;
    a.download = `${document.file_name}_extracted.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-[#1B1E23] border border-gray-700 rounded-lg shadow-xl max-w-7xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-700">
          <div>
            <h2 className="text-xl font-semibold text-gray-100">{document.file_name}</h2>
            <p className="text-sm text-gray-400 mt-1">
              {processedRows.length} rows {searchTerm && `(filtered from ${rows.length})`}
            </p>
          </div>
          
          <div className="flex items-center space-x-3">
            {/* View Mode Toggle */}
            <div className="flex bg-[#0D0F12] rounded-lg p-1 border border-gray-700">
              <button
                onClick={() => setViewMode('table')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  viewMode === 'table' 
                    ? 'bg-[#1B1E23] text-gray-100 shadow-sm border border-gray-700' 
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Table
              </button>
              <button
                onClick={() => setViewMode('json')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  viewMode === 'json' 
                    ? 'bg-[#1B1E23] text-gray-100 shadow-sm border border-gray-700' 
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                JSON
              </button>
              <button
                onClick={() => setViewMode('anomalies')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors relative ${
                  viewMode === 'anomalies' 
                    ? 'bg-[#1B1E23] text-gray-100 shadow-sm border border-gray-700' 
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Anomalies
                {document.anomalies_count && document.anomalies_count > 0 && (
                  <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center">
                    {document.anomalies_count}
                  </span>
                )}
              </button>
              <button
                onClick={() => setViewMode('evaluate')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  viewMode === 'evaluate' 
                    ? 'bg-[#1B1E23] text-gray-100 shadow-sm border border-gray-700' 
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                Evaluate
              </button>
            </div>

            {/* Re-run Detection Button (shown only in Anomalies tab) */}
            {viewMode === 'anomalies' && (
              <button
                onClick={rerunDetection}
                disabled={rerunLoading}
                className="px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 transition-colors flex items-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw className={`h-4 w-4 ${rerunLoading ? 'animate-spin' : ''}`} />
                <span>{rerunLoading ? 'Running...' : 'Re-run Detection'}</span>
              </button>
            )}

            {/* Download Buttons */}
            <button
              onClick={downloadCSV}
              className="px-4 py-2 bg-gradient-to-r from-cyan-400 to-green-400 text-[#0D0F12] font-semibold rounded-lg hover:opacity-90 transition-opacity flex items-center space-x-2"
            >
              <Download className="h-4 w-4" />
              <span>CSV</span>
            </button>
            
            <button
              onClick={downloadJSON}
              className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg hover:bg-gray-600 transition-colors flex items-center space-x-2"
            >
              <Download className="h-4 w-4" />
              <span>JSON</span>
            </button>

            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-[#23272E] transition-colors"
            >
              <X className="h-6 w-6" />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="p-4 border-b border-gray-700">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search in data..."
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full pl-10 pr-4 py-2 bg-[#0D0F12] border border-gray-700 rounded-lg text-gray-200 placeholder-gray-500 focus:ring-2 focus:ring-cyan-400 focus:border-transparent"
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {viewMode === 'evaluate' ? (
            <EvaluateView 
              document={document} 
              rows={rows}
              onGenerateReport={generateReport}
            />
          ) : viewMode === 'anomalies' ? (
            <AnomalyTable documentId={document.id} />
          ) : loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-gray-400">Loading data...</div>
            </div>
          ) : error ? (
            <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
              <p className="text-red-400">{error}</p>
            </div>
          ) : rows.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-gray-400">No data found</p>
            </div>
          ) : viewMode === 'table' ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-700">
                <thead className="bg-[#0D0F12] sticky top-0 border-b border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      #
                    </th>
                    {columns.map(column => (
                      <th
                        key={column}
                        className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-[#23272E] transition-colors"
                        onClick={() => handleSort(column)}
                      >
                        <div className="flex items-center space-x-1">
                          <span>{column}</span>
                          {sortColumn === column && (
                            <ArrowUpDown className="h-3 w-3" />
                          )}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-[#1B1E23] divide-y divide-gray-700">
                  {paginatedRows.map((row, index) => (
                    <tr key={row.id} className="hover:bg-[#23272E] transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-400">
                        {(currentPage - 1) * rowsPerPage + index + 1}
                      </td>
                      {columns.map(column => (
                        <td key={column} className="px-4 py-3 text-sm text-gray-100">
                          {String(row.raw_json[column] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <pre className="bg-[#0D0F12] border border-gray-700 p-4 rounded-lg overflow-auto text-sm text-gray-200">
              {JSON.stringify(rows.map(r => r.raw_json), null, 2)}
            </pre>
          )}
        </div>

        {/* Pagination */}
        {viewMode === 'table' && totalPages > 1 && (
          <div className="flex items-center justify-between p-4 border-t border-gray-700">
            <div className="text-sm text-gray-400">
              Showing {(currentPage - 1) * rowsPerPage + 1} to {Math.min(currentPage * rowsPerPage, processedRows.length)} of {processedRows.length} rows
            </div>
            
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="p-2 rounded-lg border border-gray-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#23272E] transition-colors text-gray-400 hover:text-gray-200"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
              
              <span className="text-sm text-gray-300">
                Page {currentPage} of {totalPages}
              </span>
              
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="p-2 rounded-lg border border-gray-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#23272E] transition-colors text-gray-400 hover:text-gray-200"
              >
                <ChevronRight className="h-5 w-5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


