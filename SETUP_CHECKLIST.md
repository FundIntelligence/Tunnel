# ✅ FundIQ Setup & Testing Checklist

## 🎯 Quick Start Checklist

Use this checklist to verify your FundIQ setup is working correctly with the service_role key.

---

## 📋 Part 1: Initial Setup

### Backend Setup
- [ ] Navigate to backend directory: `cd FundIQ/Tunnel/backend`
- [ ] Virtual environment exists: `python3 -m venv venv` (if needed)
- [ ] Activate environment: `source venv/bin/activate`
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Verify service_role key in `main.py` (lines 42-46)

### Frontend Setup
- [ ] Navigate to project: `cd FundIQ/Tunnel`
- [ ] Install dependencies: `npm install`
- [ ] Environment configured (`.env.local` or hardcoded)

---

## 🧪 Part 2: Service Role Key Verification

### Run Automated Tests
```bash
cd backend
bash RUN_TESTS.sh
```

### Expected Results
- [ ] ✅ TEST 1: Supabase connection successful
- [ ] ✅ TEST 2: Document insert successful (RLS bypassed)
- [ ] ✅ TEST 3: Extracted rows insert successful (RLS bypassed)
- [ ] ✅ TEST 4: Document update successful (RLS bypassed)
- [ ] ✅ Cleanup successful

**If all tests pass, proceed to Part 3. Otherwise, see Troubleshooting section.**

---

## 🚀 Part 3: Supabase Mode Testing

### Step 1: Start Backend
```bash
cd backend
source venv/bin/activate
python main.py
```

#### Verify Startup Logs
- [ ] See: `✅ [DEBUG] Supabase client initialized with SERVICE_ROLE key`
- [ ] See: `✅ [DEBUG] Supabase URL: https://caajasgudqsqlztjqedc.supabase.co`
- [ ] See: `✅ [DEBUG] Service Role Key (first 20 chars): eyJhbGciOiJIUzI1NiIsI...`
- [ ] Backend running on `http://0.0.0.0:8000`

### Step 2: Start Frontend
```bash
# New terminal
cd FundIQ/Tunnel
npm run dev
```

- [ ] Frontend running on `http://localhost:3000`
- [ ] No errors in terminal

### Step 3: Upload Test File
1. [ ] Open http://localhost:3000 in browser
2. [ ] Upload a PDF, CSV, or XLSX file (< 50MB)
3. [ ] Watch backend terminal for debug logs

#### Verify Backend Logs
- [ ] See: `📨 [DEBUG] ===== PARSE REQUEST RECEIVED =====`
- [ ] See: `🚀 [DEBUG] ===== PROCESSING DOCUMENT =====`
- [ ] See: `📝 [DEBUG] Using service_role key for update (bypasses RLS)`
- [ ] See: `📥 [DEBUG] Using Supabase service_role key for insert (bypasses RLS)`
- [ ] See: `✅ [DEBUG] Total rows inserted successfully: [number]`
- [ ] See: `✅ Updated document [uuid] status to completed`
- [ ] **NO RLS ERRORS** ❌ "row violates row-level security policy"

#### Verify Frontend
- [ ] File appears in document list
- [ ] Status changes: `uploaded` → `processing` → `completed`
- [ ] Row count shows correct number
- [ ] Click "View Data" opens modal
- [ ] Data table displays correctly
- [ ] Search works
- [ ] CSV download works
- [ ] JSON download works

### Step 4: Verify in Supabase Dashboard
1. [ ] Go to https://supabase.com/dashboard
2. [ ] Select project: `caajasgudqsqlztjqedc`
3. [ ] Navigate to Table Editor
4. [ ] Check `documents` table - see uploaded file
5. [ ] Check `extracted_rows` table - see parsed data
6. [ ] Verify row counts match

---

## 🗃️ Part 4: SQLite Mode Testing (Optional)

### Step 1: Start SQLite Backend
```bash
cd backend
source venv/bin/activate
python simple_main.py
```

- [ ] Backend running on `http://127.0.0.1:8002`
- [ ] See: `✅ Database initialized successfully`

### Step 2: Access Demo Page
```bash
# New terminal (or use existing frontend)
cd FundIQ/Tunnel
PORT=3001 npm run dev
```

- [ ] Open http://localhost:3001/simple-page
- [ ] Demo interface loads

### Step 3: Test Upload
- [ ] Upload test file (PDF, CSV, or XLSX)
- [ ] File processes immediately
- [ ] Data appears in UI
- [ ] No Supabase calls made

### Step 4: Verify SQLite Database
```bash
cd backend
sqlite3 fundiq_demo.db
```

```sql
.tables
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM extracted_rows;
SELECT * FROM documents ORDER BY upload_date DESC LIMIT 1;
.quit
```

- [ ] Tables exist
- [ ] Data is stored correctly
- [ ] Row counts match upload

---

## 🎉 Part 5: Final Verification

### Supabase Mode ✅
- [ ] No RLS errors in any operation
- [ ] Documents insert successfully
- [ ] Extracted rows insert successfully
- [ ] Status updates work
- [ ] Data appears in Supabase dashboard
- [ ] Frontend displays all data correctly
- [ ] Export functions work

### SQLite Mode ✅
- [ ] Local database works
- [ ] No external dependencies
- [ ] All features functional
- [ ] Good for development/demo

---

## 🐛 Troubleshooting

### ❌ Issue: RLS Policy Violation

**Error**: `row violates row-level security policy for table "documents"`

**Solutions**:
1. Verify service_role key is correct:
   ```bash
   cd backend
   python -c "from main import SUPABASE_SERVICE_ROLE_KEY; print(SUPABASE_SERVICE_ROLE_KEY[:30])"
   # Should start with: eyJhbGciOiJIUzI1NiIsInR5cCI6Ik
   ```

2. Confirm backend is using the updated `main.py`:
   ```bash
   cd backend
   python -c "import main; print(main.__file__)"
   ```

3. Restart backend to reload configuration:
   ```bash
   # Kill existing process
   lsof -ti:8000 | xargs kill -9
   # Restart
   python main.py
   ```

4. Disable RLS temporarily (if all else fails):
   ```sql
   -- In Supabase SQL Editor
   ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
   ALTER TABLE extracted_rows DISABLE ROW LEVEL SECURITY;
   ```

### ❌ Issue: Connection Errors

**Error**: `Connection refused` or `Cannot connect to Supabase`

**Solutions**:
1. Check Supabase URL is correct: `https://caajasgudqsqlztjqedc.supabase.co`
2. Verify internet connection
3. Check Supabase service status: https://status.supabase.com

### ❌ Issue: Table Not Found

**Error**: `relation "documents" does not exist`

**Solution**: Create tables in Supabase
1. Go to Supabase SQL Editor
2. Copy contents of `supabase/schema.sql`
3. Execute the SQL
4. Verify tables created: Table Editor → documents, extracted_rows

### ❌ Issue: Port Already in Use

**Error**: `Address already in use` on port 8000/3000

**Solution**: Kill existing processes
```bash
# Kill all relevant ports
lsof -ti:3000,8000,8001,8002 | xargs kill -9

# Or specific port
kill -9 $(lsof -ti:8000)
```

### ❌ Issue: Import Errors

**Error**: `ModuleNotFoundError: No module named 'supabase'`

**Solution**: Reinstall dependencies
```bash
cd backend
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

---

## 📊 Service Role Key Details

### Current Configuration
- **URL**: `https://caajasgudqsqlztjqedc.supabase.co`
- **Service Role Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8`
- **Location**: Hardcoded in `backend/main.py` (lines 42-46)
- **Purpose**: Bypasses Row Level Security for backend operations

### Why Service Role Key?
- **Anon Key**: Limited by RLS policies (frontend safe)
- **Service Role Key**: Full access, bypasses RLS (backend only)
- **Use Case**: Backend inserts data on behalf of users

### Security Notes
- ⚠️ Never expose service_role key in frontend
- ✅ Only use in backend code
- ✅ Store in environment variables for production
- ✅ Add `.env` to `.gitignore`

---

## 📈 Success Metrics

You've successfully completed setup when:

### ✅ All Tests Pass
```bash
cd backend
bash RUN_TESTS.sh
# Output: 🎉 ALL TESTS PASSED!
```

### ✅ Upload Works End-to-End
1. Upload file → No errors
2. Backend logs show service_role usage
3. Data appears in Supabase
4. Frontend displays results
5. Export functions work

### ✅ No RLS Errors
- Console shows: `✅ [DEBUG] Using service_role key`
- No errors: `❌ row violates row-level security policy`
- Smooth insert/update operations

---

## 🚀 Next Steps After Verification

1. **Remove Debug Logs** (Optional)
   - Edit `main.py`
   - Remove lines with `[DEBUG]`
   - Keep essential logging

2. **Move to Environment Variables** (Production)
   - Create `backend/.env` file
   - Remove hardcoded keys from `main.py`
   - Use only `os.getenv()` without fallbacks

3. **Deploy to Production**
   - Frontend → Vercel
   - Backend → Railway/Render
   - Configure environment variables in platform
   - Update CORS settings with production URLs

4. **Enable RLS with Proper Policies** (Optional)
   ```sql
   -- In Supabase SQL Editor
   ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
   ALTER TABLE extracted_rows ENABLE ROW LEVEL SECURITY;
   
   -- Service role bypasses these automatically
   CREATE POLICY "Service role full access" ON documents
   TO service_role USING (true);
   ```

---

## 📝 Summary

**What We Fixed**:
- ✅ Service role key properly configured
- ✅ RLS bypass working correctly
- ✅ Debug logging added for verification
- ✅ Test script created for validation
- ✅ Both Supabase and SQLite modes functional

**What We Tested**:
- ✅ Supabase connection
- ✅ Document insert (bypasses RLS)
- ✅ Extracted rows insert (bypasses RLS)
- ✅ Document update (bypasses RLS)
- ✅ End-to-end upload workflow
- ✅ SQLite fallback mode

**What Works Now**:
- ✅ Upload files without RLS errors
- ✅ Parse documents successfully
- ✅ Store data in Supabase
- ✅ View and export data in frontend
- ✅ Demo mode with local SQLite

---

**🎉 Setup Complete! Happy coding!** 🚀


