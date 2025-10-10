-- COMPLETE FIX: Disable RLS completely for demo
-- Run this in your Supabase SQL Editor

-- Disable RLS on both tables
ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_rows DISABLE ROW LEVEL SECURITY;

-- Drop ALL existing policies (just to be safe)
DROP POLICY IF EXISTS "Users can view their own documents" ON documents;
DROP POLICY IF EXISTS "Users can insert their own documents" ON documents;
DROP POLICY IF EXISTS "Users can update their own documents" ON documents;
DROP POLICY IF EXISTS "Users can delete their own documents" ON documents;
DROP POLICY IF EXISTS "Users can view extracted rows from their documents" ON extracted_rows;
DROP POLICY IF EXISTS "Service role can insert extracted rows" ON extracted_rows;
DROP POLICY IF EXISTS "Users can delete extracted rows from their documents" ON extracted_rows;
DROP POLICY IF EXISTS "Demo users can view documents" ON documents;
DROP POLICY IF EXISTS "Demo users can insert documents" ON documents;
DROP POLICY IF EXISTS "Demo users can update documents" ON documents;
DROP POLICY IF EXISTS "Demo users can delete documents" ON documents;
DROP POLICY IF EXISTS "Demo users can view extracted rows" ON extracted_rows;
DROP POLICY IF EXISTS "Demo users can insert extracted rows" ON extracted_rows;
DROP POLICY IF EXISTS "Demo users can delete extracted rows" ON extracted_rows;

-- Verify RLS is disabled
SELECT schemaname, tablename, rowsecurity 
FROM pg_tables 
WHERE tablename IN ('documents', 'extracted_rows');
