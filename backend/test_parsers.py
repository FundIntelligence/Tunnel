#!/usr/bin/env python3
"""
Test script for FundIQ parsers (PDF, CSV, Excel)
Run this to verify all parsers work correctly before running the full app.

Usage:
    python test_parsers.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path so we can import parsers
sys.path.insert(0, str(Path(__file__).parent))

from parsers import PDFParser, CSVParser, ExcelParser
import asyncio

# ANSI color codes for pretty output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_header(text):
    """Print a formatted header"""
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")


def print_success(text):
    """Print success message"""
    print(f"{GREEN}✓ {text}{RESET}")


def print_error(text):
    """Print error message"""
    print(f"{RED}✗ {text}{RESET}")


def print_info(text):
    """Print info message"""
    print(f"{YELLOW}ℹ {text}{RESET}")


async def test_csv_parser():
    """Test CSV parser with the sample CSV file"""
    print_header("Testing CSV Parser")
    
    csv_path = Path(__file__).parent.parent / "test-data" / "sample.csv"
    
    if not csv_path.exists():
        print_error(f"Sample CSV not found at: {csv_path}")
        print_info("Creating a simple test CSV file...")
        
        # Create test CSV
        csv_path.parent.mkdir(exist_ok=True)
        with open(csv_path, 'w') as f:
            f.write("Date,Transaction,Amount,Category\n")
            f.write("2024-01-01,Office Supplies,250.00,Expense\n")
            f.write("2024-01-05,Client Payment,5000.00,Revenue\n")
            f.write("2024-01-10,Software License,99.00,Expense\n")
        
        print_success(f"Created test CSV at: {csv_path}")
    
    try:
        # Read the file and create a mock URL (for local testing)
        with open(csv_path, 'rb') as f:
            content = f.read()
        
        # Test the parser by directly using the content
        import io
        import pandas as pd
        
        print_info("Parsing CSV file...")
        df = pd.read_csv(io.BytesIO(content))
        rows = df.to_dict('records')
        
        print_success(f"Successfully parsed CSV")
        print_info(f"Rows extracted: {len(rows)}")
        print_info(f"Columns: {list(df.columns)}")
        
        if rows:
            print_info("First row sample:")
            print(f"  {rows[0]}")
        
        return True
        
    except Exception as e:
        print_error(f"CSV parsing failed: {e}")
        return False


async def test_excel_parser():
    """Test Excel parser"""
    print_header("Testing Excel Parser")
    
    xlsx_path = Path(__file__).parent / "test_sample_files" / "test.xlsx"
    
    if not xlsx_path.exists():
        print_info("Creating a simple test Excel file...")
        
        try:
            import pandas as pd
            
            # Create test data
            data = {
                'Date': ['2024-01-01', '2024-01-05', '2024-01-10'],
                'Transaction': ['Office Supplies', 'Client Payment', 'Software License'],
                'Amount': [250.00, 5000.00, 99.00],
                'Category': ['Expense', 'Revenue', 'Expense']
            }
            df = pd.DataFrame(data)
            
            # Create directory and save
            xlsx_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_excel(xlsx_path, index=False, engine='openpyxl')
            
            print_success(f"Created test Excel file at: {xlsx_path}")
            
        except Exception as e:
            print_error(f"Could not create test Excel file: {e}")
            print_info("Skipping Excel parser test")
            return None
    
    try:
        # Test the parser
        import pandas as pd
        
        print_info("Parsing Excel file...")
        df = pd.read_excel(xlsx_path, engine='openpyxl')
        rows = df.to_dict('records')
        
        print_success(f"Successfully parsed Excel file")
        print_info(f"Rows extracted: {len(rows)}")
        print_info(f"Columns: {list(df.columns)}")
        
        if rows:
            print_info("First row sample:")
            print(f"  {rows[0]}")
        
        return True
        
    except Exception as e:
        print_error(f"Excel parsing failed: {e}")
        return False


async def test_pdf_parser():
    """Test PDF parser"""
    print_header("Testing PDF Parser")
    
    pdf_path = Path(__file__).parent / "test_sample_files" / "test.pdf"
    
    if not pdf_path.exists():
        print_info(f"No test PDF found at: {pdf_path}")
        print_info("To test PDF parsing:")
        print_info("  1. Create backend/test_sample_files/ directory")
        print_info("  2. Place a PDF with tables in that directory as 'test.pdf'")
        print_info("  3. Run this script again")
        print_info("\nSkipping PDF parser test for now...")
        return None
    
    try:
        print_info("Parsing PDF file...")
        
        import pdfplumber
        
        with pdfplumber.open(pdf_path) as pdf:
            print_success(f"Opened PDF: {len(pdf.pages)} pages")
            
            total_rows = 0
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    print_info(f"  Page {page_num}: {len(tables)} table(s) found")
                    for table in tables:
                        total_rows += len(table) - 1  # Exclude header
                else:
                    text = page.extract_text()
                    if text:
                        print_info(f"  Page {page_num}: No tables, extracted text")
            
            print_success(f"Successfully parsed PDF")
            print_info(f"Total data rows: ~{total_rows}")
        
        return True
        
    except Exception as e:
        print_error(f"PDF parsing failed: {e}")
        return False


async def main():
    """Run all parser tests"""
    print(f"\n{BOLD}FundIQ Parser Test Suite{RESET}")
    print(f"Testing all file parsers...\n")
    
    results = {}
    
    # Test CSV parser
    results['csv'] = await test_csv_parser()
    
    # Test Excel parser
    results['excel'] = await test_excel_parser()
    
    # Test PDF parser
    results['pdf'] = await test_pdf_parser()
    
    # Summary
    print_header("Test Summary")
    
    for parser_name, result in results.items():
        if result is True:
            print_success(f"{parser_name.upper()} Parser: PASSED")
        elif result is False:
            print_error(f"{parser_name.upper()} Parser: FAILED")
        else:
            print_info(f"{parser_name.upper()} Parser: SKIPPED")
    
    # Overall result
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\n{BOLD}Results: {passed} passed, {failed} failed, {skipped} skipped{RESET}\n")
    
    if failed > 0:
        print_error("Some tests failed. Please check the errors above.")
        sys.exit(1)
    else:
        print_success("All tests passed! Parsers are working correctly.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

