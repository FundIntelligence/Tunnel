import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// Make Supabase optional - use backend API if not available
export const supabase = (supabaseUrl && supabaseAnonKey) 
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null;

// Backend API base URL (local-first mode)
const API_BASE = process.env.NEXT_PUBLIC_PARSER_API_URL || 'http://localhost:8000';

// Check if we're in local-first mode (no Supabase)
export const isLocalMode = !supabase;

// Types for our database tables
export interface Document {
  id: string;
  user_id: string | null;
  file_name: string;
  file_type: 'pdf' | 'csv' | 'xlsx';
  file_url: string | null;
  format_detected: string | null;
  upload_date: string;
  status: 'uploaded' | 'processing' | 'completed' | 'failed';
  rows_count: number;
  anomalies_count?: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExtractedRow {
  id: string;
  document_id: string;
  row_index: number;
  raw_json: Record<string, any>;
  created_at: string;
}

// Helper function to upload file to Supabase Storage or backend
export async function uploadFile(file: File, userId: string) {
  if (isLocalMode || !supabase) {
    // Local mode: upload directly to backend
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_BASE}/parse`, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      throw new Error('File upload failed');
    }
    
    const result = await response.json();
    return {
      path: file.name,
      url: `local://${file.name}`,
      document_id: result.document_id
    };
  }
  
  // Supabase mode
  const fileExt = file.name.split('.').pop();
  const fileName = `${userId}/${Date.now()}_${file.name}`;
  const filePath = `${fileName}`;

  const { data, error } = await supabase.storage
    .from('uploads')
    .upload(filePath, file, {
      cacheControl: '3600',
      upsert: false
    });

  if (error) {
    throw error;
  }

  // Get public URL
  const { data: urlData } = supabase.storage
    .from('uploads')
    .getPublicUrl(filePath);

  return {
    path: data.path,
    url: urlData.publicUrl
  };
}

// Helper function to create document record
export async function createDocument(
  userId: string,
  fileName: string,
  fileType: 'pdf' | 'csv' | 'xlsx',
  fileUrl: string
): Promise<Document> {
  if (isLocalMode || !supabase) {
    // Local mode: use backend API
    // Documents are created automatically during upload
    // Return a mock document for now
    return {
      id: Date.now().toString(),
      user_id: userId,
      file_name: fileName,
      file_type: fileType,
      file_url: fileUrl,
      format_detected: null,
      upload_date: new Date().toISOString(),
      status: 'uploaded',
      rows_count: 0,
      error_message: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
  }
  
  // Supabase mode
  const { data, error } = await supabase
    .from('documents')
    .insert({
      user_id: userId,
      file_name: fileName,
      file_type: fileType,
      file_url: fileUrl,
      status: 'uploaded'
    })
    .select()
    .single();

  if (error) {
    throw error;
  }

  return data;
}

// Helper function to update document status
export async function updateDocumentStatus(
  documentId: string,
  status: Document['status'],
  rowsCount?: number,
  errorMessage?: string
) {
  if (isLocalMode || !supabase) {
    // Local mode: document status is managed by backend
    // Just return success
    return {
      id: documentId,
      status,
      rows_count: rowsCount || 0,
      error_message: errorMessage || null
    } as Document;
  }

  // Supabase mode
  const updateData: Partial<Document> = { status };
  if (rowsCount !== undefined) updateData.rows_count = rowsCount;
  if (errorMessage !== undefined) updateData.error_message = errorMessage;

  const { data, error } = await supabase
    .from('documents')
    .update(updateData)
    .eq('id', documentId)
    .select()
    .single();

  if (error) {
    throw error;
  }

  return data;
}

// Helper function to get documents for a user
export async function getDocuments(userId: string): Promise<Document[]> {
  if (isLocalMode || !supabase) {
    // Local mode: use backend API
    const response = await fetch(`${API_BASE}/documents`);
    if (!response.ok) {
      throw new Error('Failed to fetch documents');
    }
    const data = await response.json();
    return data || [];
  }
  
  // Supabase mode
  const { data, error } = await supabase
    .from('documents')
    .select('*')
    .eq('user_id', userId)
    .order('upload_date', { ascending: false });

  if (error) {
    throw error;
  }

  return data || [];
}

// Helper function to get extracted rows for a document
export async function getExtractedRows(documentId: string): Promise<ExtractedRow[]> {
    if (isLocalMode || !supabase) {
    // Local mode: use backend API
    const response = await fetch(`${API_BASE}/document/${documentId}/rows`);
    if (!response.ok) {
      throw new Error('Failed to fetch rows');
    }
    const data = await response.json();
    // Transform backend response format to expected format
    return (data.rows || []).map((row: any) => ({
      id: `${row.row_index}`,
      document_id: documentId,
      row_index: row.row_index,
      raw_json: row.raw_json,
      created_at: new Date().toISOString()
    }));
  }
  
  // Supabase mode
  const { data, error } = await supabase
    .from('extracted_rows')
    .select('*')
    .eq('document_id', documentId)
    .order('row_index', { ascending: true });

  if (error) {
    throw error;
  }

  return data || [];
}

// Helper function to delete a document and its extracted rows
export async function deleteDocument(documentId: string) {
  if (isLocalMode || !supabase) {
    // Local mode: use backend API
    try {
      const response = await fetch(`${API_BASE}/document/${documentId}`, {
        method: 'DELETE'
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || errorData.message || `HTTP ${response.status}: Failed to delete document`);
      }
      
      const result = await response.json();
      return result;
    } catch (err: any) {
      // If it's already an Error, re-throw it
      if (err instanceof Error) {
        throw err;
      }
      throw new Error(`Failed to delete document: ${err.message || 'Unknown error'}`);
    }
  }

  // Supabase mode
  const { error } = await supabase
    .from('documents')
    .delete()
    .eq('id', documentId);

  if (error) {
    throw new Error(error.message || 'Failed to delete document');
  }
}


