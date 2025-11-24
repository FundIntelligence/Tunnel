# FundIQ Tunnel Project - Complete File Analysis

## 📋 Project Overview

**FundIQ** is a financial intelligence platform for automatically extracting structured data from financial documents (PDFs, CSVs, Excel files). This is a **separate project** from the Beyo Finances project in the parent directory.

**Purpose**: AI-powered document processing for investment teams to extract transaction data, analyze financial statements, and export structured data for analysis.

---

## 🗂️ File Structure & Purpose

### 📱 **Frontend Files (Next.js/React/TypeScript)**

#### **Configuration Files**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `package.json` | Node.js dependencies and scripts | Defines all frontend libraries (Next.js, React, Supabase, Tailwind) and npm scripts |
| `tsconfig.json` | TypeScript configuration | Ensures type safety across the frontend |
| `next.config.js` | Next.js framework configuration | Configures routing, build settings, and framework behavior |
| `tailwind.config.ts` | Tailwind CSS configuration | Defines design system, colors, and styling rules |
| `postcss.config.js` | PostCSS configuration | Processes CSS for Tailwind compilation |
| `next-env.d.ts` | Next.js TypeScript definitions | Provides type definitions for Next.js APIs |

#### **Application Pages**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `app/page.tsx` | Main application entry point | Landing page where users upload files and see their documents |
| `app/layout.tsx` | App-wide layout wrapper | Defines HTML structure, metadata, and global providers |
| `app/globals.css` | Global CSS styles | Base styles, Tailwind directives, and custom CSS variables |
| `app/simple-page/page.tsx` | Demo version page | Simplified version for testing without Supabase (uses SQLite) |
| `app/simple-page/page-component.tsx` | Demo page component | Component logic for demo mode |
| `app/simple-page.tsx` | Alternative demo entry | Alternative demo route |
| `app/debug/page.tsx` | Debug/testing page | Development page for testing components in isolation |

#### **React Components**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `components/FileUpload.tsx` | File upload interface | **Core component** - Handles drag-and-drop, file validation, upload progress, Supabase Storage integration |
| `components/SimpleFileUpload.tsx` | Demo upload component | Simplified version for demo mode (local storage only) |
| `components/DocumentList.tsx` | Document management UI | **Core component** - Lists all uploaded documents, shows status (uploaded/processing/completed/failed), delete functionality |
| `components/SimpleDocumentList.tsx` | Demo document list | Simplified version for demo mode |
| `components/DataReview.tsx` | Data viewer modal | **Core component** - Full-screen modal showing extracted data with search, sort, filter, pagination, and CSV/JSON export |

#### **Library/Utility Files**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `lib/supabase.ts` | Supabase client & helpers | **Critical** - Initializes Supabase client, provides functions for database operations, file storage uploads |
| `lib/simple_supabase.ts` | Demo database client | SQLite-based alternative for demo mode (no Supabase required) |
| `lib/types.ts` | TypeScript type definitions | Defines types for Document, ExtractedRow, and API responses |

---

### 🐍 **Backend Files (Python/FastAPI)**

#### **Main Backend Files**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `backend/main.py` | FastAPI server & API endpoints | **Core backend** - Handles HTTP requests, coordinates file parsing, manages Supabase database operations, provides REST API |
| `backend/simple_main.py` | Demo backend server | Simplified version using SQLite instead of Supabase for local testing |
| `backend/parsers.py` | Document parsing logic | **Critical** - Contains PDF, CSV, and Excel parsers that extract structured data from files |

#### **Backend Configuration**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `backend/requirements.txt` | Python dependencies | Lists all Python packages needed (FastAPI, Supabase, pandas, pdfplumber, etc.) |
| `backend/railway.toml` | Railway deployment config | Configuration for deploying backend to Railway platform |
| `backend/README.md` | Backend documentation | Setup instructions, API endpoint documentation, parser details |

#### **Backend Testing/Data**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `backend/test_parsers.py` | Parser unit tests | Tests individual parsers to ensure they work correctly |
| `backend/test_supabase.py` | Supabase connection tests | Verifies Supabase connectivity and operations |
| `backend/test_service_role.py` | Service role key tests | Tests that service role authentication works |
| `backend/test_startup.sh` | Backend startup test script | Automated script to verify backend starts correctly |
| `backend/RUN_TESTS.sh` | Test runner script | Runs all backend tests |
| `backend/test_sample_files/` | Sample test files | PDF and Excel files for testing parsers |

#### **Backend Databases**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `backend/fundiq_demo.db` | SQLite demo database | Local SQLite database for demo mode (no Supabase needed) |
| `backend/fundiq_demo 2.db` | Backup demo database | Duplicate/backup of demo database |

---

### 🗄️ **Database Files**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `supabase/schema.sql` | Database schema definition | **Critical** - Creates tables (`documents`, `extracted_rows`), indexes, RLS policies, triggers for Supabase PostgreSQL database |
| `fix_supabase.sql` | RLS policy fixes | SQL script to fix Row Level Security issues if they occur |
| `fix_rls_final.sql` | Final RLS fix | Additional RLS policy corrections |

---

### 📚 **Documentation Files**

#### **Setup & Quick Start Guides**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `README.md` | Main project README | **Start here** - Overview, features, architecture, quick start, API docs |
| `QUICK_START.md` | Quick setup guide | Fast-track setup instructions for immediate use |
| `SETUP.md` | Detailed setup guide | Step-by-step setup instructions for all components |
| `ENV_SETUP_GUIDE.md` | Environment variable guide | How to configure `.env.local` and environment variables |
| `env-template.txt` | Environment variable template | Template showing what environment variables are needed |

#### **Implementation Reports**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `PROJECT_OVERVIEW.md` | Comprehensive project overview | Architecture, data flow, features, technical decisions, deployment guide |
| `IMPLEMENTATION_COMPLETE.md` | Implementation status report | Documents completion of frontend-backend integration, debug logging, testing setup |
| `IMPLEMENTATION_REPORT.md` | Detailed implementation report | Full breakdown of what was implemented |
| `COMPLETED_FEATURES.md` | Features checklist | Complete list of all implemented features with status |

#### **Testing & Deployment Guides**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `TESTING_GUIDE.md` | Testing instructions | How to test the application, what to verify |
| `FRONTEND_BACKEND_TESTING.md` | Integration testing guide | Step-by-step guide for testing frontend-backend connection |
| `DEPLOY_TO_PRODUCTION.md` | Production deployment guide | Instructions for deploying to Vercel (frontend) and Railway/Render (backend) |
| `DEPLOY_CHECKLIST.md` | Deployment checklist | Pre-deployment checklist to ensure everything is ready |
| `SERVICE_ROLE_FIX_SUMMARY.md` | Service role key fix docs | Documents how RLS (Row Level Security) issues were fixed |

#### **Planning Documents**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `SETUP_CHECKLIST.md` | Setup task checklist | Checklist for setting up the project locally |
| `FILE_STRUCTURE.txt` | Project structure overview | Text representation of project folder structure |

#### **Business Documents**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `FundIQ_MVP_File_Upload_Module.docx` | Business requirements doc | Word document with original requirements/specifications |
| `FundIQ_Tech_Strategy_Brief.docx` | Technical strategy document | Technical planning and architecture decisions |

---

### 🛠️ **Scripts & Automation**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `scripts/quick-start.sh` | Automated setup script | One-command setup that installs dependencies, configures environment |
| `start-production.sh` | Production startup script | Starts both frontend and backend for production mode |
| `start-simple.sh` | Demo startup script | Starts demo mode (SQLite, no Supabase) |
| `prepare_deploy.sh` | Pre-deployment script | Prepares project for deployment (builds, checks) |
| `TEST_NOW.sh` | Quick test script | Runs quick tests to verify setup |

---

### 📊 **Data & Test Files**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `test-data/sample.csv` | Sample CSV file | Example file for testing CSV parser |
| `Statement_All_Transactions_20250101_20250201.pdf` | Sample PDF file | Example PDF for testing PDF parser |

---

### 🚂 **Deployment Configuration**

| File | Purpose | Why It Matters |
|------|---------|----------------|
| `railway.toml` | Railway deployment config | Configuration for deploying entire project to Railway platform |

---

## 🔄 How Files Work Together

### **Upload Flow**:
1. User drags file → `components/FileUpload.tsx`
2. Uploads to Supabase Storage → `lib/supabase.ts`
3. Creates document record → Supabase via `lib/supabase.ts`
4. Frontend calls backend → `backend/main.py` `/parse` endpoint
5. Backend downloads file → Supabase Storage
6. Backend parses file → `backend/parsers.py` (PDF/CSV/Excel parser)
7. Backend stores extracted rows → Supabase via `backend/main.py`
8. Frontend refreshes document list → `components/DocumentList.tsx`
9. User clicks document → `components/DataReview.tsx` shows data

### **Database Flow**:
1. Schema created → `supabase/schema.sql` run in Supabase SQL editor
2. Documents stored → `documents` table (via `lib/supabase.ts` or `backend/main.py`)
3. Extracted rows stored → `extracted_rows` table (via `backend/main.py`)
4. RLS policies enforce → User can only see their own data

---

## 🎯 Key File Relationships

### **Frontend ↔ Backend**
- `components/FileUpload.tsx` → calls `backend/main.py` `/parse` endpoint
- `components/DocumentList.tsx` → reads from Supabase via `lib/supabase.ts`
- `components/DataReview.tsx` → fetches rows from Supabase via `lib/supabase.ts`

### **Backend ↔ Database**
- `backend/main.py` → writes to Supabase using service role key
- `backend/parsers.py` → called by `backend/main.py` to extract data
- `supabase/schema.sql` → defines database structure backend uses

### **Configuration**
- `env-template.txt` → defines what goes in `.env.local` (frontend) and `.env` (backend)
- `package.json` & `backend/requirements.txt` → define all dependencies

---

## 📊 Project Statistics

- **Total Files**: 61+ files
- **Frontend Code**: ~1,500 lines (TypeScript/React)
- **Backend Code**: ~700 lines (Python/FastAPI)
- **Database Schema**: ~200 lines (SQL)
- **Documentation**: ~1,000+ lines (Markdown)
- **Components**: 5 major React components
- **API Endpoints**: 5+ REST endpoints
- **Parsers**: 3 file format parsers (PDF, CSV, Excel)

---

## 🚀 Quick File Navigation Guide

**Want to:**
- **Start the app?** → See `QUICK_START.md` or `scripts/quick-start.sh`
- **Understand architecture?** → Read `PROJECT_OVERVIEW.md`
- **Set up environment?** → See `ENV_SETUP_GUIDE.md` and `env-template.txt`
- **Upload files?** → Check `components/FileUpload.tsx`
- **View data?** → See `components/DataReview.tsx`
- **Understand parsing?** → Read `backend/parsers.py`
- **Deploy?** → See `DEPLOY_TO_PRODUCTION.md`
- **Test?** → See `TESTING_GUIDE.md`

---

## 🔑 Critical Files (Must Understand)

1. **`backend/main.py`** - Backend API server
2. **`backend/parsers.py`** - Document parsing logic
3. **`lib/supabase.ts`** - Database client for frontend
4. **`components/FileUpload.tsx`** - File upload UI
5. **`components/DataReview.tsx`** - Data viewing UI
6. **`supabase/schema.sql`** - Database structure
7. **`README.md`** - Project overview

---

## 💡 Summary

The **Tunnel** folder contains a **complete, production-ready MVP** for financial document processing. It's a separate project from Beyo Finances, designed specifically for:

- **Uploading** financial documents (PDF, CSV, Excel)
- **Extracting** structured data automatically
- **Reviewing** extracted data in an interactive table
- **Exporting** data as CSV or JSON
- **Managing** documents with status tracking

All files work together to create a seamless document processing pipeline from upload → parsing → storage → review → export.

---

**Last Updated**: Analysis based on project state as of October 2025



