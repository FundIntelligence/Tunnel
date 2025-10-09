'use client';

import { useState, useEffect } from 'react';
import { FileText, Trash2, Download, Eye, AlertCircle, CheckCircle, Clock, Loader2 } from 'lucide-react';
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
      const docs = await getDocuments(userId);
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
  }, [userId, refreshTrigger]);

  const handleDelete = async (documentId: string, fileName: string) => {
    if (!confirm(`Are you sure you want to delete "${fileName}"?`)) {
      return;
    }

    try {
      await deleteDocument(documentId);
      setDocuments(prev => prev.filter(doc => doc.id !== documentId));
    } catch (err: any) {
      alert(`Failed to delete document: ${err.message}`);
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
        return 'text-gray-600 bg-gray-100';
      case 'processing':
        return 'text-yellow-700 bg-yellow-100';
      case 'completed':
        return 'text-green-700 bg-green-100';
      case 'failed':
        return 'text-red-700 bg-red-100';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-700">{error}</p>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
        <FileText className="mx-auto h-12 w-12 text-gray-400 mb-4" />
        <p className="text-gray-600">No documents uploaded yet</p>
        <p className="text-sm text-gray-500 mt-2">Upload your first document to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-gray-800 mb-4">Your Documents</h2>
      
      {documents.map((document) => (
        <div
          key={document.id}
          className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-start space-x-3 flex-1">
              <FileText className="h-6 w-6 text-gray-400 mt-1" />
              
              <div className="flex-1">
                <h3 className="font-medium text-gray-900">{document.file_name}</h3>
                
                <div className="flex items-center space-x-4 mt-2 text-sm text-gray-500">
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
                    <span className="text-xs text-gray-500">
                      Format: {document.format_detected}
                    </span>
                  )}
                </div>

                {document.status === 'failed' && document.error_message && (
                  <div className="mt-2 text-xs text-red-600 bg-red-50 p-2 rounded">
                    {document.error_message}
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center space-x-2 ml-4">
              {document.status === 'completed' && (
                <button
                  onClick={() => onViewDocument(document)}
                  className="p-2 text-primary-600 hover:bg-primary-50 rounded-lg transition-colors"
                  title="View Data"
                >
                  <Eye className="h-5 w-5" />
                </button>
              )}
              
              <button
                onClick={() => handleDelete(document.id, document.file_name)}
                className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
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


