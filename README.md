# FundIQ MVP - File Upload & Extraction Module

A financial intelligence platform for investment teams that allows document upload, automatic data extraction, and data management.

## Features

- 📤 Upload documents (PDF, CSV, Excel)
- 🔍 Automatic data extraction from uploaded files
- 💾 Store structured data in Supabase
- 📊 Review and validate extracted data
- ⬇️ Download extracted data for comparison

## Tech Stack

- **Frontend**: Next.js 14 + React + TypeScript + Tailwind CSS
- **Backend**: Supabase (PostgreSQL + Storage)
- **Parser**: Python (FastAPI + pdfplumber + pandas)
- **Storage**: Supabase Storage

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.9+
- Supabase account

### Setup

1. **Install Frontend Dependencies**
```bash
npm install
```

2. **Install Python Dependencies**
```bash
cd backend
pip install -r requirements.txt
```

3. **Configure Environment Variables**

Copy `.env.local.example` to `.env.local` and fill in your Supabase credentials:
```bash
cp .env.local.example .env.local
```

4. **Set up Supabase Database**

Run the SQL schema in your Supabase SQL editor:
```bash
# Execute the file: supabase/schema.sql
```

5. **Create Supabase Storage Bucket**

In your Supabase dashboard:
- Go to Storage
- Create a new bucket named `uploads`
- Set it to private (or public based on your needs)

### Run the Application

1. **Start the Frontend**
```bash
npm run dev
```

2. **Start the Python Backend**
```bash
cd backend
uvicorn main:app --reload
```

The frontend will be available at `http://localhost:3000`
The backend API will be available at `http://localhost:8000`

## Project Structure

```
FundIQ/
├── app/                    # Next.js app directory
│   ├── page.tsx           # Home page
│   └── globals.css        # Global styles
├── components/            # React components
│   ├── FileUpload.tsx    # File upload component
│   ├── DataReview.tsx    # Data review table
│   └── DocumentList.tsx  # Document list
├── lib/                   # Utility libraries
│   └── supabase.ts       # Supabase client
├── backend/              # Python backend
│   ├── main.py          # FastAPI server
│   ├── parsers.py       # File parsing logic
│   └── requirements.txt # Python dependencies
└── supabase/            # Database schema
    └── schema.sql       # Database tables
```

## API Endpoints

### Backend Parser API

- `POST /parse` - Parse an uploaded document
  - Body: `{ "document_id": "uuid", "file_url": "url" }`
  - Returns: `{ "success": true, "rows_extracted": 42 }`

## Database Schema

### documents
- `id` (uuid, primary key)
- `user_id` (uuid)
- `file_name` (text)
- `file_type` (text)
- `format_detected` (text)
- `upload_date` (timestamp)
- `status` (text)

### extracted_rows
- `id` (uuid, primary key)
- `document_id` (uuid, foreign key)
- `row_index` (int)
- `raw_json` (jsonb)

## License

MIT


