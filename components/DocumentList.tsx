'use client';

import { useState, useEffect } from 'react';
import { FileText, Trash2, Download, Eye, AlertCircle, CheckCircle, Clock, Loader2, X, RefreshCw } from 'lucide-react';
import { getDocuments, deleteDocument, Document } from '@/lib/supabase';
import { format } from 'date-fns';

interface DocumentListProps {
  userId: string;
  onViewDocument: (document: Document) => void;
  refreshTrigger?: number;
}

export default function DocumentList({ userId, onViewDocument, refreshTrigger }: DocumentListProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      console.log('Loading documents for user:', userId);
      const docs = await getDocuments(userId);
      console.log('Documents loaded:', docs);
      setDocuments(docs);
    } catch (err: any) {
      console.error('Error loading documents:', err);
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    
    // Add timeout to prevent infinite loading
    const timeout = setTimeout(() => {
      if (loading) {
        console.warn('Document loading timeout - setting error');
        setError('Loading timeout - please check your connection');
        setLoading(false);
      }
    }, 10000); // 10 second timeout
    
    return () => clearTimeout(timeout);
  }, [userId, refreshTrigger]);

  const handleDelete = async (documentId: string, fileName: string) => {
    if (!confirm(`Are you sure you want to delete "${fileName}"?`)) {
      return;
    }

    try {
      await deleteDocument(documentId);
      // Remove from local state immediately
      setDocuments(prev => prev.filter(doc => doc.id !== documentId));
      // Optionally refresh the list
      loadDocuments();
    } catch (err: any) {
      console.error('Delete error:', err);
      const errorMessage = err.message || 'Failed to delete document. Please try again.';
      alert(`Failed to delete document: ${errorMessage}`);
    }
  };

  const getStatusIcon = (status: Document['status']) => {
    switch (status) {
      case 'uploaded':
        return <Clock className="h-4 w-4 text-gray-500" />;
      case 'processing':
        return <Loader2 className="h-4 w-4 text-yellow-500 animate-spin" />;
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'failed':
        return <AlertCircle className="h-4 w-4 text-red-500" />;
    }
  };

  const getStatusText = (status: Document['status']) => {
    switch (status) {
      case 'uploaded':
        return 'Uploaded';
      case 'processing':
        return 'Processing...';
      case 'completed':
        return 'Completed';
      case 'failed':
        return 'Failed';
    }
  };

  const getStatusColor = (status: Document['status']) => {
    switch (status) {
      case 'uploaded':
        return 'text-gray-400 bg-gray-800';
      case 'processing':
        return 'text-yellow-400 bg-yellow-900/20';
      case 'completed':
        return 'text-green-400 bg-green-900/20';
      case 'failed':
        return 'text-red-400 bg-red-900/20';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 text-cyan-400 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
        <p className="text-red-400">{error}</p>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="text-center py-12 bg-[#1B1E23] rounded-lg border-2 border-dashed border-gray-700">
        <FileText className="mx-auto h-12 w-12 text-gray-500 mb-4" />
        <p className="text-gray-300">No documents uploaded yet</p>
        <p className="text-sm text-gray-400 mt-2">Upload your first document to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-gray-200 mb-4">Your Documents</h2>
      
      {documents.map((document) => (
        <div
          key={document.id}
          className="bg-[#1B1E23] border border-gray-700 rounded-lg p-4 hover:bg-[#23272E] transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start space-x-3 flex-1">
              <FileText className="h-6 w-6 text-gray-400 mt-1" />
              
              <div className="flex-1">
                <h3 className="font-medium text-white">{document.file_name}</h3>
                
                <div className="flex items-center space-x-4 mt-2 text-sm text-gray-400">
                  <span className="uppercase">{document.file_type}</span>
                  <span>•</span>
                  <span>{format(new Date(document.upload_date), 'MMM d, yyyy h:mm a')}</span>
                  {document.rows_count > 0 && (
                    <>
                      <span>•</span>
                      <span>{document.rows_count} rows</span>
                    </>
                  )}
                </div>

                <div className="mt-2 flex items-center space-x-2">
                  <div className={`inline-flex items-center space-x-1 px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(document.status)}`}>
                    {getStatusIcon(document.status)}
                    <span>{getStatusText(document.status)}</span>
                  </div>
                  
                  {document.format_detected && (
                    <span className="text-xs text-gray-400">
                      Format: {document.format_detected}
                    </span>
                  )}
                </div>

                {document.status === 'failed' && document.error_message && (
                  <div className="mt-2 text-xs text-red-400 bg-red-900/20 border border-red-800 p-2 rounded">
                    {document.error_message}
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center space-x-2 ml-4">
              {/* View button - show for completed files or files with data */}
              {(document.status === 'completed' || document.rows_count > 0) && (
                <button
                  onClick={() => onViewDocument(document)}
                  className="p-2 text-cyan-400 hover:bg-cyan-400/10 rounded-lg transition-colors"
                  title="View Data"
                >
                  <Eye className="h-5 w-5" />
                </button>
              )}
              
              {/* Cancel button - show for processing files */}
              {document.status === 'processing' && (
                <button
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (confirm(`Cancel processing for "${document.file_name}"?`)) {
                      try {
                        const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
                        const response = await fetch(`${API_BASE}/document/${document.id}/cancel`, {
                          method: 'POST'
                        });
                        if (response.ok) {
                          loadDocuments(); // Refresh list
                        } else {
                          alert('Failed to cancel processing');
                        }
                      } catch (err: any) {
                        console.error('Failed to cancel:', err);
                        alert(`Failed to cancel: ${err.message}`);
                      }
                    }
                  }}
                  className="p-2 text-orange-400 hover:bg-orange-400/10 rounded-lg transition-colors"
                  title="Cancel Processing"
                >
                  <X className="h-5 w-5" />
                </button>
              )}
              
              {/* Retry button - show for failed files */}
              {document.status === 'failed' && (
                <button
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (confirm(`Retry processing for "${document.file_name}"?`)) {
                      try {
                        const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';
                        const response = await fetch(`${API_BASE}/document/${document.id}/retry`, {
                          method: 'POST'
                        });
                        if (response.ok) {
                          loadDocuments(); // Refresh list
                        } else {
                          alert('Failed to retry processing');
                        }
                      } catch (err: any) {
                        console.error('Failed to retry:', err);
                        alert(`Failed to retry: ${err.message}`);
                      }
                    }
                  }}
                  className="p-2 text-blue-400 hover:bg-blue-400/10 rounded-lg transition-colors"
                  title="Retry Processing"
                >
                  <RefreshCw className="h-5 w-5" />
                </button>
              )}
              
              {/* Delete button - always visible */}
              <button
                onClick={(e) => {
                  e.stopPropagation(); // Prevent event bubbling
                  handleDelete(document.id, document.file_name);
                }}
                className="p-2 text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                title="Delete"
              >
                <Trash2 className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}


