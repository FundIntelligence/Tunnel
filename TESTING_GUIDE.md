# FundIQ Testing Guide
## Service Role Key Configuration & End-to-End Testing

---

## 🎯 Overview

This guide covers:
1. ✅ Verifying service_role key is correctly configured
2. ✅ Testing Supabase mode (production)
3. ✅ Testing SQLite mode (demo/development)
4. ✅ End-to-end upload and parsing workflow

---

## 📋 Prerequisites

### Backend Setup
```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Variables
The service_role key is now **hardcoded in main.py** as a fallback:
- URL: `https://caajasgudqsqlztjqedc.supabase.co`
- Service Role Key: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`

*Alternatively, create a `.env` file in the backend directory:*
```env
SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8
```

---

## 🧪 Step 1: Test Service Role Connection

### Run the Test Script
```bash
cd backend
python test_service_role.py
```

### Expected Output
```
🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬
SUPABASE SERVICE_ROLE KEY VERIFICATION TEST
🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬🔬

============================================================
TEST 1: Supabase Service Role Connection
============================================================
✓ Supabase URL: https://caajasgudqsqlztjqedc.supabase.co
✓ Service Role Key (first 30 chars): eyJhbGciOiJIUzI1NiIsInR5cCI6Ik...
✅ Supabase client created successfully
✅ Successfully connected to Supabase
✅ Documents table accessible

============================================================
TEST 2: Insert Document with Service Role (Bypass RLS)
============================================================
✓ Inserting test document: [uuid]
✅ Document inserted successfully!
✅ Response data: [...]

============================================================
TEST 3: Insert Extracted Rows with Service Role (Bypass RLS)
============================================================
✓ Inserting 2 test rows for document [uuid]
✅ Extracted rows inserted successfully!
✅ Inserted 2 rows

============================================================
TEST 4: Update Document with Service Role (Bypass RLS)
============================================================
✓ Updating document [uuid] to status 'completed'
✅ Document updated successfully!

🎉 ALL TESTS PASSED! Service role key is working correctly.
✅ RLS is being bypassed as expected.
✅ Backend should be able to insert/update without RLS errors.
```

### ❌ If Tests Fail

**Error: "row violates row-level security policy"**
- The service_role key is not being used
- Check that `main.py` has the correct key
- Verify backend is using the updated `main.py`

**Error: "relation does not exist"**
- Database tables are not created
- Run the schema in Supabase SQL Editor: `supabase/schema.sql`

**Error: "Invalid JWT"**
- Service role key is incorrect or expired
- Get a new key from Supabase Dashboard → Settings → API

---

## 🚀 Step 2: Test Supabase Mode (Production)

### 2.1 Start Backend
```bash
cd backend
source venv/bin/activate
python main.py
```

### 2.2 Check Startup Logs
You should see:
```
✅ [DEBUG] Supabase client initialized with SERVICE_ROLE key
✅ [DEBUG] Supabase URL: https://caajasgudqsqlztjqedc.supabase.co
✅ [DEBUG] Service Role Key (first 20 chars): eyJhbGciOiJIUzI1NiIsI...
INFO:     Started server process [PID]
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2.3 Start Frontend
```bash
# In a new terminal
cd FundIQ/Tunnel
npm run dev
```

### 2.4 Upload a Test File
1. Open http://localhost:3000
2. Upload a PDF, CSV, or XLSX file
3. Watch the backend terminal for debug logs

### Expected Backend Logs
```
📨 [DEBUG] ===== PARSE REQUEST RECEIVED =====
📨 [DEBUG] Document ID: [uuid]
📨 [DEBUG] File URL: [supabase storage URL]
📨 [DEBUG] File Type: pdf

🚀 [DEBUG] ===== PROCESSING DOCUMENT =====
🚀 [DEBUG] Document ID: [uuid]
🚀 [DEBUG] File URL: [url]
🚀 [DEBUG] File Type: pdf

📝 [DEBUG] Updating document [uuid] with data: {'status': 'processing'}
📝 [DEBUG] Using service_role key for update (bypasses RLS)
✅ [DEBUG] Update response: [response object]
✅ Updated document [uuid] status to processing

📥 [DEBUG] Storing 450 rows for document [uuid]
📥 [DEBUG] Using Supabase service_role key for insert (bypasses RLS)
📤 [DEBUG] Inserting batch 1 into extracted_rows table...
✅ [DEBUG] Batch insert response: [response object]
✅ Inserted batch 1: 450 rows
✅ [DEBUG] Total rows inserted successfully: 450

📝 [DEBUG] Updating document [uuid] with data: {'status': 'completed', 'rows_count': 450}
✅ [DEBUG] Update response: [response object]
✅ Updated document [uuid] status to completed
```

### ✅ Success Indicators
- No RLS errors in logs
- Document status changes: uploaded → processing → completed
- Rows appear in Supabase `extracted_rows` table
- Frontend shows completed document with row count

### ❌ Failure Indicators
- Error: "row violates row-level security policy"
  - **Fix**: Verify service_role key is correct
  - **Fix**: Restart backend to reload configuration

- Error: "File not found" or "Access denied"
  - **Fix**: Check Supabase storage bucket permissions
  - **Fix**: Verify file_url is accessible

---

## 🗃️ Step 3: Test SQLite Mode (Demo)

### 3.1 Start SQLite Backend
```bash
cd backend
source venv/bin/activate
python simple_main.py
```

Backend will run on `http://127.0.0.1:8002`

### 3.2 Start Frontend (Demo Page)
```bash
cd FundIQ/Tunnel
PORT=3001 npm run dev
```

### 3.3 Access Demo Page
Open http://localhost:3001/simple-page

### 3.4 Upload Test File
1. Drag and drop a file (PDF, CSV, or XLSX)
2. File is uploaded and parsed immediately
3. Data stored in local `fundiq_demo.db` SQLite database

### Expected Behavior
- ✅ File uploads without Supabase
- ✅ Parsing works locally
- ✅ Data stored in SQLite
- ✅ No network requests to Supabase

### Check SQLite Data
```bash
cd backend
sqlite3 fundiq_demo.db

.tables
SELECT * FROM documents;
SELECT * FROM extracted_rows LIMIT 5;
.quit
```

---

## 🔄 Step 4: End-to-End Upload + Parse Test

### Test Checklist

#### ✅ Supabase Mode
- [ ] Backend starts with service_role key confirmation
- [ ] Frontend connects to http://localhost:8000
- [ ] Upload PDF file → status: uploaded
- [ ] Parse triggered → status: processing
- [ ] Rows inserted → status: completed
- [ ] No RLS errors in backend logs
- [ ] Data appears in Supabase tables
- [ ] Frontend shows extracted data
- [ ] CSV/JSON export works

#### ✅ SQLite Mode
- [ ] SQLite backend starts on port 8002
- [ ] Frontend connects to demo page
- [ ] Upload file → immediate parsing
- [ ] Data stored in `fundiq_demo.db`
- [ ] No Supabase calls made
- [ ] Frontend shows extracted data
- [ ] CSV/JSON export works

---

## 📊 Verification Queries

### Check Documents in Supabase
```sql
SELECT 
    id, 
    file_name, 
    status, 
    rows_count, 
    upload_date,
    error_message
FROM documents
ORDER BY upload_date DESC
LIMIT 10;
```

### Check Extracted Rows in Supabase
```sql
SELECT 
    document_id,
    COUNT(*) as row_count
FROM extracted_rows
GROUP BY document_id
ORDER BY COUNT(*) DESC
LIMIT 10;
```

### Check SQLite Data
```bash
sqlite3 backend/fundiq_demo.db "SELECT COUNT(*) FROM documents;"
sqlite3 backend/fundiq_demo.db "SELECT COUNT(*) FROM extracted_rows;"
```

---

## 🐛 Troubleshooting

### Problem: RLS Error Still Appearing

**Solution 1: Verify Service Role Key**
```bash
cd backend
python -c "
from main import SUPABASE_SERVICE_ROLE_KEY
print(f'Key starts with: {SUPABASE_SERVICE_ROLE_KEY[:30]}')
print(f'Key length: {len(SUPABASE_SERVICE_ROLE_KEY)}')
"
```

**Solution 2: Disable RLS Temporarily**
```sql
-- Run in Supabase SQL Editor
ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_rows DISABLE ROW LEVEL SECURITY;
```

**Solution 3: Check Backend is Using Correct File**
```bash
# Restart backend with explicit file
cd backend
python -c "import main; print('Using:', main.__file__)"
python main.py
```

### Problem: Ports Already in Use

**Kill Existing Processes**
```bash
# Kill all Python/Node processes
lsof -ti:3000,3001,8000,8001,8002 | xargs kill -9

# Or kill specific port
kill -9 $(lsof -ti:8000)
```

### Problem: Import Errors

**Reinstall Dependencies**
```bash
cd backend
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

---

## 📝 Testing Summary

### Service Role Key Configuration
✅ Hardcoded in `main.py` with fallback to `.env`  
✅ Confirmed in startup logs  
✅ Verified with `test_service_role.py`

### Supabase Mode Tests
✅ Connection established  
✅ Document insert works (bypasses RLS)  
✅ Extracted rows insert works (bypasses RLS)  
✅ Document update works (bypasses RLS)  
✅ End-to-end upload + parse successful

### SQLite Mode Tests
✅ Local database created  
✅ File upload and parsing works  
✅ No Supabase dependency  
✅ Data export functional

---

## 🎉 Success Criteria

You can confirm everything is working when:

1. **Service Role Test Passes**
   ```bash
   python test_service_role.py
   # Output: 🎉 ALL TESTS PASSED!
   ```

2. **Supabase Mode Works**
   - Upload file in production app
   - Backend logs show: `✅ [DEBUG] Using service_role key for insert (bypasses RLS)`
   - No RLS errors
   - Data appears in Supabase dashboard

3. **SQLite Mode Works**
   - Upload file in demo app
   - Data stored locally
   - No network calls

---

## 📞 Next Steps

After confirming all tests pass:

1. **Remove Debug Logs** (Optional)
   - Remove `[DEBUG]` log statements from `main.py`
   - Keep essential info/error logs

2. **Secure the Key** (Production)
   - Move service_role key to `.env` file only
   - Remove hardcoded fallback
   - Add `.env` to `.gitignore`

3. **Deploy**
   - Frontend to Vercel
   - Backend to Railway/Render
   - Configure environment variables in deployment platform

---

**Happy Testing! 🚀**


