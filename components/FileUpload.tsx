'use client';

import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, File, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { uploadFile, createDocument, updateDocumentStatus, isLocalMode } from '@/lib/supabase';
import { FileType, UploadProgress } from '@/lib/types';
import axios from 'axios';

interface FileUploadProps {
  userId: string;
  onUploadComplete?: () => void;
}

export default function FileUpload({ userId, onUploadComplete }: FileUploadProps) {
  const [uploads, setUploads] = useState<UploadProgress[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const getFileType = (file: File): FileType | null => {
    const extension = file.name.split('.').pop()?.toLowerCase();
    if (extension === 'pdf') return 'pdf';
    if (extension === 'csv') return 'csv';
    if (extension === 'xlsx' || extension === 'xls') return 'xlsx';
    return null;
  };

  const processFile = async (file: File) => {
    const fileType = getFileType(file);
    
    if (!fileType) {
      throw new Error('Unsupported file type. Please upload PDF, CSV, or XLSX files.');
    }

    const parserUrl = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';

    // Local-first mode: upload directly to backend
    if (isLocalMode) {
      // Update progress: uploading
      setUploads(prev => prev.map(u => 
        u.fileName === file.name ? { ...u, status: 'uploading', progress: 20 } : u
      ));

      const formData = new FormData();
      formData.append('file', file);

      try {
        // Upload and parse in one step
        setUploads(prev => prev.map(u => 
          u.fileName === file.name ? { ...u, status: 'processing', progress: 50 } : u
        ));

        const response = await axios.post(`${parserUrl}/parse`, formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          timeout: 300000 // 5 minutes timeout for large files
        });

        if (response.data.success) {
          // Update progress: completed
          setUploads(prev => prev.map(u => 
            u.fileName === file.name ? { ...u, status: 'completed', progress: 100 } : u
          ));
        } else {
          throw new Error(response.data.error || 'Parsing failed');
        }
      } catch (error: any) {
        const errorMessage = error.response?.data?.detail || error.message || 'Unknown error';
        setUploads(prev => prev.map(u => 
          u.fileName === file.name ? { ...u, status: 'error', error: errorMessage, progress: 0 } : u
        ));
        throw new Error(`Parsing failed: ${errorMessage}`);
      }
      return;
    }

    // Supabase mode: use existing flow
    // Update progress: uploading
    setUploads(prev => prev.map(u => 
      u.fileName === file.name ? { ...u, status: 'uploading', progress: 30 } : u
    ));

    // Upload to Supabase Storage
    const { url } = await uploadFile(file, userId);

    // Update progress: creating record
    setUploads(prev => prev.map(u => 
      u.fileName === file.name ? { ...u, progress: 50 } : u
    ));

    // Create document record
    const document = await createDocument(userId, file.name, fileType, url);

    // Update progress: processing
    setUploads(prev => prev.map(u => 
      u.fileName === file.name ? { ...u, status: 'processing', progress: 70 } : u
    ));

    // Update document status to processing
    await updateDocumentStatus(document.id, 'processing');

    // Call parser API
    try {
      const response = await axios.post(`${parserUrl}/parse`, {
        document_id: document.id,
        file_url: url,
        file_type: fileType
      }, {
        timeout: 300000 // 5 minutes timeout for large files
      });

      if (response.data.success) {
        // Update document status to completed
        await updateDocumentStatus(document.id, 'completed', response.data.rows_extracted);
        
        // Update progress: completed
        setUploads(prev => prev.map(u => 
          u.fileName === file.name ? { ...u, status: 'completed', progress: 100 } : u
        ));
      } else {
        throw new Error(response.data.error || 'Parsing failed');
      }
    } catch (error: any) {
      // Update document status to failed
      const errorMessage = error.response?.data?.detail || error.message || 'Unknown error';
      await updateDocumentStatus(document.id, 'failed', 0, errorMessage);
      
      throw new Error(`Parsing failed: ${errorMessage}`);
    }
  };

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    setIsUploading(true);

    // Initialize upload progress for all files
    const newUploads: UploadProgress[] = acceptedFiles.map(file => ({
      fileName: file.name,
      progress: 0,
      status: 'uploading'
    }));
    setUploads(prev => [...prev, ...newUploads]);

    // Process files sequentially
    for (const file of acceptedFiles) {
      try {
        await processFile(file);
      } catch (error: any) {
        console.error(`Error processing ${file.name}:`, error);
        setUploads(prev => prev.map(u => 
          u.fileName === file.name 
            ? { ...u, status: 'error', error: error.message, progress: 0 } 
            : u
        ));
      }
    }

    setIsUploading(false);
    
    // Call callback to refresh document list
    if (onUploadComplete) {
      onUploadComplete();
    }

    // Clear completed uploads after 5 seconds
    setTimeout(() => {
      setUploads(prev => prev.filter(u => u.status === 'uploading' || u.status === 'processing'));
    }, 5000);
  }, [userId, onUploadComplete]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls']
    },
    disabled: isUploading
  });

  return (
    <div className="w-full">
      <div
        {...getRootProps()}
        className={`
          border-2 border-dashed rounded-lg p-12 text-center cursor-pointer
          transition-colors duration-200
          ${isDragActive 
            ? 'border-cyan-400 bg-cyan-400/10' 
            : 'border-gray-600 hover:border-cyan-400 bg-[#1B1E23]'
          }
          ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}
        `}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
        {isDragActive ? (
          <p className="text-lg text-cyan-400">Drop the files here...</p>
        ) : (
          <>
            <p className="text-lg text-gray-200 mb-2">
              Drag & drop files here, or click to select
            </p>
            <p className="text-sm text-gray-400">
              Supports: PDF, CSV, XLSX (Max 50MB per file)
            </p>
          </>
        )}
      </div>

      {/* Upload Progress */}
      {uploads.length > 0 && (
        <div className="mt-6 space-y-3">
          <h3 className="text-sm font-semibold text-gray-300">Upload Progress</h3>
          {uploads.map((upload, index) => (
            <div key={index} className="bg-[#1B1E23] border border-gray-700 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center space-x-3">
                  <File className="h-5 w-5 text-gray-400" />
                  <span className="text-sm font-medium text-gray-200">
                    {upload.fileName}
                  </span>
                </div>
                <div>
                  {upload.status === 'uploading' && (
                    <Loader2 className="h-5 w-5 text-cyan-400 animate-spin" />
                  )}
                  {upload.status === 'processing' && (
                    <Loader2 className="h-5 w-5 text-yellow-400 animate-spin" />
                  )}
                  {upload.status === 'completed' && (
                    <CheckCircle className="h-5 w-5 text-green-400" />
                  )}
                  {upload.status === 'error' && (
                    <XCircle className="h-5 w-5 text-red-400" />
                  )}
                </div>
              </div>
              
              {/* Progress Bar */}
              {(upload.status === 'uploading' || upload.status === 'processing') && (
                <div className="w-full bg-gray-700 rounded-full h-2">
                  <div
                    className="bg-gradient-to-r from-cyan-400 to-green-400 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${upload.progress}%` }}
                  />
                </div>
              )}

              {/* Status Text */}
              <div className="mt-2">
                {upload.status === 'uploading' && (
                  <p className="text-xs text-gray-400">Uploading...</p>
                )}
                {upload.status === 'processing' && (
                  <p className="text-xs text-yellow-400">Extracting data...</p>
                )}
                {upload.status === 'completed' && (
                  <p className="text-xs text-green-400">Completed successfully!</p>
                )}
                {upload.status === 'error' && (
                  <p className="text-xs text-red-400">{upload.error}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


