export type FileType = 'pdf' | 'csv' | 'xlsx';
export type DocumentStatus = 'uploaded' | 'processing' | 'completed' | 'failed';

export interface UploadProgress {
  fileName: string;
  progress: number;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  error?: string;
}

export interface ParsedData {
  documentId: string;
  fileName: string;
  rowsExtracted: number;
  data: Record<string, any>[];
}


