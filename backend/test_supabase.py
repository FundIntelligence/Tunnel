#!/usr/bin/env python3
"""
Test script for Supabase connection and operations
Run this to verify your Supabase setup is correct.

Usage:
    python test_supabase.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

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


def check_environment():
    """Check if environment variables are set"""
    print_header("Checking Environment Variables")
    
    required_vars = {
        'SUPABASE_URL': os.getenv('SUPABASE_URL'),
        'SUPABASE_SERVICE_ROLE_KEY': os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    }
    
    all_set = True
    for var_name, var_value in required_vars.items():
        if var_value:
            # Show partial key for security
            if 'KEY' in var_name:
                display_value = f"{var_value[:20]}...{var_value[-10:]}"
            else:
                display_value = var_value
            print_success(f"{var_name}: {display_value}")
        else:
            print_error(f"{var_name}: NOT SET")
            all_set = False
    
    if not all_set:
        print_error("\nMissing environment variables!")
        print_info(f"Make sure backend/.env exists and contains:")
        print_info("  SUPABASE_URL=your-url")
        print_info("  SUPABASE_SERVICE_ROLE_KEY=your-key")
        sys.exit(1)
    
    return True


def test_supabase_connection():
    """Test basic Supabase connection"""
    print_header("Testing Supabase Connection")
    
    try:
        from supabase import create_client, Client
        
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        print_info("Creating Supabase client...")
        supabase: Client = create_client(url, key)
        print_success("Supabase client created")
        
        # Test connection by listing tables
        print_info("Testing database connection...")
        response = supabase.table('documents').select('id').limit(1).execute()
        print_success("Database connection successful")
        
        return supabase
        
    except Exception as e:
        print_error(f"Connection failed: {e}")
        print_info("\nPossible issues:")
        print_info("  1. Check your SUPABASE_URL is correct")
        print_info("  2. Check your SUPABASE_SERVICE_ROLE_KEY is correct")
        print_info("  3. Make sure you ran the schema.sql in Supabase SQL Editor")
        print_info("  4. Check your internet connection")
        sys.exit(1)


def test_documents_table(supabase):
    """Test documents table operations"""
    print_header("Testing Documents Table")
    
    test_doc_id = None
    
    try:
        # Insert a test document
        print_info("Inserting test document...")
        test_data = {
            'user_id': 'test-user-123',
            'file_name': 'test_document.csv',
            'file_type': 'csv',
            'file_url': 'https://example.com/test.csv',
            'status': 'uploaded'
        }
        
        result = supabase.table('documents').insert(test_data).execute()
        test_doc_id = result.data[0]['id']
        print_success(f"Inserted test document: {test_doc_id}")
        
        # Retrieve the document
        print_info("Retrieving test document...")
        result = supabase.table('documents').select('*').eq('id', test_doc_id).execute()
        if result.data:
            print_success("Successfully retrieved document")
            doc = result.data[0]
            print_info(f"  File: {doc['file_name']}")
            print_info(f"  Type: {doc['file_type']}")
            print_info(f"  Status: {doc['status']}")
        else:
            raise Exception("Document not found after insert")
        
        # Update the document
        print_info("Updating document status...")
        result = supabase.table('documents').update({
            'status': 'completed',
            'rows_count': 10
        }).eq('id', test_doc_id).execute()
        print_success("Updated document status to 'completed'")
        
        return test_doc_id
        
    except Exception as e:
        print_error(f"Documents table test failed: {e}")
        return None


def test_extracted_rows_table(supabase, document_id):
    """Test extracted_rows table operations"""
    print_header("Testing Extracted Rows Table")
    
    if not document_id:
        print_info("Skipping (no document ID)")
        return False
    
    try:
        # Insert test rows
        print_info("Inserting test extracted rows...")
        test_rows = [
            {
                'document_id': document_id,
                'row_index': 0,
                'raw_json': {'Date': '2024-01-01', 'Amount': '100.00', 'Category': 'Test'}
            },
            {
                'document_id': document_id,
                'row_index': 1,
                'raw_json': {'Date': '2024-01-02', 'Amount': '200.00', 'Category': 'Test'}
            },
            {
                'document_id': document_id,
                'row_index': 2,
                'raw_json': {'Date': '2024-01-03', 'Amount': '300.00', 'Category': 'Test'}
            }
        ]
        
        result = supabase.table('extracted_rows').insert(test_rows).execute()
        print_success(f"Inserted {len(test_rows)} test rows")
        
        # Retrieve the rows
        print_info("Retrieving extracted rows...")
        result = supabase.table('extracted_rows').select('*').eq('document_id', document_id).execute()
        
        if result.data:
            print_success(f"Successfully retrieved {len(result.data)} rows")
            if result.data:
                first_row = result.data[0]
                print_info(f"  Sample row data: {first_row['raw_json']}")
        else:
            raise Exception("No rows found after insert")
        
        return True
        
    except Exception as e:
        print_error(f"Extracted rows table test failed: {e}")
        return False


def test_storage_bucket(supabase):
    """Test storage bucket access"""
    print_header("Testing Storage Bucket")
    
    try:
        print_info("Checking 'uploads' bucket...")
        
        # Try to list files in the bucket
        result = supabase.storage.from_('uploads').list()
        print_success("Successfully accessed 'uploads' bucket")
        print_info(f"  Files in bucket: {len(result)}")
        
        return True
        
    except Exception as e:
        print_error(f"Storage bucket test failed: {e}")
        print_info("\nMake sure you created the 'uploads' bucket in Supabase:")
        print_info("  1. Go to Storage in Supabase dashboard")
        print_info("  2. Click 'New Bucket'")
        print_info("  3. Name it 'uploads'")
        print_info("  4. Set it to private")
        return False


def cleanup(supabase, document_id):
    """Clean up test data"""
    print_header("Cleaning Up Test Data")
    
    if not document_id:
        print_info("No test data to clean up")
        return
    
    try:
        # Delete test document (will cascade delete extracted_rows)
        print_info(f"Deleting test document: {document_id}")
        supabase.table('documents').delete().eq('id', document_id).execute()
        print_success("Test data cleaned up")
        
    except Exception as e:
        print_error(f"Cleanup failed: {e}")
        print_info(f"You may need to manually delete document: {document_id}")


def main():
    """Run all Supabase tests"""
    print(f"\n{BOLD}FundIQ Supabase Test Suite{RESET}")
    print(f"Testing Supabase connection and operations...\n")
    
    # Check environment
    check_environment()
    
    # Test connection
    supabase = test_supabase_connection()
    
    # Test documents table
    test_doc_id = test_documents_table(supabase)
    
    # Test extracted_rows table
    test_extracted_rows_table(supabase, test_doc_id)
    
    # Test storage bucket
    test_storage_bucket(supabase)
    
    # Clean up
    cleanup(supabase, test_doc_id)
    
    # Summary
    print_header("Test Complete")
    print_success("All Supabase tests passed!")
    print_info("\nYour Supabase setup is working correctly.")
    print_info("You can now run the full application:")
    print_info("  1. Start backend: uvicorn main:app --reload")
    print_info("  2. Start frontend: npm run dev")
    print_info("  3. Visit: http://localhost:3000")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Test interrupted by user{RESET}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {e}{RESET}\n")
        sys.exit(1)

