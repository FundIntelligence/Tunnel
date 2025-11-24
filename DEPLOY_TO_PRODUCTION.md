# 🚀 Production Deployment Guide
## Railway (Backend) + Vercel (Frontend) + Supabase

---

## 🎯 Overview

This guide will deploy:
- **Backend** → Railway (FastAPI + Python)
- **Frontend** → Vercel (Next.js)
- **Database** → Supabase (Already set up)

**Total time**: ~15 minutes

---

## 📋 Prerequisites

- [x] GitHub account
- [x] Railway account (sign up at https://railway.app)
- [x] Vercel account (sign up at https://vercel.com)
- [x] Supabase project already configured ✅

---

## 🚂 PART 1: Deploy Backend to Railway

### Step 1: Prepare Backend for Railway

#### 1.1 Create `railway.toml` (if not exists)
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
cat > railway.toml << 'EOF'
[build]
builder = "nixpacks"
buildCommand = "pip install -r requirements.txt"

[deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
EOF
```

#### 1.2 Verify `requirements.txt` exists
```bash
cat requirements.txt
```

Should include:
```
fastapi
uvicorn
python-dotenv
supabase
pdfplumber
pandas
openpyxl
python-multipart
httpx
```

### Step 2: Push to GitHub

```bash
cd /Users/mbakswatu/Desktop/Fintelligence
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### Step 3: Deploy to Railway

#### 3.1 Create New Project
1. Go to https://railway.app/dashboard
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Choose your repository: `Fintelligence`
5. Select root path: `/FundIQ/Tunnel/backend` (if Railway allows path selection)
   - If not, we'll configure this in settings

#### 3.2 Configure Environment Variables
In Railway dashboard → Your Project → Variables:

```bash
SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8
PORT=8000
```

**Important**: Railway auto-injects `$PORT`, so we set it to 8000 for consistency.

#### 3.3 Configure Build Settings
1. Go to **Settings** tab
2. Set **Root Directory**: `FundIQ/Tunnel/backend`
3. Set **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Click **Deploy**

#### 3.4 Get Your Railway URL
After deployment:
1. Go to **Settings** → **Domains**
2. Click **Generate Domain**
3. Copy the URL (e.g., `https://fundiq-backend-production.up.railway.app`)

### Step 4: Update CORS in `main.py`

```python
# In backend/main.py, update CORS origins:
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://your-vercel-app.vercel.app",  # Update after Vercel deployment
        "https://*.vercel.app",  # Allow all Vercel preview deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Push update:
```bash
git add backend/main.py
git commit -m "Update CORS for production"
git push origin main
```

Railway will auto-redeploy.

### Step 5: Test Railway Backend

```bash
# Test health check
curl https://your-railway-url.up.railway.app/health

# Expected response:
# {"status":"healthy","supabase":"connected","parsers":["pdf","csv","xlsx"]}
```

---

## ▲ PART 2: Deploy Frontend to Vercel

### Step 1: Prepare Frontend Environment Variables

Create a file to copy from:
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
cat > .env.production.example << 'EOF'
NEXT_PUBLIC_API_URL=https://your-railway-url.up.railway.app
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=https://your-railway-url.up.railway.app
EOF
```

**Replace** `your-railway-url.up.railway.app` with your actual Railway URL!

### Step 2: Deploy to Vercel

#### 2.1 Via Vercel Dashboard (Recommended)

1. Go to https://vercel.com/new
2. Import your GitHub repository
3. Configure project:
   - **Framework Preset**: Next.js
   - **Root Directory**: `FundIQ/Tunnel`
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`

#### 2.2 Add Environment Variables

In Vercel → Your Project → Settings → Environment Variables:

Add these for **Production** environment:

| Name | Value |
|------|-------|
| `NEXT_PUBLIC_API_URL` | `https://your-railway-url.up.railway.app` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://caajasgudqsqlztjqedc.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4` |
| `NEXT_PUBLIC_PARSER_API_URL` | `https://your-railway-url.up.railway.app` |

**Important**: Replace Railway URL with your actual backend URL!

#### 2.3 Deploy
1. Click **Deploy**
2. Wait for build to complete (~2-3 minutes)
3. Get your Vercel URL (e.g., `https://fundiq.vercel.app`)

### Step 3: Update Backend CORS with Vercel URL

```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
```

Update `main.py` CORS to include your Vercel URL:
```python
allow_origins=[
    "http://localhost:3000",
    "https://fundiq.vercel.app",  # Your actual Vercel URL
    "https://*.vercel.app",
],
```

Push:
```bash
git add backend/main.py
git commit -m "Add Vercel URL to CORS"
git push origin main
```

---

## 🧪 PART 3: Test Production Deployment

### Test 1: Backend Health Check

```bash
curl https://your-railway-url.up.railway.app/health
```

**Expected**:
```json
{
  "status": "healthy",
  "supabase": "connected",
  "parsers": ["pdf", "csv", "xlsx"]
}
```

✅ If you see this, backend is working!

### Test 2: Frontend Access

1. Open your Vercel URL: `https://your-vercel-app.vercel.app`
2. Should see FundIQ interface
3. Check browser console for errors

### Test 3: End-to-End Upload

1. **Upload a test file** (PDF, CSV, or XLSX)
2. **Watch for**:
   - Upload progress bar
   - Success message
   - Document appears in list
   - Status shows "completed"

### Test 4: Verify in Railway Logs

1. Go to Railway dashboard → Your project
2. Click **Deployments** → Latest deployment → **View Logs**
3. Should see:
   ```
   [DEBUG] Using Supabase Service Role Key: eyJhbG...
   [DEBUG] 📨 PARSE REQUEST RECEIVED
   [DEBUG] Starting document upload - storing rows
   [DEBUG] Insert successful
   [DEBUG] ✅ Upload complete!
   ```

### Test 5: Verify in Supabase

1. Go to Supabase dashboard
2. Table Editor → `documents` table
3. Should see your uploaded file
4. Check `extracted_rows` table for parsed data

---

## ✅ Success Checklist

### Backend (Railway)
- [ ] Railway project created
- [ ] Environment variables set (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
- [ ] Deployment successful
- [ ] Health check returns "healthy"
- [ ] Logs show service_role key being used

### Frontend (Vercel)
- [ ] Vercel project created
- [ ] Environment variables set (all 4 variables)
- [ ] Build successful
- [ ] Site accessible at Vercel URL
- [ ] No console errors

### Integration
- [ ] CORS updated with Vercel URL
- [ ] Upload test file successfully
- [ ] Data appears in Supabase
- [ ] No RLS errors in Railway logs
- [ ] Frontend displays extracted data

---

## 🔧 Troubleshooting

### Issue: Railway deployment fails

**Check**:
1. Logs in Railway dashboard
2. Verify `requirements.txt` has all dependencies
3. Ensure start command is correct: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Issue: Vercel build fails

**Check**:
1. Build logs in Vercel dashboard
2. Verify root directory is `FundIQ/Tunnel`
3. Check `package.json` has all dependencies
4. Run `npm run build` locally to test

### Issue: CORS errors in browser

**Symptoms**:
```
Access to fetch at 'https://railway...' from origin 'https://vercel...' 
has been blocked by CORS policy
```

**Fix**:
1. Update `backend/main.py` CORS origins
2. Add your Vercel URL to `allow_origins`
3. Push to GitHub
4. Railway will auto-redeploy

### Issue: "Failed to fetch" from frontend

**Check**:
1. Environment variables in Vercel
2. `NEXT_PUBLIC_API_URL` is correct Railway URL
3. Railway backend is running (check health endpoint)
4. No typos in URL

### Issue: RLS errors in Railway logs

**Fix**:
1. Verify service_role key is set in Railway env vars
2. Check Railway logs show: `[DEBUG] Using Supabase Service Role Key`
3. If not, redeploy with correct env var

---

## 📊 Monitoring & Logs

### Railway Logs
```bash
# View in dashboard or install Railway CLI
railway logs
```

### Vercel Logs
```bash
# View in dashboard or install Vercel CLI
vercel logs
```

### Supabase Logs
1. Go to Supabase dashboard
2. Logs section
3. Filter by table: `documents`, `extracted_rows`

---

## 🔄 Redeployment

### Backend Updates
```bash
git add backend/
git commit -m "Update backend"
git push origin main
# Railway auto-deploys
```

### Frontend Updates
```bash
git add FundIQ/Tunnel/
git commit -m "Update frontend"
git push origin main
# Vercel auto-deploys
```

### Force Redeploy
- **Railway**: Dashboard → Deployments → Redeploy
- **Vercel**: Dashboard → Deployments → Redeploy

---

## 🎉 You're Live!

Once all tests pass:

✅ **Backend**: Railway  
✅ **Frontend**: Vercel  
✅ **Database**: Supabase  

**Your production URLs**:
- Frontend: `https://your-app.vercel.app`
- Backend: `https://your-backend.up.railway.app`
- Database: `https://caajasgudqsqlztjqedc.supabase.co`

---

## 📝 Post-Deployment Tasks

### Optional Optimizations
1. **Custom domain**: Add to Vercel/Railway
2. **Remove debug logs**: Clean up `[DEBUG]` prints in production
3. **Error monitoring**: Add Sentry or LogRocket
4. **Analytics**: Add PostHog or Google Analytics
5. **Rate limiting**: Add API rate limits
6. **Caching**: Add Redis for performance

### Security Review
- [ ] Service role key only in Railway (never in frontend)
- [ ] Anon key in Vercel (safe for client-side)
- [ ] CORS restricted to your domain
- [ ] HTTPS enforced
- [ ] Environment variables secured

---

**🚀 Your FundIQ MVP is now live in production!**




