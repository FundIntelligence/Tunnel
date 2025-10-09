-- FundIQ MVP Database Schema
-- Run this in your Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'csv', 'xlsx')),
    file_url TEXT,
    format_detected TEXT,
    upload_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'uploaded' CHECK (status IN ('uploaded', 'processing', 'completed', 'failed')),
    rows_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Extracted Rows Table
CREATE TABLE IF NOT EXISTS extracted_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, row_index)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_upload_date ON documents(upload_date DESC);
CREATE INDEX IF NOT EXISTS idx_extracted_rows_document_id ON extracted_rows(document_id);
CREATE INDEX IF NOT EXISTS idx_extracted_rows_raw_json ON extracted_rows USING GIN(raw_json);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER update_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Row Level Security (RLS) Policies
-- Enable RLS
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_rows ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own documents
CREATE POLICY "Users can view their own documents"
    ON documents FOR SELECT
    USING (auth.uid() = user_id);

-- Policy: Users can insert their own documents
CREATE POLICY "Users can insert their own documents"
    ON documents FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Policy: Users can update their own documents
CREATE POLICY "Users can update their own documents"
    ON documents FOR UPDATE
    USING (auth.uid() = user_id);

-- Policy: Users can delete their own documents
CREATE POLICY "Users can delete their own documents"
    ON documents FOR DELETE
    USING (auth.uid() = user_id);

-- Policy: Users can view extracted rows from their documents
CREATE POLICY "Users can view extracted rows from their documents"
    ON extracted_rows FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM documents
            WHERE documents.id = extracted_rows.document_id
            AND documents.user_id = auth.uid()
        )
    );

-- Policy: Service role can insert extracted rows
CREATE POLICY "Service role can insert extracted rows"
    ON extracted_rows FOR INSERT
    WITH CHECK (true);

-- Policy: Users can delete extracted rows from their documents
CREATE POLICY "Users can delete extracted rows from their documents"
    ON extracted_rows FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM documents
            WHERE documents.id = extracted_rows.document_id
            AND documents.user_id = auth.uid()
        )
    );

-- Storage bucket setup (run this separately in Storage section or via SQL)
-- INSERT INTO storage.buckets (id, name, public) VALUES ('uploads', 'uploads', false);

-- Storage policies for uploads bucket
CREATE POLICY "Users can upload files"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'uploads' AND auth.role() = 'authenticated');

CREATE POLICY "Users can view their own files"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'uploads' AND auth.role() = 'authenticated');

CREATE POLICY "Users can delete their own files"
    ON storage.objects FOR DELETE
    USING (bucket_id = 'uploads' AND auth.role() = 'authenticated');


