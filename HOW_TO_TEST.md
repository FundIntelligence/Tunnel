# 🧪 How to Test FundIQ Project - Complete Guide

## 🎯 Quick Test (5 Minutes)

### Option 1: Full Production Mode (Supabase)

```bash
# Step 1: Test backend connection (30 seconds)
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
python test_service_role.py

# Step 2: Start backend (Terminal 1)
python main.py

# Step 3: Start frontend (Terminal 2 - NEW TERMINAL)
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
npm run dev

# Step 4: Open browser
open http://localhost:3000
```

### Option 2: Demo Mode (SQLite - No Supabase Needed)

```bash
# Step 1: Start SQLite backend (Terminal 1)
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
python simple_main.py

# Step 2: Start frontend (Terminal 2 - NEW TERMINAL)
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
PORT=3001 npm run dev

# Step 3: Open demo page
open http://localhost:3001/simple-page
```

---

## 📋 Detailed Testing Steps

### Prerequisites Check

Before starting, verify you have:

```bash
# Check Node.js installed
node --version  # Should be 18+

# Check Python installed
python3 --version  # Should be 3.9+

# Check you're in the right directory
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
ls -la package.json  # Should exist
```

---

## 🧪 Step-by-Step Testing

### Test 1: Backend Service Role Connection

**Purpose**: Verify backend can connect to Supabase

```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
python test_service_role.py
```

**Expected Output**:
```
🔬 SUPABASE SERVICE_ROLE KEY VERIFICATION TEST
✅ Supabase client created successfully
✅ Successfully connected to Supabase
✅ Documents table accessible
✅ Document inserted successfully!
✅ Extracted rows inserted successfully!
🎉 ALL TESTS PASSED!
```

**If it fails**: Check `backend/main.py` has the correct Supabase credentials.

---

### Test 2: Backend Health Check

**Purpose**: Verify backend API is running

```bash
# Terminal 1: Start backend
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
python main.py
```

**Look for these logs**:
```
✅ [DEBUG] Supabase client initialized with SERVICE_ROLE key
✅ [DEBUG] Supabase URL: https://caajasgudqsqlztjqedc.supabase.co
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Terminal 2: Test health endpoint**
```bash
curl http://localhost:8000/health
```

**Expected Response**:
```json
{
  "status": "healthy",
  "supabase": "connected",
  "parsers": ["pdf", "csv", "xlsx"]
}
```

---

### Test 3: Frontend Setup

**Purpose**: Verify frontend can connect to backend

```bash
# Check if .env.local exists
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
ls -la .env.local

# If it doesn't exist, create it:
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
EOF

# Start frontend
npm run dev
```

**Expected Output**:
```
ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

**Open Browser**: http://localhost:3000

---

### Test 4: File Upload Test

**Purpose**: Test end-to-end upload and parsing

#### Steps:

1. **Make sure both backend and frontend are running**
   - Backend: `http://localhost:8000`
   - Frontend: `http://localhost:3000`

2. **Upload a test file**:
   - Open http://localhost:3000
   - Drag and drop a PDF, CSV, or XLSX file
   - Or click to select a file

3. **Watch backend logs** (Terminal 1):
   ```
   📨 [DEBUG] ===== PARSE REQUEST RECEIVED =====
   [DEBUG] Document ID: [uuid]
   [DEBUG] File Type: pdf
   
   📥 [DEBUG] Using Supabase service_role key for insert (bypasses RLS)
   ✅ [DEBUG] Total rows inserted successfully: [number]
   ✅ [DEBUG] PARSE COMPLETE
   ```

4. **Check frontend**:
   - Document should appear in the list
   - Status should change: `uploaded` → `processing` → `completed`
   - Row count should display
   - No error messages

5. **Click "View Data"**:
   - Modal should open
   - Extracted data should appear in table
   - Search should work
   - Export buttons should work

---

### Test 5: Verify Data in Supabase

**Purpose**: Confirm data was stored correctly

1. **Go to Supabase Dashboard**: https://supabase.com/dashboard
2. **Select project**: `caajasgudqsqlztjqedc`
3. **Open SQL Editor** and run:

```sql
-- Check documents
SELECT 
    id, 
    file_name, 
    status, 
    rows_count, 
    upload_date
FROM documents
ORDER BY upload_date DESC
LIMIT 5;

-- Check extracted rows count
SELECT 
    document_id,
    COUNT(*) as row_count
FROM extracted_rows
GROUP BY document_id
ORDER BY COUNT(*) DESC
LIMIT 5;
```

**Expected**: Your uploaded document should appear with correct row count.

---

## ✅ Success Criteria

Your tests are successful if:

### ✅ Backend Tests
- [x] Service role test passes (`python test_service_role.py`)
- [x] Health check returns `{"status": "healthy"}`
- [x] Backend starts with service role key confirmation
- [x] No RLS errors in logs

### ✅ Upload Tests
- [x] File uploads successfully
- [x] Status changes: `uploaded` → `processing` → `completed`
- [x] Backend logs show: "Using service_role key for insert"
- [x] Backend logs show: "Total rows inserted successfully: [n]"
- [x] **NO RLS ERRORS** in backend logs

### ✅ Frontend Tests
- [x] Frontend loads on http://localhost:3000
- [x] Upload interface works (drag-and-drop and click)
- [x] Document appears in list after upload
- [x] Status indicators show correctly
- [x] "View Data" button works
- [x] Data table displays correctly
- [x] Search functionality works
- [x] Export (CSV/JSON) works

### ✅ Database Tests
- [x] Document appears in Supabase `documents` table
- [x] Extracted rows appear in `extracted_rows` table
- [x] Row counts match between frontend and database

---

## 🐛 Troubleshooting

### Problem: RLS Error Still Appearing

**Symptoms**:
```
row violates row-level security policy for table "documents"
```

**Solution 1**: Verify service role key
```bash
cd backend
python -c "from main import SUPABASE_SERVICE_ROLE_KEY; print(SUPABASE_SERVICE_ROLE_KEY[:30])"
# Should print: eyJhbGciOiJIUzI1NiIsInR5cCI6Ik
```

**Solution 2**: Restart backend
```bash
lsof -ti:8000 | xargs kill -9
cd backend && source venv/bin/activate && python main.py
```

**Solution 3**: Disable RLS temporarily (in Supabase SQL Editor)
```sql
ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_rows DISABLE ROW LEVEL SECURITY;
```

---

### Problem: Port Already in Use

**Symptoms**: Can't start backend/frontend

**Solution**:
```bash
# Kill all processes on ports 3000, 3001, 8000, 8001, 8002
lsof -ti:3000,3001,8000,8001,8002 | xargs kill -9

# Or kill specific port
kill -9 $(lsof -ti:8000)
```

---

### Problem: "Module Not Found" or Import Errors

**Symptoms**: Python can't find modules

**Solution**:
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

---

### Problem: Frontend Can't Connect to Backend

**Symptoms**: "Failed to fetch" or CORS error

**Solution 1**: Check `.env.local` exists
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
ls -la .env.local
cat .env.local
```

**Solution 2**: Verify backend is running
```bash
curl http://localhost:8000/health
```

**Solution 3**: Restart both frontend and backend

---

### Problem: File Upload Fails

**Symptoms**: Upload fails immediately or parsing fails

**Check**:
1. File format is supported (PDF, CSV, XLSX only)
2. File is not corrupted
3. File size is reasonable (< 50MB)
4. Backend logs for specific error message

---

## 📊 Test Files to Use

### Good Test Files:

1. **PDF**:
   - `Statement_All_Transactions_20250101_20250201.pdf` (in Tunnel folder)
   - Any bank statement with tables
   - Expected: 200-500 rows extracted

2. **CSV**:
   - `test-data/sample.csv` (in Tunnel folder)
   - Any CSV with headers
   - Expected: All rows extracted

3. **Excel**:
   - Any `.xlsx` file with data
   - Expected: All rows from first sheet

---

## 🎯 Quick Testing Checklist

Run through this 5-minute checklist:

```bash
# 1. Test service role (30 seconds)
cd backend && source venv/bin/activate && python test_service_role.py
# ✅ Should pass

# 2. Start backend (Terminal 1)
python main.py
# ✅ Should show service role key confirmation

# 3. Test health (Terminal 2)
curl http://localhost:8000/health
# ✅ Should return {"status": "healthy"}

# 4. Start frontend (Terminal 2)
cd .. && npm run dev
# ✅ Should start on http://localhost:3000

# 5. Upload file in browser
# ✅ Should show progress
# ✅ Should complete without errors
# ✅ Should show in document list

# 6. Check backend logs
# ✅ Should show "Using service_role key"
# ✅ Should show "Total rows inserted successfully"
# ✅ NO RLS ERRORS

# 7. Click "View Data"
# ✅ Should show extracted data
# ✅ Should allow search/sort
# ✅ Should allow export
```

**All checked** = 🎉 Everything working perfectly!

---

## 🚀 Alternative: Use Test Scripts

### Run All Tests Automatically:

```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate
bash RUN_TESTS.sh
```

### Start Simple Mode (Demo):

```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
chmod +x start-simple.sh
./start-simple.sh
```

---

## 📖 Additional Resources

For more detailed information:

1. **TESTING_GUIDE.md** - Comprehensive testing documentation
2. **FRONTEND_BACKEND_TESTING.md** - Integration testing details
3. **QUICK_START.md** - Quick setup guide
4. **README.md** - Project overview

---

## ✅ Final Verification

After all tests, verify:

1. ✅ Backend starts without errors
2. ✅ Frontend connects to backend
3. ✅ Files upload successfully
4. ✅ Data is parsed correctly
5. ✅ Data appears in Supabase
6. ✅ Frontend displays data
7. ✅ Export functions work
8. ✅ No RLS errors

**All verified** = 🎉 **Project is working correctly!**

---

**Happy Testing! 🚀**



