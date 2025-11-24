'use client';

import { useState, useEffect } from 'react';
import { FileText, Download, Eye, Trash2, CheckCircle, XCircle, Clock } from 'lucide-react';

interface Document {
  id: number;
  user_id: string;
  file_name: string;
  file_type: string;
  upload_date: string;
  status: string;
  rows_count: number;
  error_message: string | null;
}

interface ExtractedRow {
  row_index: number;
  raw_json: Record<string, any>;
}

interface SimpleDocumentListProps {
  refreshTrigger: number;
}

export default function SimpleDocumentList({ refreshTrigger }: SimpleDocumentListProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [extractedRows, setExtractedRows] = useState<ExtractedRow[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch documents from backend
  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/documents`);
      if (response.ok) {
        const data = await response.json();
        setDocuments(data);
      }
    } catch (error) {
      console.error('Error fetching documents:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch extracted rows for a document
  const fetchExtractedRows = async (documentId: number) => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/document/${documentId}/rows`);
      if (response.ok) {
        const data = await response.json();
        setExtractedRows(data);
      }
    } catch (error) {
      console.error('Error fetching extracted rows:', error);
    }
  };

  // Delete a document
  const deleteDocument = async (documentId: number) => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_BASE}/document/${documentId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        setDocuments(documents.filter(doc => doc.id !== documentId));
        if (selectedDocument?.id === documentId) {
          setSelectedDocument(null);
          setExtractedRows([]);
        }
      }
    } catch (error) {
      console.error('Error deleting document:', error);
    }
  };

  // Download extracted data as CSV
  const downloadAsCSV = (doc: Document, rows: ExtractedRow[]) => {
    if (rows.length === 0) return;

    // Get all unique keys from the data
    const allKeys = new Set<string>();
    rows.forEach(row => {
      Object.keys(row.raw_json).forEach(key => allKeys.add(key));
    });

    // Create CSV header
    const headers = Array.from(allKeys);
    const csvContent = [
      headers.join(','),
      ...rows.map(row => 
        headers.map(header => {
          const value = row.raw_json[header] || '';
          // Escape commas and quotes in CSV
          return `"${String(value).replace(/"/g, '""')}"`;
        }).join(',')
      )
    ].join('\n');

    // Create and download file
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.file_name.replace(/\.[^/.]+$/, '')}_extracted.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  // Download extracted data as JSON
  const downloadAsJSON = (doc: Document, rows: ExtractedRow[]) => {
    const jsonContent = JSON.stringify(rows, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.file_name.replace(/\.[^/.]+$/, '')}_extracted.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  // Handle document selection
  const handleDocumentSelect = (doc: Document) => {
    setSelectedDocument(doc);
    fetchExtractedRows(doc.id);
  };

  // Refresh documents when trigger changes
  useEffect(() => {
    fetchDocuments();
  }, [refreshTrigger]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />;
      case 'processing':
        return <Clock className="h-4 w-4 text-yellow-500 animate-spin" />;
      default:
        return <Clock className="h-4 w-4 text-gray-500" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 bg-green-50';
      case 'failed':
        return 'text-red-600 bg-red-50';
      case 'processing':
        return 'text-yellow-600 bg-yellow-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-800">Documents</h2>
        {documents.length > 0 && (
          <span className="text-sm text-gray-500">{documents.length} document(s)</span>
        )}
      </div>

      {loading ? (
        <div className="text-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
          <p className="text-gray-500 mt-2">Loading documents...</p>
        </div>
      ) : documents.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <FileText className="mx-auto h-12 w-12 text-gray-400 mb-4" />
          <p className="text-gray-600">No documents uploaded yet</p>
          <p className="text-sm text-gray-500 mt-2">Upload your first document to get started</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Document List */}
          <div className="space-y-3">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className={`border rounded-lg p-4 cursor-pointer transition-colors ${
                  selectedDocument?.id === doc.id
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
                onClick={() => handleDocumentSelect(doc)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <FileText className="h-5 w-5 text-gray-400" />
                    <div>
                      <p className="font-medium text-gray-900">{doc.file_name}</p>
                      <div className="flex items-center space-x-2 mt-1">
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(doc.status)}`}>
                          {doc.status}
                        </span>
                        {doc.status === 'completed' && (
                          <span className="text-xs text-gray-500">
                            {doc.rows_count} rows extracted
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    {getStatusIcon(doc.status)}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteDocument(doc.id);
                      }}
                      className="p-1 text-gray-400 hover:text-red-500"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Extracted Data Preview */}
          {selectedDocument && extractedRows.length > 0 && (
            <div className="mt-6 border-t pt-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-md font-semibold text-gray-800">
                  Extracted Data ({extractedRows.length} rows)
                </h3>
                <div className="flex space-x-2">
                  <button
                    onClick={() => downloadAsCSV(selectedDocument, extractedRows)}
                    className="flex items-center space-x-1 px-3 py-1 bg-green-600 text-white rounded text-sm hover:bg-green-700"
                  >
                    <Download className="h-4 w-4" />
                    <span>CSV</span>
                  </button>
                  <button
                    onClick={() => downloadAsJSON(selectedDocument, extractedRows)}
                    className="flex items-center space-x-1 px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
                  >
                    <Download className="h-4 w-4" />
                    <span>JSON</span>
                  </button>
                </div>
              </div>

              {/* Data Table */}
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      {Object.keys(extractedRows[0]?.raw_json || {}).map((key) => (
                        <th
                          key={key}
                          className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                        >
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {extractedRows.slice(0, 10).map((row, index) => (
                      <tr key={index} className="hover:bg-gray-50">
                        {Object.values(row.raw_json).map((value, cellIndex) => (
                          <td
                            key={cellIndex}
                            className="px-3 py-2 text-sm text-gray-900 max-w-xs truncate"
                            title={String(value)}
                          >
                            {String(value)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {extractedRows.length > 10 && (
                  <p className="text-xs text-gray-500 mt-2 text-center">
                    Showing first 10 rows of {extractedRows.length} total rows
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Error Message */}
          {selectedDocument?.error_message && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded">
              <p className="text-sm text-red-600">
                <strong>Error:</strong> {selectedDocument.error_message}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
