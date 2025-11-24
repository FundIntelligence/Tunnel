# FundIQ MVP - Application Links & Status

## 🚀 Application is Running!

### Frontend Dashboard
**👉 Open this link in your browser:**
**http://localhost:3000**

### Backend API
**Base URL:** http://localhost:8000

---

## ✅ Current Status

### Backend (Port 8000)
- ✅ Status: Running
- ✅ Storage: SQLite (Local-first mode)
- ✅ Health: Healthy
- ✅ Features: All operational

### Frontend (Port 3000)
- ✅ Status: Running
- ✅ Framework: Next.js 14.1.0
- ✅ Mode: Local-first (Supabase optional)

---

## 📋 Quick Test Steps

1. **Open Application**
   - Click or visit: **http://localhost:3000**

2. **Upload Test File**
   - Use test files from: `backend/test_data/`
   - Try: `revenue_anomalies.csv`
   - Expected: 2 anomalies detected

3. **View Results**
   - Anomalies will be detected automatically
   - Check document list for uploaded files
   - View anomalies and insights

---

## 🔗 Test Data Files

Located in: `backend/test_data/`

1. **revenue_anomalies.csv** - 2 anomalies
2. **expense_integrity.xlsx** - 4 anomalies  
3. **cashflow_consistency.csv** - 1 anomaly
4. **payroll_anomalies.xlsx** - 1 anomaly
5. **declared_mismatch.csv** - 1 anomaly

---

## 🧪 API Testing

### Health Check
```bash
curl http://localhost:8000/health
```

### Get Documents
```bash
curl http://localhost:8000/documents
```

### Get Anomalies (after upload)
```bash
curl http://localhost:8000/documents/{doc_id}/anomalies
```

### Get Insights
```bash
curl http://localhost:8000/documents/{doc_id}/insights
```

---

## 📝 What's Working

✅ Local-first mode (no Supabase required)
✅ File upload and parsing
✅ Anomaly detection (5 rule types)
✅ Insights generation
✅ Notes system
✅ SQLite storage
✅ Debug logging

---

## 🎯 Ready to Test!

**Frontend Link:** http://localhost:3000

Just open the link above and start uploading files!

---

**Status:** All systems operational ✅
**Date:** November 3, 2025


