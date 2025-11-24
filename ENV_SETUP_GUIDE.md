# 🔧 Environment Variables Setup Guide

## 📋 Frontend Configuration (.env.local)

Create `.env.local` in the `FundIQ/Tunnel` directory:

```bash
# Copy and paste this into .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
```

### Quick Setup
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
EOF
```

---

## 🚀 Production Configuration (Vercel)

### Option 1: Vercel Dashboard
1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add these for **Production** environment:

```
NEXT_PUBLIC_API_URL=https://fundiq-api.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=https://fundiq-api.onrender.com
```

3. **Important**: Update `https://fundiq-api.onrender.com` with your actual backend URL

### Option 2: Vercel CLI
```bash
vercel env add NEXT_PUBLIC_API_URL production
# Enter: https://your-backend-url.onrender.com

vercel env add NEXT_PUBLIC_SUPABASE_URL production
# Enter: https://caajasgudqsqlztjqedc.supabase.co

vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
# Enter: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

vercel env add NEXT_PUBLIC_PARSER_API_URL production
# Enter: https://your-backend-url.onrender.com
```

---

## 🐍 Backend Configuration

Already configured in `backend/main.py` with hardcoded fallbacks.

### Optional: Create backend/.env
```bash
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
cat > .env << 'EOF'
SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8
EOF
```

---

## 🌐 Backend Deployment (Render/Railway)

### Render Setup
1. Create new Web Service
2. Connect your GitHub repo
3. Set root directory: `backend`
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variables:
   ```
   SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8
   ```

### Railway Setup
1. Create new project
2. Connect GitHub repo
3. Set root directory: `backend`
4. Add environment variables (same as Render)
5. Railway auto-detects Python and runs

### Update CORS for Production
In `backend/main.py`, update CORS origins:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://your-vercel-app.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## ✅ Verification

### Local Development
```bash
# Check .env.local exists
ls -la /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local

# Verify content
cat /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local
```

### Test Frontend Connection
```bash
# Start backend
cd backend && source venv/bin/activate && python main.py

# Start frontend (new terminal)
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
npm run dev

# Open http://localhost:3000
```

### Production
- Backend health check: `curl https://your-backend.onrender.com/health`
- Frontend deployed: Check Vercel dashboard
- Environment variables set: Verify in Vercel settings

---

## 🔑 Key Points

### Frontend (.env.local)
- ✅ Uses `NEXT_PUBLIC_` prefix (exposed to browser)
- ✅ Uses **anon key** (safe for client-side)
- ✅ Points to backend API

### Backend (main.py or .env)
- ✅ Uses **service_role key** (server-side only)
- ✅ Bypasses RLS for inserts
- ✅ Never exposed to frontend

### Security
- ⚠️ Never commit `.env` files to Git
- ⚠️ Never use service_role key in frontend
- ✅ Use anon key in frontend (limited permissions)
- ✅ Use service_role key in backend (full access)

---

## 📝 Quick Commands

```bash
# Create frontend .env.local
cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000' > .env.local

# Verify
cat .env.local

# Test
npm run dev
```

---

**Ready to go!** 🚀




