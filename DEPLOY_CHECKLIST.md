# 🚀 Quick Deployment Checklist

## ⚡ Railway Backend Deployment

### Pre-Deployment
- [ ] Kill all local processes: `lsof -ti:3000,8000 | xargs kill -9`
- [ ] Commit all changes: `git add . && git commit -m "Ready for production"`
- [ ] Push to GitHub: `git push origin main`

### Railway Setup (5 minutes)
1. [ ] Go to https://railway.app/dashboard
2. [ ] Click **"New Project"** → **"Deploy from GitHub repo"**
3. [ ] Select repository: `Fintelligence`
4. [ ] Configure:
   - **Root Directory**: `FundIQ/Tunnel/backend`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

5. [ ] Add Environment Variables:
   ```
   SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8
   ```

6. [ ] Click **Deploy**
7. [ ] Generate Domain (Settings → Domains)
8. [ ] Copy Railway URL: `_______________________________`

### Test Backend
```bash
curl https://YOUR-RAILWAY-URL.up.railway.app/health
```
Expected: `{"status":"healthy","supabase":"connected"}`

---

## ▲ Vercel Frontend Deployment

### Pre-Deployment
- [ ] Have Railway URL ready from above

### Vercel Setup (5 minutes)
1. [ ] Go to https://vercel.com/new
2. [ ] Import GitHub repository
3. [ ] Configure:
   - **Framework**: Next.js
   - **Root Directory**: `FundIQ/Tunnel`
   - **Build Command**: `npm run build`

4. [ ] Add Environment Variables (Production):
   ```
   NEXT_PUBLIC_API_URL=https://YOUR-RAILWAY-URL.up.railway.app
   NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
   NEXT_PUBLIC_PARSER_API_URL=https://YOUR-RAILWAY-URL.up.railway.app
   ```

5. [ ] Click **Deploy**
6. [ ] Copy Vercel URL: `_______________________________`

---

## 🔧 CORS Update (Critical!)

### Update backend/main.py
```python
allow_origins=[
    "https://YOUR-VERCEL-URL.vercel.app",
    "https://*.vercel.app",
],
```

### Deploy
```bash
git add backend/main.py
git commit -m "Update CORS for production"
git push origin main
```
Railway will auto-redeploy.

---

## ✅ Final Testing

### 1. Backend Health
```bash
curl https://YOUR-RAILWAY-URL.up.railway.app/health
```
- [ ] Returns `{"status":"healthy"}`

### 2. Frontend Access
- [ ] Open: `https://YOUR-VERCEL-URL.vercel.app`
- [ ] Page loads without errors
- [ ] Check browser console (no CORS errors)

### 3. Upload Test
- [ ] Upload a PDF/CSV/XLSX file
- [ ] File processes successfully
- [ ] Data appears in list
- [ ] Status shows "completed"
- [ ] Can view extracted data
- [ ] Can export CSV/JSON

### 4. Verify in Railway Logs
- [ ] Railway Dashboard → Deployments → View Logs
- [ ] See: `[DEBUG] Using Supabase Service Role Key`
- [ ] See: `[DEBUG] ✅ Upload complete!`
- [ ] **NO RLS ERRORS**

### 5. Verify in Supabase
- [ ] Supabase Dashboard → Table Editor
- [ ] New row in `documents` table
- [ ] Rows in `extracted_rows` table

---

## 🎉 Production URLs

**Record your URLs here:**

| Service | URL |
|---------|-----|
| Frontend (Vercel) | `https://_________________________.vercel.app` |
| Backend (Railway) | `https://_________________________.up.railway.app` |
| Database (Supabase) | `https://caajasgudqsqlztjqedc.supabase.co` |

---

## 🐛 Quick Fixes

### CORS Error
```bash
# Add Vercel URL to backend/main.py CORS
# Then:
git add . && git commit -m "Fix CORS" && git push
```

### Railway Not Responding
- Check Railway logs for errors
- Verify environment variables are set
- Redeploy: Railway Dashboard → Redeploy

### Vercel Build Failed
- Check build logs in Vercel
- Verify environment variables
- Try: Vercel Dashboard → Redeploy

---

## ⏱️ Total Time: ~15 minutes

1. ✅ Railway deployment: 5 min
2. ✅ Vercel deployment: 5 min  
3. ✅ CORS update: 2 min
4. ✅ Testing: 3 min

**Status**: Production Ready! 🚀




