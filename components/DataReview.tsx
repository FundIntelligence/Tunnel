'use client';

import { useState, useEffect, useMemo } from 'react';
import { Download, X, Search, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { getExtractedRows, Document, ExtractedRow } from '@/lib/supabase';

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
  const [viewMode, setViewMode] = useState<'table' | 'json'>('table');
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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-7xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{document.file_name}</h2>
            <p className="text-sm text-gray-500 mt-1">
              {processedRows.length} rows {searchTerm && `(filtered from ${rows.length})`}
            </p>
          </div>
          
          <div className="flex items-center space-x-3">
            {/* View Mode Toggle */}
            <div className="flex bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => setViewMode('table')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  viewMode === 'table' 
                    ? 'bg-white text-gray-900 shadow-sm' 
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Table
              </button>
              <button
                onClick={() => setViewMode('json')}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  viewMode === 'json' 
                    ? 'bg-white text-gray-900 shadow-sm' 
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                JSON
              </button>
            </div>

            {/* Download Buttons */}
            <button
              onClick={downloadCSV}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors flex items-center space-x-2"
            >
              <Download className="h-4 w-4" />
              <span>CSV</span>
            </button>
            
            <button
              onClick={downloadJSON}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors flex items-center space-x-2"
            >
              <Download className="h-4 w-4" />
              <span>JSON</span>
            </button>

            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <X className="h-6 w-6" />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="p-4 border-b border-gray-200">
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
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-gray-500">Loading data...</div>
            </div>
          ) : error ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-red-700">{error}</p>
            </div>
          ) : rows.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-gray-500">No data found</p>
            </div>
          ) : viewMode === 'table' ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      #
                    </th>
                    {columns.map(column => (
                      <th
                        key={column}
                        className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
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
                <tbody className="bg-white divide-y divide-gray-200">
                  {paginatedRows.map((row, index) => (
                    <tr key={row.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {(currentPage - 1) * rowsPerPage + index + 1}
                      </td>
                      {columns.map(column => (
                        <td key={column} className="px-4 py-3 text-sm text-gray-900">
                          {String(row.raw_json[column] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <pre className="bg-gray-50 p-4 rounded-lg overflow-auto text-sm">
              {JSON.stringify(rows.map(r => r.raw_json), null, 2)}
            </pre>
          )}
        </div>

        {/* Pagination */}
        {viewMode === 'table' && totalPages > 1 && (
          <div className="flex items-center justify-between p-4 border-t border-gray-200">
            <div className="text-sm text-gray-500">
              Showing {(currentPage - 1) * rowsPerPage + 1} to {Math.min(currentPage * rowsPerPage, processedRows.length)} of {processedRows.length} rows
            </div>
            
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="p-2 rounded-lg border border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
              
              <span className="text-sm text-gray-700">
                Page {currentPage} of {totalPages}
              </span>
              
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="p-2 rounded-lg border border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
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


