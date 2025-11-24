# 📋 File Processing Controls & Encoding Support

## ✅ Solutions Implemented

### 1. **Multiple CSV Encoding Support**

**Problem**: CSV files with different encodings (Windows-1252, ISO-8859-1, etc.) were failing to parse.

**Solution**: 
- **Automatic encoding detection** using `chardet` library (optional, falls back if not installed)
- **Comprehensive encoding list** tries these in order:
  1. Auto-detected encoding (if confidence > 70%)
  2. `utf-8`, `utf-8-sig` (UTF-8 with/without BOM)
  3. `latin-1`, `iso-8859-1`, `cp1252` (Western European)
  4. `utf-16`, `utf-16le`, `utf-16be` (UTF-16 variants)
  5. `cp850`, `cp437` (DOS encodings)
  6. `mbcs` (Windows multibyte)

**Features**:
- **Lenient parsing**: Uses `engine='python'` and `on_bad_lines='skip'` to handle problematic rows
- **Detailed error logging**: Tracks which encoding succeeded or what the last error was
- **No installation required**: Works without `chardet` (uses fallback list)

**Location**: `backend/main.py` lines 252-316

---

### 2. **View Button for Completed Files**

**Problem**: View button was missing or not showing for processed files.

**Solution**: 
- **View button now shows** for:
  - Files with `status === 'completed'`
  - Files with `rows_count > 0` (even if status is different)
- **Persistent availability**: Files remain in the list after processing for review

**Location**: `components/DocumentList.tsx` lines 179-188

---

### 3. **Cancel Processing Files**

**Problem**: No way to stop files stuck in "Processing..." status.

**Solution**: 
- **Cancel button** (X icon) appears for files with `status === 'processing'`
- **Backend endpoint**: `POST /document/{document_id}/cancel`
  - Updates status to `'failed'`
  - Sets error message: "Processing cancelled by user"
- **Safe cancellation**: Updates database status immediately (no background process to kill)

**When to use**: If a file has been processing for too long or you want to stop it manually.

**Location**: 
- Frontend: `components/DocumentList.tsx` lines 191-217
- Backend: `backend/main.py` lines 729-753

---

### 4. **Retry Failed Files**

**Problem**: No way to retry failed file processing without re-uploading.

**Solution**:
- **Retry button** (refresh icon) appears for files with `status === 'failed'`
- **Backend endpoint**: `POST /document/{document_id}/retry`
  - Resets status to `'processing'`
  - Clears error message
- **Note**: This resets the status, but actual reprocessing requires re-uploading the file

**When to use**: After fixing encoding issues or after cleanup of stuck files.

**Location**:
- Frontend: `components/DocumentList.tsx` lines 219-246
- Backend: `backend/main.py` lines 755-781

---

### 5. **Cleanup Stuck Files**

**Problem**: Files stuck in "processing" indefinitely.

**Solution**:
- **Cleanup endpoint**: `POST /cleanup/stuck-files?max_age_minutes=30`
  - Finds documents in `processing` status older than `max_age_minutes`
  - Updates them to `failed` with timeout message
  - Returns count of updated files

**When to use**: 
- Manually: Call endpoint to clean up stuck files
- Automatically: Can be scheduled via cron or background task

**Safety**: Only marks as failed if file is older than specified time (default 30 minutes)

**Location**: `backend/main.py` lines 783-813

---

## 🎯 Usage Guide

### For Users:

1. **View Processed Files**: 
   - Click the eye icon (👁️) next to completed files
   - Opens `DataReview` modal with extracted data, anomalies, and insights

2. **Cancel Stuck Processing**: 
   - Click the X icon (❌) next to processing files
   - Confirms cancellation and updates status

3. **Retry Failed Files**: 
   - Click the refresh icon (🔄) next to failed files
   - Resets status (re-upload file to actually reprocess)

4. **Files Stay Available**: 
   - All processed files remain in the list
   - Can review them anytime via the view button

### For Developers:

```bash
# Cleanup stuck files (30 minutes default)
curl -X POST http://localhost:8000/cleanup/stuck-files?max_age_minutes=30

# Cancel processing for specific document
curl -X POST http://localhost:8000/document/{document_id}/cancel

# Retry failed document
curl -X POST http://localhost:8000/document/{document_id}/retry
```

---

## 🔧 Installation (Optional)

For better CSV encoding detection, install `chardet`:

```bash
pip install chardet
```

**Note**: Not required - the system works without it using fallback encodings.

---

## 📊 Process Flow

```
File Upload
    ↓
Status: "processing"
    ↓
├─→ Success → Status: "completed" → [View Button] 👁️
    │                              → [Delete Button] 🗑️
    │
├─→ Error → Status: "failed" → [Retry Button] 🔄
    │                        → [Delete Button] 🗑️
    │
└─→ Timeout (30+ min) → Auto-cleanup → Status: "failed"
    
During Processing:
    [Cancel Button] ❌ → Status: "failed"
```

---

## ✅ Summary

All three issues have been resolved:

1. ✅ **Multiple encodings**: Comprehensive encoding detection with fallbacks
2. ✅ **View button**: Shows for completed files or files with data
3. ✅ **Cancel/Retry**: Full control over processing status

Files remain available after processing for review, and users have full control over the processing lifecycle.

