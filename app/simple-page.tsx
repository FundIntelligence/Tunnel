'use client';

import { useState } from 'react';
import SimpleFileUpload from '@/components/SimpleFileUpload';
import { FileText } from 'lucide-react';

export default function SimplePage() {
  // For demo purposes, using a hardcoded user ID
  const userId = 'demo-user-123';
  
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleUploadComplete = () => {
    // Trigger document list refresh
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center space-x-3">
            <div className="bg-primary-600 p-2 rounded-lg">
              <FileText className="h-8 w-8 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">FundIQ</h1>
              <p className="text-sm text-gray-600">Financial Intelligence Platform (Local Demo)</p>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left Column: Upload */}
          <div>
            <div className="bg-white rounded-lg shadow-md p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">Upload Documents</h2>
              <p className="text-gray-600 mb-6">
                Upload your financial documents to automatically extract and analyze data.
                <br />
                <span className="text-sm text-blue-600 font-medium">
                  ✅ Using local SQLite database - no Supabase needed!
                </span>
              </p>
              <SimpleFileUpload userId={userId} onUploadComplete={handleUploadComplete} />
            </div>

            {/* Info Cards */}
            <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
                <div className="text-2xl font-bold text-primary-600">PDF</div>
                <div className="text-xs text-gray-600 mt-1">Extract tables & text</div>
              </div>
              <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
                <div className="text-2xl font-bold text-primary-600">CSV</div>
                <div className="text-xs text-gray-600 mt-1">Parse structured data</div>
              </div>
              <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
                <div className="text-2xl font-bold text-primary-600">XLSX</div>
                <div className="text-xs text-gray-600 mt-1">Extract spreadsheets</div>
              </div>
            </div>
          </div>

          {/* Right Column: Document List */}
          <div>
            <div className="bg-white rounded-lg shadow-md p-6">
              <h2 className="text-lg font-semibold text-gray-800 mb-4">Documents</h2>
              <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
                <FileText className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                <p className="text-gray-600">No documents uploaded yet</p>
                <p className="text-sm text-gray-500 mt-2">Upload your first document to get started</p>
              </div>
            </div>
          </div>
        </div>

        {/* Features Section */}
        <div className="mt-12 bg-white rounded-lg shadow-md p-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">How It Works</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="text-center">
              <div className="bg-primary-100 rounded-full w-12 h-12 flex items-center justify-center mx-auto mb-3">
                <span className="text-primary-600 font-bold text-lg">1</span>
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Upload</h3>
              <p className="text-sm text-gray-600">
                Drag and drop your PDF, CSV, or Excel files
              </p>
            </div>
            
            <div className="text-center">
              <div className="bg-primary-100 rounded-full w-12 h-12 flex items-center justify-center mx-auto mb-3">
                <span className="text-primary-600 font-bold text-lg">2</span>
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Extract</h3>
              <p className="text-sm text-gray-600">
                AI automatically extracts structured data
              </p>
            </div>
            
            <div className="text-center">
              <div className="bg-primary-100 rounded-full w-12 h-12 flex items-center justify-center mx-auto mb-3">
                <span className="text-primary-600 font-bold text-lg">3</span>
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Review</h3>
              <p className="text-sm text-gray-600">
                View and validate the extracted information
              </p>
            </div>
            
            <div className="text-center">
              <div className="bg-primary-100 rounded-full w-12 h-12 flex items-center justify-center mx-auto mb-3">
                <span className="text-primary-600 font-bold text-lg">4</span>
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">Export</h3>
              <p className="text-sm text-gray-600">
                Download as CSV or JSON for analysis
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
