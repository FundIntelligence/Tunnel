# 🧪 Frontend-Backend Integration Testing Guide

## 🎯 Goal
Confirm the frontend can communicate with the backend and successfully upload/parse documents without RLS errors.

---

## ✅ Prerequisites Confirmed

- [x] RLS disabled in Supabase
- [x] Backend using service_role key
- [x] CORS middleware configured
- [x] Health check endpoint exists
- [x] Upload confirmation logs added

---

## 🚀 Step-by-Step Testing Flow

### Step 1: Setup Environment Variables

#### Frontend Setup
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel

# Create .env.local
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
EOF

# Verify
cat .env.local
```

#### Backend Already Configured ✅
Service role key is hardcoded in `backend/main.py` - no additional setup needed.

---

### Step 2: Start Backend

```bash
# Terminal 1: Backend
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
python main.py
```

#### Expected Output:
```
[DEBUG] Using Supabase Service Role Key: eyJhbG... (truncated)
2025-10-13 - INFO - ✅ [DEBUG] Supabase client initialized with SERVICE_ROLE key
2025-10-13 - INFO - ✅ [DEBUG] Supabase URL: https://caajasgudqsqlztjqedc.supabase.co
2025-10-13 - INFO - ✅ [DEBUG] Service Role Key (first 20 chars): eyJhbGciOiJIUzI1NiIs...
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

✅ **Confirmation**: You should see the service role key debug line

---

### Step 3: Start Frontend

```bash
# Terminal 2: Frontend
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
npm run dev
```

#### Expected Output:
```
ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

---

### Step 4: Test Health Check

```bash
# Terminal 3: Testing
curl http://localhost:8000/health
```

#### Expected Response:
```json
{
  "status": "healthy",
  "supabase": "connected",
  "parsers": ["pdf", "csv", "xlsx"]
}
```

✅ **Confirmation**: Backend is healthy and connected to Supabase

---

### Step 5: Upload Test Document

#### 5.1 Open Frontend
```
Open: http://localhost:3000
```

#### 5.2 Upload a File
1. Drag and drop or click to select a PDF/CSV/XLSX file
2. Watch the upload progress

#### 5.3 Watch Backend Logs

You should see this sequence in Terminal 1:

```
============================================================
[DEBUG] 📨 PARSE REQUEST RECEIVED
============================================================
[DEBUG] Document ID: [uuid]
[DEBUG] File URL: [supabase storage URL]
[DEBUG] File Type: pdf
============================================================

🚀 [DEBUG] ===== PROCESSING DOCUMENT =====
🚀 [DEBUG] Document ID: [uuid]
🚀 [DEBUG] File URL: [url]
🚀 [DEBUG] File Type: pdf

📝 [DEBUG] Updating document [uuid] with data: {'status': 'processing'}
📝 [DEBUG] Using service_role key for update (bypasses RLS)
✅ [DEBUG] Update response: [...]
✅ Updated document [uuid] status to processing

[DEBUG] Starting document upload - storing rows
[DEBUG] Document ID: [uuid]
[DEBUG] Number of rows to insert: 450

📥 [DEBUG] Storing 450 rows for document [uuid]
📥 [DEBUG] Using Supabase service_role key for insert (bypasses RLS)

[DEBUG] Inserting into table: extracted_rows (batch 1)
📤 [DEBUG] Inserting batch 1 into extracted_rows table...
✅ [DEBUG] Batch insert response: [...]
[DEBUG] Insert successful. Batch 1: 450 rows
✅ Inserted batch 1: 450 rows

[DEBUG] ✅ Upload complete! Total rows: 450
✅ [DEBUG] Total rows inserted successfully: 450

📝 [DEBUG] Updating document [uuid] with data: {'status': 'completed', 'rows_count': 450}
✅ [DEBUG] Update response: [...]
✅ Updated document [uuid] status to completed

[DEBUG] ✅ PARSE COMPLETE - Document ID: [uuid]
[DEBUG] ✅ Rows extracted: 450
[DEBUG] ✅ No RLS errors encountered
```

---

### Step 6: Verify Upload Success

#### In Frontend (http://localhost:3000)
- [x] Document appears in list
- [x] Status shows "completed"
- [x] Row count displays (e.g., "450 rows")
- [x] No error messages
- [x] "View Data" button clickable

#### In Backend Logs
- [x] **NO RLS ERRORS** ❌ "row violates row-level security policy"
- [x] Service role key confirmed in use
- [x] Insert successful messages
- [x] Upload complete confirmation

#### In Supabase Dashboard
1. Go to https://supabase.com/dashboard
2. Select project: `caajasgudqsqlztjqedc`
3. Navigate to Table Editor

**Check `documents` table**:
```sql
SELECT * FROM documents ORDER BY upload_date DESC LIMIT 1;
```
- [x] New row with your uploaded file
- [x] `status` = 'completed'
- [x] `rows_count` = number of extracted rows

**Check `extracted_rows` table**:
```sql
SELECT COUNT(*) FROM extracted_rows WHERE document_id = '[your-document-id]';
```
- [x] Count matches rows_count from documents table

---

## 🎉 Success Criteria

### ✅ All Tests Passing When:

1. **Backend Startup**
   - [x] Service role key debug line appears
   - [x] No connection errors
   - [x] Server running on port 8000

2. **Health Check**
   - [x] Returns `{"status": "healthy"}`
   - [x] Supabase status is "connected"

3. **Upload Flow**
   - [x] Frontend uploads file
   - [x] Backend receives parse request
   - [x] Document status: uploaded → processing → completed
   - [x] Rows inserted without errors
   - [x] **NO RLS ERRORS**

4. **Data Verification**
   - [x] Document appears in Supabase `documents` table
   - [x] Rows appear in Supabase `extracted_rows` table
   - [x] Frontend displays extracted data
   - [x] Export functions work (CSV/JSON)

---

## 🐛 Troubleshooting

### Issue: "Failed to fetch" or CORS error

**Symptoms**:
```
Access to fetch at 'http://localhost:8000' from origin 'http://localhost:3000' 
has been blocked by CORS policy
```

**Solution**:
1. Check backend logs show CORS middleware loaded
2. Restart backend: `lsof -ti:8000 | xargs kill -9 && python main.py`
3. Verify `main.py` has CORS middleware (lines 32-39)

---

### Issue: Backend not receiving request

**Symptoms**:
- Frontend shows "Upload failed"
- No logs appear in backend terminal

**Solution**:
1. Check `.env.local` exists in frontend directory
2. Verify `NEXT_PUBLIC_API_URL=http://localhost:8000`
3. Restart frontend: `npm run dev`
4. Check network tab in browser DevTools

---

### Issue: RLS error still appearing

**Symptoms**:
```
row violates row-level security policy for table "documents"
```

**Solution**:
1. Verify service role key in backend logs:
   ```
   [DEBUG] Using Supabase Service Role Key: eyJhbG... (truncated)
   ```

2. If key not showing, restart backend:
   ```bash
   lsof -ti:8000 | xargs kill -9
   cd backend && source venv/bin/activate && python main.py
   ```

3. Confirm RLS is disabled:
   ```sql
   -- In Supabase SQL Editor
   SELECT relname, relrowsecurity 
   FROM pg_class 
   WHERE relname IN ('documents', 'extracted_rows');
   ```
   Both should show `relrowsecurity: false`

---

### Issue: 500 Internal Server Error

**Symptoms**:
- Backend logs show error
- Frontend shows "Parse failed"

**Check**:
1. Backend logs for specific error
2. File format is supported (PDF, CSV, XLSX)
3. File is not corrupted
4. Supabase storage is accessible

---

## 📊 Test Data Samples

### Good Test Files

1. **PDF**: Bank statement with tables (multi-page)
2. **CSV**: Transaction list with headers
3. **XLSX**: Financial data with multiple sheets

### Expected Results

| File Type | Expected Rows | Parse Time | Status |
|-----------|--------------|------------|--------|
| PDF (5 pages) | 200-500 | 2-5 sec | ✅ |
| CSV (1000 rows) | 1000 | < 1 sec | ✅ |
| XLSX (500 rows) | 500 | 1-2 sec | ✅ |

---

## 🔄 Cleanup Test Data

After testing, you can clean up test uploads:

```sql
-- In Supabase SQL Editor
-- Get test document IDs
SELECT id, file_name, upload_date FROM documents ORDER BY upload_date DESC LIMIT 5;

-- Delete a specific document and its rows
DELETE FROM extracted_rows WHERE document_id = '[uuid]';
DELETE FROM documents WHERE id = '[uuid]';

-- Or use the frontend "Delete" button
```

---

## 📝 Testing Checklist

### Pre-Test Setup
- [ ] Backend running on port 8000
- [ ] Frontend running on port 3000
- [ ] `.env.local` exists in frontend directory
- [ ] Service role key confirmed in backend logs

### Upload Test
- [ ] Upload PDF file successfully
- [ ] Upload CSV file successfully
- [ ] Upload XLSX file successfully
- [ ] No RLS errors in backend logs
- [ ] Data appears in Supabase tables
- [ ] Frontend displays results

### Feature Test
- [ ] View extracted data in frontend
- [ ] Search data works
- [ ] Sort columns works
- [ ] Pagination works
- [ ] Export CSV works
- [ ] Export JSON works
- [ ] Delete document works

### Error Handling
- [ ] Try uploading unsupported file (should fail gracefully)
- [ ] Try uploading empty file (should show error)
- [ ] Check error messages are clear

---

## 🚀 Next Steps After Testing

Once all tests pass:

1. **Optional Cleanup**:
   - Remove `[DEBUG]` print statements from `main.py`
   - Keep essential logging for production

2. **Prepare for Deployment**:
   - Set up backend on Render/Railway
   - Deploy frontend to Vercel
   - Configure production environment variables
   - Update CORS origins for production domain

3. **Production Testing**:
   - Test with production URLs
   - Verify environment variables
   - Check error monitoring
   - Load testing (optional)

---

## 🎯 Quick Test Command

**One-line test after setup**:
```bash
# Test health check
curl http://localhost:8000/health && echo "✅ Backend healthy"

# Then upload via frontend at http://localhost:3000
```

---

**🎉 Happy Testing!** If all tests pass, your frontend-backend integration is working perfectly! 🚀




