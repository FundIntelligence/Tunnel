// Simple local database client (no Supabase needed)
// This replaces the Supabase client for demo purposes

export interface Document {
  id: number;
  user_id: string;
  file_name: string;
  file_type: 'pdf' | 'csv' | 'xlsx';
  file_url: string | null;
  format_detected: string | null;
  upload_date: string;
  status: 'uploaded' | 'processing' | 'completed' | 'failed';
  rows_count: number;
  error_message: string | null;
}

export interface ExtractedRow {
  id: number;
  document_id: number;
  row_index: number;
  raw_json: Record<string, any>;
  created_at: string;
}

const API_BASE = 'http://localhost:8000';

// Helper function to upload file to local backend
export async function uploadFile(file: File, userId: string) {
  // For demo, we'll store the file content directly
  const arrayBuffer = await file.arrayBuffer();
  const fileContent = new Uint8Array(arrayBuffer);
  
  return {
    content: fileContent,
    url: `demo://${file.name}` // Mock URL
  };
}

// Helper function to create document record
export async function createDocument(
  userId: string,
  fileName: string,
  fileType: 'pdf' | 'csv' | 'xlsx',
  fileUrl: string
): Promise<Document> {
  // Create document in local database
  const response = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user_id: userId,
      file_name: fileName,
      file_type: fileType,
      file_url: fileUrl,
      status: 'uploaded'
    })
  });

  if (!response.ok) {
    throw new Error('Failed to create document');
  }

  return response.json();
}

// Helper function to update document status
export async function updateDocumentStatus(
  documentId: number,
  status: Document['status'],
  rowsCount?: number,
  errorMessage?: string
) {
  const response = await fetch(`${API_BASE}/documents/${documentId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      status,
      rows_count: rowsCount,
      error_message: errorMessage
    })
  });

  if (!response.ok) {
    throw new Error('Failed to update document');
  }

  return response.json();
}

// Helper function to get documents for a user
export async function getDocuments(userId: string): Promise<Document[]> {
  const response = await fetch(`${API_BASE}/documents`);
  
  if (!response.ok) {
    throw new Error('Failed to fetch documents');
  }

  const documents = await response.json();
  return documents.filter((doc: Document) => doc.user_id === userId);
}

// Helper function to get extracted rows for a document
export async function getExtractedRows(documentId: number): Promise<ExtractedRow[]> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/rows`);
  
  if (!response.ok) {
    throw new Error('Failed to fetch extracted rows');
  }

  const rows = await response.json();
  return rows.map((row: any) => ({
    id: row.row_index,
    document_id: documentId,
    row_index: row.row_index,
    raw_json: row.raw_json,
    created_at: new Date().toISOString()
  }));
}

// Helper function to delete a document and its extracted rows
export async function deleteDocument(documentId: number) {
  const response = await fetch(`${API_BASE}/documents/${documentId}`, {
    method: 'DELETE'
  });

  if (!response.ok) {
    throw new Error('Failed to delete document');
  }

  return response.json();
}

// Parse document using local backend
export async function parseDocument(
  documentId: number,
  fileContent: Uint8Array,
  fileType: 'pdf' | 'csv' | 'xlsx'
) {
  const response = await fetch(`${API_BASE}/parse`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      document_id: documentId,
      file_content: Array.from(fileContent), // Convert to array for JSON
      file_type: fileType
    })
  });

  if (!response.ok) {
    throw new Error('Failed to parse document');
  }

  return response.json();
}
