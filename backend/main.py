"""
FundIQ Backend Parser API
FastAPI server for parsing PDF, CSV, and XLSX files with anomaly detection
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import os
import time
import uuid
import json
import datetime
from dotenv import load_dotenv
from parsers import get_parser

# Import new modules
from local_storage import get_storage, StorageInterface, SQLiteStorage
from anomaly_engine import AnomalyDetector
from notes_manager import NotesManager
from insight_generator import InsightGenerator
from debug_logger import debug_logger
from report_generator import ReportGenerator

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="FundIQ Parser API",
    description="Parse financial documents and extract structured data with anomaly detection",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage (Supabase or SQLite fallback)
storage: StorageInterface = get_storage()
logger.info(f"✅ Storage initialized: {type(storage).__name__}")

# Initialize anomaly detector
anomaly_detector = AnomalyDetector()

# Initialize notes manager
notes_manager = NotesManager()

# Initialize insight generator
insight_generator = InsightGenerator()

# Initialize report generator
report_generator = ReportGenerator()

# Pydantic models
class ParseRequest(BaseModel):
    document_id: str = Field(..., description="Document ID from database")
    file_url: str = Field(..., description="URL of the file to parse")
    file_type: str = Field(..., description="File type: pdf, csv, or xlsx")


class ParseResponse(BaseModel):
    success: bool
    rows_extracted: int
    anomalies_count: int = 0
    insights_summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class NoteCreate(BaseModel):
    content: str = Field(..., description="Note content")
    author: str = Field(default="system", description="Note author")


class AnalyzeRequest(BaseModel):
    document_id: str = Field(..., description="Document ID to analyze")


# Helper functions
async def process_document(document_id: str, file_url: str, file_type: str):
    """Process a document: parse, store data, detect anomalies, generate insights"""
    parse_start_time = time.time()
    
    try:
        debug_logger.log_parse_start(document_id, file_type)
        logger.info(f"Processing document {document_id} ({file_type})")
        
        # Update status to processing
        storage.update_document_status(document_id, 'processing')
        
        # Get appropriate parser
        parser = get_parser(file_type)
        
        # Parse the file
        rows = await parser.parse(file_url)
        
        if not rows:
            logger.warning(f"No data extracted from document {document_id}")
            storage.update_document_status(
                document_id,
                'completed',
                rows_count=0,
                error_message='No data found in document'
            )
            return 0, [], None
        
        # Store extracted rows
        rows_inserted = storage.store_rows(document_id, rows)
        parse_time = time.time() - parse_start_time
        debug_logger.log_parse_complete(document_id, rows_inserted, parse_time)
        
        # Run anomaly detection
        detection_start_time = time.time()
        anomalies = anomaly_detector.detect_all(rows)
        detection_time = time.time() - detection_start_time
        
        # Log individual anomalies
        for anomaly in anomalies:
            debug_logger.log_anomaly(
                anomaly.get('anomaly_type'),
                anomaly.get('severity'),
                anomaly.get('description'),
                anomaly.get('row_index', -1)
            )
        
        # Store anomalies
        anomalies_count = 0
        if anomalies:
            anomalies_count = storage.store_anomalies(document_id, anomalies)
        
        debug_logger.log_anomaly_detection(document_id, anomalies_count, detection_time)
        
        # Generate insights
        insights = insight_generator.generate_insights(anomalies)
        debug_logger.log_insight_generation(document_id, len(insights.get('insights', [])))
        
        # Update document status with anomalies and insights
        storage.update_document_status(
            document_id,
            'completed',
            rows_count=rows_inserted,
            anomalies_count=anomalies_count,
            insights_summary=insights
        )
        
        logger.info(f"Successfully processed document {document_id}: {rows_inserted} rows, {anomalies_count} anomalies")
        return rows_inserted, anomalies, insights
        
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        debug_logger.log_error("PROCESS", e, {"document_id": document_id, "file_type": file_type})
        # Update document status to failed
        storage.update_document_status(
            document_id,
            'failed',
            error_message=str(e)
        )
        raise


# API Routes
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "FundIQ Parser API",
        "status": "running",
        "version": "2.0.0",
        "storage": type(storage).__name__
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Test storage connection
        test_doc = storage.get_document("test-non-existent-id")
        storage_status = "connected"
    except Exception as e:
        logger.error(f"Storage health check failed: {e}")
        storage_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "storage": storage_status,
        "storage_type": type(storage).__name__,
        "parsers": ["pdf", "csv", "xlsx"]
    }


@app.post("/parse")
async def parse_document(
    request: Optional[ParseRequest] = None,
    file: Optional[UploadFile] = File(None)
):
    """
    Parse a document and extract structured data with anomaly detection
    
    This endpoint supports two modes:
    1. Direct file upload (local-first): POST with multipart/form-data file
    2. Supabase mode: POST with JSON containing document_id, file_url, file_type
    """
    document_id = None  # Track document ID for error handling
    try:
        # Check if direct file upload (local-first mode)
        if file:
            logger.info(f"📨 Direct file upload: {file.filename}")
            debug_logger.log_upload(file.filename, file.filename.split('.')[-1], file.size, "new")
            
            # Read file content
            file_content = await file.read()
            file_type = file.filename.split('.')[-1].lower()
            
            if file_type not in ['pdf', 'csv', 'xlsx']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_type}"
                )
            
            # Create document record
            document_id = str(uuid.uuid4())
            document_data = {
                'id': document_id,
                'user_id': 'demo-user',
                'file_name': file.filename,
                'file_type': file_type,
                'file_url': None,
                'status': 'processing'
            }
            storage.store_document(document_data)
            
            # Save file temporarily (or process directly)
            # For now, process directly from memory
            parser = get_parser(file_type)
            
            # Create a temporary URL for the parser (parsers expect URL)
            # For local mode, we'll pass file content directly
            import io
            import httpx
            
            # Parse directly from bytes
            if file_type == 'csv':
                import pandas as pd
                
                # Try automatic encoding detection first (optional, falls back if chardet not available)
                encodings = []
                try:
                    import chardet
                    detected = chardet.detect(file_content[:10000])  # Check first 10KB
                    detected_encoding = detected.get('encoding', 'utf-8')
                    confidence = detected.get('confidence', 0)
                    
                    logger.info(f"Detected encoding: {detected_encoding} (confidence: {confidence:.2f})")
                    
                    # If confidence is high, try detected encoding first
                    if confidence > 0.7 and detected_encoding:
                        encodings.append(detected_encoding)
                except ImportError:
                    logger.info("chardet not available, using fallback encodings")
                except Exception as e:
                    logger.warning(f"Encoding detection failed: {e}")
                
                # Add common encodings as fallbacks
                encodings.extend([
                    'utf-8', 'utf-8-sig',  # UTF-8 with/without BOM
                    'latin-1', 'iso-8859-1', 'cp1252',  # Western European
                    'utf-16', 'utf-16le', 'utf-16be',  # UTF-16 variants
                    'cp850', 'cp437',  # DOS encodings
                    'mbcs',  # Windows default multibyte encoding
                ])
                
                # Remove duplicates while preserving order
                seen = set()
                encodings = [e for e in encodings if e and (e not in seen or seen.add(e))]
                
                df = None
                encoding_used = None
                last_error = None
                
                for encoding in encodings:
                    try:
                        # Reset BytesIO for each attempt
                        file_io = io.BytesIO(file_content)
                        df = pd.read_csv(
                            file_io,
                            encoding=encoding,
                            skip_blank_lines=True,
                            on_bad_lines='skip',  # Skip problematic lines instead of failing
                            engine='python'  # More lenient parsing
                        )
                        encoding_used = encoding
                        logger.info(f"✅ Successfully parsed CSV with encoding: {encoding}")
                        break
                    except UnicodeDecodeError as e:
                        last_error = str(e)
                        logger.debug(f"Encoding {encoding} failed: {e}")
                        continue
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Error parsing CSV with encoding {encoding}: {e}")
                        continue
                
                if df is None:
                    error_msg = f"Failed to parse CSV with any supported encoding. Last error: {last_error}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                # Convert to dict and clean values
                rows = []
                for record in df.to_dict('records'):
                    cleaned_row = {}
                    for key, value in record.items():
                        if pd.isna(value):
                            cleaned_row[str(key)] = ''
                        elif isinstance(value, (pd.Timestamp, type(pd.NaT))):
                            cleaned_row[str(key)] = str(value)
                        else:
                            cleaned_row[str(key)] = str(value).strip() if value else ''
                    rows.append(cleaned_row)
                    
            elif file_type == 'xlsx':
                import pandas as pd
                df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
                
                # Convert to dict and handle datetime objects
                rows = []
                for record in df.to_dict('records'):
                    cleaned_row = {}
                    for key, value in record.items():
                        if pd.isna(value):
                            cleaned_row[str(key)] = ''
                        elif isinstance(value, (pd.Timestamp, type(pd.NaT))):
                            # Convert datetime to ISO format string
                            cleaned_row[str(key)] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
                        elif isinstance(value, (datetime.datetime, datetime.date)):
                            # Handle Python datetime objects
                            cleaned_row[str(key)] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
                        else:
                            cleaned_row[str(key)] = str(value).strip() if value else ''
                    rows.append(cleaned_row)
            elif file_type == 'pdf':
                # For PDF, save to temp file and parse
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_type}') as tmp_file:
                    tmp_file.write(file_content)
                    tmp_path = tmp_file.name
                
                try:
                    # Parse PDF from temp file
                    import pdfplumber
                    all_rows = []
                    with pdfplumber.open(tmp_path) as pdf:
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
                    rows = all_rows
                finally:
                    os.unlink(tmp_path)
            else:
                rows = []
            
            if not rows:
                storage.update_document_status(document_id, 'completed', rows_count=0, error_message='No data found')
                return ParseResponse(success=True, rows_extracted=0, anomalies_count=0)
            
            # Store rows
            rows_inserted = storage.store_rows(document_id, rows)
            
            # Run anomaly detection
            anomalies = anomaly_detector.detect_all(rows)
            anomalies_count = 0
            if anomalies:
                anomalies_count = storage.store_anomalies(document_id, anomalies)
            
            # Generate insights
            insights = insight_generator.generate_insights(anomalies)
            
            # Update document
            storage.update_document_status(
                document_id,
                'completed',
                rows_count=rows_inserted,
                anomalies_count=anomalies_count,
                insights_summary=insights
            )
            
            return ParseResponse(
                success=True,
                rows_extracted=rows_inserted,
                anomalies_count=anomalies_count,
                insights_summary=insights,
                error=None
            )
        
        # Supabase mode: existing flow
        if not request:
            raise HTTPException(status_code=400, detail="Either file upload or parse request required")
        
        logger.info(f"📨 Parse request received for document {request.document_id}")
        
        # Validate file type
        if request.file_type not in ['pdf', 'csv', 'xlsx']:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {request.file_type}"
            )
        
        # Process the document
        rows_extracted, anomalies, insights = await process_document(
            request.document_id,
            request.file_url,
            request.file_type
        )
        
        return ParseResponse(
            success=True,
            rows_extracted=rows_extracted,
            anomalies_count=len(anomalies) if anomalies else 0,
            insights_summary=insights
        )
        
    except Exception as e:
        logger.error(f"Error in parse endpoint: {e}")
        debug_logger.log_error("PARSE", e, {"filename": file.filename if file else None})
        
        # Update document status to 'failed' if document was created
        if document_id:
            try:
                storage.update_document_status(
                    document_id,
                    'failed',
                    error_message=str(e)
                )
                logger.info(f"✅ Updated document {document_id} status to 'failed'")
            except Exception as update_error:
                logger.error(f"Failed to update document status: {update_error}")
        
        return ParseResponse(
            success=False,
            rows_extracted=0,
            anomalies_count=0,
            error=str(e)
        )


@app.post("/analyze")
async def analyze_document(request: AnalyzeRequest):
    """Re-run anomaly detection on an existing document"""
    try:
        # Get document rows
        rows_data = storage.get_rows(request.document_id, limit=10000)
        if not rows_data:
            raise HTTPException(status_code=404, detail="Document not found or has no rows")
        
        # Extract raw_json from rows
        rows = [row['raw_json'] for row in rows_data]
        
        # Run anomaly detection
        detection_start_time = time.time()
        anomalies = anomaly_detector.detect_all(rows)
        detection_time = time.time() - detection_start_time
        
        # Store anomalies
        anomalies_count = 0
        if anomalies:
            anomalies_count = storage.store_anomalies(request.document_id, anomalies)
        
        # Generate insights
        insights = insight_generator.generate_insights(anomalies)
        
        # Update document
        storage.update_document_status(
            request.document_id,
            None,  # Don't change status
            anomalies_count=anomalies_count,
            insights_summary=insights
        )
        
        return {
            "success": True,
            "anomalies_count": anomalies_count,
            "anomalies": anomalies[:100],  # Limit to first 100 for response
            "insights": insights,
            "detection_time": detection_time
        }
        
    except Exception as e:
        logger.error(f"Error in analyze endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
async def get_all_documents():
    """Get all documents (for local mode)"""
    try:
        # Use storage interface to get documents
        # For SQLite, query directly
        if isinstance(storage, SQLiteStorage):
            import sqlite3
            db_path = storage.db_path
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, user_id, file_name, file_type, file_url, format_detected,
                       upload_date, status, rows_count, anomalies_count, error_message,
                       insights_summary, created_at, updated_at
                FROM documents
                ORDER BY upload_date DESC
            """)
            
            documents = []
            for row in cursor.fetchall():
                doc = {
                    'id': row[0],
                    'user_id': row[1],
                    'file_name': row[2],
                    'file_type': row[3],
                    'file_url': row[4],
                    'format_detected': row[5],
                    'upload_date': row[6] or '',
                    'status': row[7],
                    'rows_count': row[8] or 0,
                    'anomalies_count': row[9] or 0,
                    'error_message': row[10],
                    'insights_summary': json.loads(row[11]) if row[11] else None,
                    'created_at': row[12] or '',
                    'updated_at': row[13] or ''
                }
                documents.append(doc)
            
            conn.close()
            return documents
        else:
            # For Supabase, use storage methods
            # Return empty for now - would need to implement get_all in storage interface
            return []
        
    except Exception as e:
        logger.error(f"Error fetching documents: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


@app.get("/document/{document_id}")
async def get_document_info(document_id: str):
    """Get information about a document"""
    try:
        doc = storage.get_document(document_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return doc
        
    except Exception as e:
        logger.error(f"Error fetching document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/document/{document_id}")
async def delete_document(document_id: str):
    """Delete a document and all its associated data"""
    try:
        doc = storage.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete document (cascades to rows, anomalies, notes via foreign keys)
        storage.delete_document(document_id)
        
        logger.info(f"✅ Deleted document {document_id}")
        return {"success": True, "message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/document/{document_id}/rows")
async def get_document_rows(document_id: str, limit: int = 100, offset: int = 0):
    """Get extracted rows for a document"""
    try:
        rows = storage.get_rows(document_id, limit=limit, offset=offset)
        
        return {
            "document_id": document_id,
            "rows": rows,
            "count": len(rows)
        }
        
    except Exception as e:
        logger.error(f"Error fetching document rows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/document/{document_id}/anomalies")
async def get_document_anomalies(document_id: str):
    """Get all anomalies for a document"""
    try:
        anomalies = storage.get_anomalies(document_id)
        return {
            "document_id": document_id,
            "anomalies": anomalies,
            "count": len(anomalies)
        }
    except Exception as e:
        logger.error(f"Error fetching anomalies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/anomalies")
async def get_anomalies_by_query(doc_id: str):
    """Alias endpoint: Get anomalies by document ID via query param"""
    return await get_document_anomalies(doc_id)


@app.post("/api/anomalies/run")
async def rerun_anomaly_detection(request: AnalyzeRequest):
    """Alias endpoint: Re-run anomaly detection"""
    return await analyze_document(request)


@app.get("/document/{document_id}/insights")
async def get_document_insights(document_id: str):
    """Get generated insights for a document"""
    try:
        doc = storage.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        insights = doc.get('insights_summary')
        if not insights:
            # Generate insights if not present
            anomalies = storage.get_anomalies(document_id)
            insights = insight_generator.generate_insights(anomalies)
        
        return insights
    except Exception as e:
        logger.error(f"Error fetching insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Notes endpoints
@app.get("/document/{document_id}/notes")
async def get_document_notes(document_id: str):
    """Get all notes for a document"""
    try:
        notes = notes_manager.get_all_notes(document_id)
        return {
            "document_id": document_id,
            "notes": notes,
            "count": len(notes)
        }
    except Exception as e:
        logger.error(f"Error fetching notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/document/{document_id}/notes")
async def create_document_note(document_id: str, note: NoteCreate):
    """Create a document-level note"""
    try:
        new_note = notes_manager.create_note(
            document_id=document_id,
            content=note.content,
            author=note.author
        )
        return new_note
    except Exception as e:
        logger.error(f"Error creating note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AnomalyNoteCreate(BaseModel):
    content: str = Field(..., description="Note content")
    author: str = Field(default="system", description="Note author")
    document_id: str = Field(..., description="Document ID")


@app.post("/anomalies/{anomaly_id}/notes")
async def create_anomaly_note(anomaly_id: str, note: AnomalyNoteCreate):
    """Create a note for a specific anomaly"""
    try:
        new_note = notes_manager.create_note(
            document_id=note.document_id,
            content=note.content,
            author=note.author,
            anomaly_id=anomaly_id
        )
        return new_note
    except Exception as e:
        logger.error(f"Error creating anomaly note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notes/{note_id}/replies")
async def get_note_replies(note_id: str, document_id: str):
    """Get replies to a note"""
    try:
        replies = notes_manager.get_note_replies(document_id, note_id)
        return {
            "note_id": note_id,
            "replies": replies,
            "count": len(replies)
        }
    except Exception as e:
        logger.error(f"Error fetching note replies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/logs")
async def get_debug_logs(lines: int = 100):
    """Get recent debug logs"""
    try:
        logs = debug_logger.get_recent_logs(lines)
        return {
            "logs": logs,
            "lines": lines
        }
    except Exception as e:
        logger.error(f"Error fetching debug logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/document/{document_id}/cancel")
async def cancel_processing(document_id: str):
    """Cancel processing for a document"""
    try:
        doc = storage.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if doc.get('status') != 'processing':
            raise HTTPException(status_code=400, detail="Document is not processing")
        
        # Update status to cancelled
        storage.update_document_status(
            document_id,
            'failed',
            error_message='Processing cancelled by user'
        )
        
        logger.info(f"✅ Cancelled processing for document {document_id}")
        return {"success": True, "message": "Processing cancelled"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/document/{document_id}/retry")
async def retry_processing(document_id: str):
    """Retry processing for a failed document"""
    try:
        doc = storage.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if doc.get('status') not in ['failed']:
            raise HTTPException(status_code=400, detail="Can only retry failed documents")
        
        # Reset status to processing
        storage.update_document_status(
            document_id,
            'processing',
            error_message=None
        )
        
        # Note: Actual reprocessing would require the original file
        # For now, this just resets the status
        # In production, you'd queue the file for reprocessing
        
        logger.info(f"✅ Retrying processing for document {document_id}")
        return {
            "success": True, 
            "message": "Status reset to processing",
            "note": "Re-upload the file to actually reprocess it"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cleanup/stuck-files")
async def cleanup_stuck_files(max_age_minutes: int = 30):
    """Cleanup files stuck in processing status"""
    try:
        if isinstance(storage, SQLiteStorage):
            import sqlite3
            db_path = storage.db_path
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Find documents stuck in processing for more than max_age_minutes
            cursor.execute("""
                UPDATE documents 
                SET status = 'failed', 
                    error_message = 'Processing timeout - file may have been corrupted or too large',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'processing' 
                  AND datetime(created_at, '+' || ? || ' minutes') < datetime('now')
            """, (max_age_minutes,))
            
            updated_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Cleaned up {updated_count} stuck files")
            return {
                "success": True,
                "updated_count": updated_count,
                "message": f"Marked {updated_count} stuck files as failed"
            }
        else:
            return {"success": False, "message": "Cleanup only supported for SQLite storage"}
            
    except Exception as e:
        logger.error(f"Error cleaning up stuck files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report")
async def generate_ic_report_endpoint(doc_id: str):
    """Generate Investment Committee PDF report"""
    try:
        logger.info(f"Generating IC report for document {doc_id}")
        
        # Fetch document data
        document = storage.get_document(doc_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Fetch anomalies
        anomalies = storage.get_anomalies(doc_id)
        
        # Fetch rows (limited sample)
        rows = storage.get_rows(doc_id, limit=10000)
        
        # Fetch notes
        try:
            notes = notes_manager.get_all_notes(doc_id).get('notes', [])
        except:
            notes = []
        
        # Generate insights
        insights = insight_generator.generate_insights(anomalies)
        
        # Generate PDF report
        report_path = report_generator.generate_report(
            document_id=doc_id,
            document_name=document.get('file_name', 'Unknown'),
            insights=insights,
            anomalies=anomalies,
            notes=notes,
            rows_sample=rows[:50] if rows else None
        )
        
        logger.info(f"Report generated successfully: {report_path}")
        
        # Return file
        return FileResponse(
            report_path,
            media_type='application/pdf',
            filename=f"{document.get('file_name', 'document')}_IC_Report.pdf"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating IC report: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
