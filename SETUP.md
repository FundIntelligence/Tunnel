# FundIQ MVP - Complete Setup Guide

This guide will walk you through setting up the complete FundIQ MVP from scratch.

## Prerequisites

Before you begin, make sure you have:
- **Node.js 18+** installed
- **Python 3.9+** installed
- **A Supabase account** (free tier works fine)
- **Git** (optional, for version control)

---

## Step 1: Supabase Setup

### 1.1 Create a Supabase Project

1. Go to [https://supabase.com](https://supabase.com)
2. Sign up or log in
3. Click "New Project"
4. Fill in the details:
   - **Name**: FundIQ MVP
   - **Database Password**: (save this securely)
   - **Region**: Choose closest to you
5. Wait for the project to initialize (~2 minutes)

### 1.2 Get Your API Credentials

1. In your Supabase dashboard, go to **Settings** → **API**
2. Copy the following values (you'll need them later):
   - **Project URL** (looks like: `https://xxxxx.supabase.co`)
   - **anon public** key (under "Project API keys")
   - **service_role** key (under "Project API keys" - keep this secret!)

### 1.3 Set Up the Database Schema

1. In your Supabase dashboard, go to **SQL Editor**
2. Click "New Query"
3. Copy the entire contents of `/supabase/schema.sql`
4. Paste it into the SQL editor
5. Click "Run" or press Cmd/Ctrl + Enter
6. You should see "Success. No rows returned" (this is normal!)

### 1.4 Create Storage Bucket

1. In your Supabase dashboard, go to **Storage**
2. Click "New Bucket"
3. Name it: `uploads`
4. **Public bucket**: Leave UNCHECKED (private)
5. Click "Create bucket"

---

## Step 2: Frontend Setup

### 2.1 Install Dependencies

```bash
# Navigate to the FundIQ directory
cd FundIQ

# Install Node dependencies
npm install
```

### 2.2 Configure Environment Variables

Create a `.env.local` file in the `FundIQ` directory:

```bash
# Create the file
touch .env.local
```

Add the following content (replace with your actual Supabase credentials):

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
```

**Important:** Replace the placeholder values with your actual Supabase credentials from Step 1.2!

---

## Step 3: Backend Setup

### 3.1 Install Python Dependencies

```bash
# Navigate to the backend directory
cd backend

# Create a virtual environment (recommended)
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3.2 Configure Backend Environment

Create a `.env` file in the `backend` directory:

```bash
# While in the backend directory
touch .env
```

Add the following content:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here
```

**Important:** Use the **service_role** key here (NOT the anon key)!

---

## Step 4: Run the Application

You'll need **two terminal windows** - one for frontend, one for backend.

### Terminal 1: Start the Backend

```bash
cd backend

# Make sure virtual environment is activated
source venv/bin/activate

# Start the FastAPI server
uvicorn main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Test it by visiting: http://localhost:8000/health

### Terminal 2: Start the Frontend

```bash
# From the FundIQ directory
npm run dev
```

You should see:
```
- ready started server on 0.0.0.0:3000, url: http://localhost:3000
```

---

## Step 5: Test the Application

1. Open your browser and go to: **http://localhost:3000**
2. You should see the FundIQ interface with:
   - Upload area on the left
   - Document list on the right
   - "How It Works" section at the bottom

### Upload a Test File

**For CSV Test:**
1. Create a simple CSV file named `test.csv`:
```csv
Date,Description,Amount,Category
2024-01-01,Office Supplies,250.00,Expense
2024-01-05,Client Payment,5000.00,Revenue
2024-01-10,Software License,99.00,Expense
```

**For PDF Test:**
- Use any PDF with tables or text

**For Excel Test:**
- Use any .xlsx file with data

### Upload Process:
1. Drag and drop your file or click to select
2. Watch the upload progress indicator
3. The document will appear in the right panel
4. Once status shows "Completed", click the eye icon to view data
5. In the data view, you can:
   - Search/filter data
   - Sort by columns
   - Download as CSV or JSON

---

## Step 6: Verify Everything Works

### Check the Database

1. Go to your Supabase dashboard
2. Navigate to **Table Editor**
3. You should see two tables:
   - `documents` - should have 1 row (your uploaded file)
   - `extracted_rows` - should have multiple rows (extracted data)

### Check Storage

1. Go to **Storage** → **uploads**
2. You should see your uploaded file

---

## Troubleshooting

### Frontend won't start
- Make sure you're in the right directory
- Check that `node_modules` exists (run `npm install` if not)
- Verify `.env.local` file exists with correct values

### Backend won't start
- Make sure Python virtual environment is activated
- Check all dependencies installed: `pip list`
- Verify `.env` file exists in backend directory
- Try: `python -m uvicorn main:app --reload`

### Upload fails
- Check backend is running (http://localhost:8000/health)
- Check browser console for errors (F12)
- Verify Supabase credentials are correct
- Check storage bucket is created and named `uploads`

### Parsing fails
- Check backend logs in terminal
- Verify file format is supported (PDF, CSV, XLSX)
- Check file isn't corrupted
- Look at error message in the document list

### "Missing Supabase credentials" error
- Double-check `.env.local` (frontend) has `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- Double-check `.env` (backend) has `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- Make sure there are no typos in the variable names
- Restart both frontend and backend after adding credentials

### RLS (Row Level Security) errors
- Make sure you ran the complete schema.sql file
- The demo uses `user_id = 'demo-user-123'` - this is hardcoded for now
- In production, you'd integrate real authentication

---

## Next Steps

Once everything is working:

1. **Add Authentication**: Integrate Supabase Auth to replace the hardcoded user ID
2. **Deploy Frontend**: Deploy to Vercel, Netlify, or similar
3. **Deploy Backend**: Deploy to Railway, Render, or AWS Lambda
4. **Custom Domain**: Set up your own domain
5. **Add Features**: Implement the stretch goals like OCR, rules engine, etc.

---

## Production Deployment Tips

### Frontend (Vercel - Recommended)
1. Push code to GitHub
2. Import project in Vercel
3. Add environment variables in Vercel dashboard
4. Deploy!

### Backend (Railway - Recommended)
1. Create `Procfile`: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
2. Push to GitHub
3. Import project in Railway
4. Add environment variables
5. Deploy!
6. Update `NEXT_PUBLIC_PARSER_API_URL` in frontend to use Railway URL

### Database
- Supabase handles this - no action needed!
- Consider upgrading to paid plan for production

---

## Support

If you encounter issues:
1. Check the browser console (F12) for frontend errors
2. Check the terminal for backend errors
3. Check Supabase logs in the dashboard
4. Review this guide again carefully

Happy coding! 🚀


