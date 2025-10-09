import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing Supabase environment variables');
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

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

// Helper function to upload file to Supabase Storage
export async function uploadFile(file: File, userId: string) {
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
  const { error } = await supabase
    .from('documents')
    .delete()
    .eq('id', documentId);

  if (error) {
    throw error;
  }
}


