#!/usr/bin/env python3
"""
Simple FundIQ Backend with SQLite (no Supabase needed)
This version uses local SQLite database - much simpler!
"""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import json
import os
import asyncio
from typing import List, Dict, Any
import pandas as pd
import pdfplumber
import io

# Initialize FastAPI
app = FastAPI(
    title="FundIQ Parser API",
    description="Parse financial documents and extract structured data",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLite database setup
DB_PATH = "fundiq_demo.db"

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            file_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_url TEXT,
            format_detected TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'uploaded',
            rows_count INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)
    
    # Create extracted_rows table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS extracted_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            row_index INTEGER NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id) REFERENCES documents (id)
        )
    """)
    
    conn.commit()
    conn.close()

# Initialize database on startup
try:
    init_db()
    print("✅ Database initialized successfully")
except Exception as e:
    print(f"❌ Database initialization failed: {e}")
    import traceback
    traceback.print_exc()

# Pydantic models
class ParseRequest(BaseModel):
    document_id: int
    file_content: bytes
    file_type: str

class ParseResponse(BaseModel):
    success: bool
    rows_extracted: int
    error: str = None

# Parser functions
def parse_csv(file_content: bytes) -> List[Dict[str, Any]]:
    """Parse CSV content"""
    try:
        df = pd.read_csv(io.BytesIO(file_content))
        return df.to_dict('records')
    except Exception as e:
        raise ValueError(f"CSV parsing failed: {e}")

def parse_excel(file_content: bytes) -> List[Dict[str, Any]]:
    """Parse Excel content"""
    try:
        df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
        return df.to_dict('records')
    except Exception as e:
        raise ValueError(f"Excel parsing failed: {e}")

def parse_pdf(file_content: bytes) -> List[Dict[str, Any]]:
    """Parse PDF content"""
    try:
        all_rows = []
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                if tables:
                    for table_num, table in enumerate(tables, start=1):
                        if len(table) > 1:
                            headers = [str(h).strip() if h else f"Column_{i}" for i, h in enumerate(table[0])]
                            for row_data in table[1:]:
                                if row_data and any(cell for cell in row_data):
                                    row_dict = {'page': page_num, 'table': table_num}
                                    for i, cell in enumerate(row_data):
                                        if i < len(headers):
                                            row_dict[headers[i]] = str(cell).strip() if cell else ''
                                    all_rows.append(row_dict)
        return all_rows
    except Exception as e:
        raise ValueError(f"PDF parsing failed: {e}")

# API endpoints
@app.get("/")
async def root():
    return {
        "service": "FundIQ Parser API (SQLite)",
        "status": "running",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "sqlite",
        "parsers": ["pdf", "csv", "xlsx"]
    }

@app.post("/test-upload")
async def test_upload(file: UploadFile = File(...)):
    """Test endpoint for file upload"""
    try:
        content = await file.read()
        return {
            "success": True,
            "filename": file.filename,
            "size": len(content),
            "content_type": file.content_type
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/parse", response_model=ParseResponse)
async def parse_document(file: UploadFile = File(...)):
    """Parse a document and extract structured data"""
    document_id = None
    try:
        print(f"🔍 Received file: {file.filename}, size: {file.size}")
        # Read file content
        file_content = await file.read()
        
        # Determine file type
        file_type = file.filename.split('.')[-1].lower()
        if file_type not in ['pdf', 'csv', 'xlsx']:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        # Create document record
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO documents (user_id, file_name, file_type, status)
            VALUES (?, ?, ?, ?)
        """, ('demo-user', file.filename, file_type, 'processing'))
        
        document_id = cursor.lastrowid
        conn.commit()
        
        # Parse the file
        if file_type == 'csv':
            rows = parse_csv(file_content)
        elif file_type == 'xlsx':
            rows = parse_excel(file_content)
        elif file_type == 'pdf':
            rows = parse_pdf(file_content)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        # Store extracted rows
        for idx, row_data in enumerate(rows):
            cursor.execute("""
                INSERT INTO extracted_rows (document_id, row_index, raw_json)
                VALUES (?, ?, ?)
            """, (document_id, idx, json.dumps(row_data)))
        
        # Update document status to completed
        cursor.execute("""
            UPDATE documents 
            SET status = 'completed', rows_count = ?
            WHERE id = ?
        """, (len(rows), document_id))
        
        conn.commit()
        conn.close()
        
        return ParseResponse(
            success=True,
            rows_extracted=len(rows)
        )
        
    except Exception as e:
        # Update document status to failed if document was created
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documents 
                SET status = 'failed', error_message = ?
                WHERE id = ?
            """, (str(e), document_id))
            conn.commit()
            conn.close()
        except:
            pass
        
        # Log the error for debugging
        print(f"❌ Error in parse_document: {e}")
        import traceback
        traceback.print_exc()
        
        return ParseResponse(
            success=False,
            rows_extracted=0,
            error=str(e)
        )

@app.get("/documents")
async def get_documents():
    """Get all documents"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, file_name, file_type, upload_date, status, rows_count, error_message
        FROM documents 
        ORDER BY upload_date DESC
    """)
    
    documents = []
    for row in cursor.fetchall():
        documents.append({
            "id": row[0],
            "user_id": row[1],
            "file_name": row[2],
            "file_type": row[3],
            "upload_date": row[4],
            "status": row[5],
            "rows_count": row[6],
            "error_message": row[7]
        })
    
    conn.close()
    return documents

@app.get("/documents/{document_id}/rows")
async def get_document_rows(document_id: int):
    """Get extracted rows for a document"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT row_index, raw_json
        FROM extracted_rows 
        WHERE document_id = ?
        ORDER BY row_index
    """, (document_id,))
    
    rows = []
    for row in cursor.fetchall():
        rows.append({
            "row_index": row[0],
            "raw_json": json.loads(row[1])
        })
    
    conn.close()
    return rows

@app.delete("/documents/{document_id}")
async def delete_document(document_id: int):
    """Delete a document and its rows"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Delete extracted rows first (foreign key constraint)
    cursor.execute("DELETE FROM extracted_rows WHERE document_id = ?", (document_id,))
    
    # Delete document
    cursor.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    
    conn.commit()
    conn.close()
    
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
