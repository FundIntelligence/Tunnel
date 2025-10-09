# FundIQ Backend Parser

Python FastAPI backend for parsing PDF, CSV, and Excel files.

## Features

- PDF parsing with table extraction (pdfplumber)
- CSV parsing with multiple encoding support (pandas)
- Excel parsing with multi-sheet support (pandas + openpyxl)
- Automatic data storage in Supabase
- Async processing for large files
- RESTful API endpoints

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the `backend` directory:

```env
SUPABASE_URL=your-supabase-url
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

### 3. Run the Server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

### `GET /`
Health check endpoint

**Response:**
```json
{
  "service": "FundIQ Parser API",
  "status": "running",
  "version": "1.0.0"
}
```

### `GET /health`
Detailed health check with Supabase connection status

**Response:**
```json
{
  "status": "healthy",
  "supabase": "connected",
  "parsers": ["pdf", "csv", "xlsx"]
}
```

### `POST /parse`
Parse a document and extract data

**Request Body:**
```json
{
  "document_id": "uuid",
  "file_url": "https://...",
  "file_type": "pdf"
}
```

**Response:**
```json
{
  "success": true,
  "rows_extracted": 150
}
```

### `GET /document/{document_id}`
Get document information

### `GET /document/{document_id}/rows`
Get extracted rows for a document

**Query Parameters:**
- `limit`: Number of rows to return (default: 100)
- `offset`: Offset for pagination (default: 0)

## Parsers

### PDF Parser
- Extracts tables using pdfplumber
- Falls back to text extraction if no tables found
- Preserves page and table numbers
- Handles multi-page documents

### CSV Parser
- Supports multiple encodings (UTF-8, Latin-1, etc.)
- Handles different delimiters
- Cleans and normalizes column names

### Excel Parser
- Supports .xlsx and .xls formats
- Can parse specific sheets or default to first sheet
- Preserves sheet names in data
- Handles multiple sheets

## Error Handling

All errors are logged and returned to the client with appropriate HTTP status codes.
Document status is updated to 'failed' in the database if parsing fails.

## Development

### Run Tests
```bash
pytest
```

### Code Formatting
```bash
black .
```

### Type Checking
```bash
mypy .
```


