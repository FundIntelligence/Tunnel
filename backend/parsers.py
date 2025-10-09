"""
File parsers for PDF, CSV, and XLSX files
"""
import pdfplumber
import pandas as pd
from typing import List, Dict, Any, Optional
import logging
import io
import httpx

logger = logging.getLogger(__name__)


class FileParser:
    """Base class for file parsers"""
    
    @staticmethod
    async def download_file(url: str) -> bytes:
        """Download file from URL"""
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content


class PDFParser(FileParser):
    """Parser for PDF files using pdfplumber"""
    
    @staticmethod
    async def parse(file_url: str) -> List[Dict[str, Any]]:
        """
        Extract tables and text from PDF
        Returns a list of dictionaries representing rows
        """
        logger.info(f"Parsing PDF from {file_url}")
        
        # Download the file
        file_content = await FileParser.download_file(file_url)
        
        all_rows = []
        
        # Open PDF with pdfplumber
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            logger.info(f"PDF has {len(pdf.pages)} pages")
            
            for page_num, page in enumerate(pdf.pages, start=1):
                # Try to extract tables first
                tables = page.extract_tables()
                
                if tables:
                    logger.info(f"Found {len(tables)} tables on page {page_num}")
                    for table_num, table in enumerate(tables, start=1):
                        # Convert table to list of dicts
                        if len(table) > 1:
                            headers = table[0]
                            # Clean headers
                            headers = [
                                str(h).strip() if h is not None else f"Column_{i}"
                                for i, h in enumerate(headers)
                            ]
                            
                            # Process data rows
                            for row_data in table[1:]:
                                if row_data and any(cell for cell in row_data):
                                    row_dict = {
                                        'page': page_num,
                                        'table': table_num,
                                    }
                                    for i, cell in enumerate(row_data):
                                        if i < len(headers):
                                            row_dict[headers[i]] = str(cell).strip() if cell else ''
                                    all_rows.append(row_dict)
                else:
                    # If no tables found, extract text
                    text = page.extract_text()
                    if text:
                        logger.info(f"No tables on page {page_num}, extracting text")
                        lines = text.split('\n')
                        for line_num, line in enumerate(lines, start=1):
                            if line.strip():
                                all_rows.append({
                                    'page': page_num,
                                    'line': line_num,
                                    'text': line.strip()
                                })
        
        logger.info(f"Extracted {len(all_rows)} rows from PDF")
        return all_rows


class CSVParser(FileParser):
    """Parser for CSV files using pandas"""
    
    @staticmethod
    async def parse(file_url: str) -> List[Dict[str, Any]]:
        """
        Parse CSV file
        Returns a list of dictionaries representing rows
        """
        logger.info(f"Parsing CSV from {file_url}")
        
        # Download the file
        file_content = await FileParser.download_file(file_url)
        
        # Try different encodings
        encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
        df = None
        
        for encoding in encodings:
            try:
                df = pd.read_csv(
                    io.BytesIO(file_content),
                    encoding=encoding,
                    skip_blank_lines=True
                )
                logger.info(f"Successfully parsed CSV with encoding: {encoding}")
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"Error parsing CSV with encoding {encoding}: {e}")
                continue
        
        if df is None:
            raise ValueError("Failed to parse CSV with any supported encoding")
        
        # Clean column names
        df.columns = df.columns.str.strip()
        
        # Convert to list of dicts
        # Replace NaN with None
        rows = df.where(pd.notnull(df), None).to_dict('records')
        
        # Convert all values to strings for consistency
        cleaned_rows = []
        for row in rows:
            cleaned_row = {}
            for key, value in row.items():
                if value is None:
                    cleaned_row[key] = ''
                else:
                    cleaned_row[key] = str(value).strip()
            cleaned_rows.append(cleaned_row)
        
        logger.info(f"Extracted {len(cleaned_rows)} rows from CSV")
        return cleaned_rows


class ExcelParser(FileParser):
    """Parser for Excel files using pandas"""
    
    @staticmethod
    async def parse(file_url: str, sheet_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Parse Excel file
        Returns a list of dictionaries representing rows
        If sheet_name is None, uses the first sheet
        """
        logger.info(f"Parsing Excel from {file_url}")
        
        # Download the file
        file_content = await FileParser.download_file(file_url)
        
        # Read Excel file
        try:
            # If sheet_name not specified, read first sheet
            excel_file = pd.ExcelFile(io.BytesIO(file_content))
            
            if sheet_name is None:
                sheet_name = excel_file.sheet_names[0]
                logger.info(f"Using first sheet: {sheet_name}")
            
            df = pd.read_excel(
                io.BytesIO(file_content),
                sheet_name=sheet_name,
                engine='openpyxl'
            )
            
            logger.info(f"Loaded sheet '{sheet_name}' with {len(df)} rows")
            
        except Exception as e:
            logger.error(f"Error parsing Excel file: {e}")
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
        
        # Clean column names
        df.columns = df.columns.astype(str).str.strip()
        
        # Add sheet name to each row
        df['_sheet'] = sheet_name
        
        # Convert to list of dicts
        rows = df.where(pd.notnull(df), None).to_dict('records')
        
        # Convert all values to strings for consistency
        cleaned_rows = []
        for row in rows:
            cleaned_row = {}
            for key, value in row.items():
                if value is None:
                    cleaned_row[key] = ''
                else:
                    cleaned_row[key] = str(value).strip()
            cleaned_rows.append(cleaned_row)
        
        logger.info(f"Extracted {len(cleaned_rows)} rows from Excel")
        return cleaned_rows


def get_parser(file_type: str):
    """Get the appropriate parser for the file type"""
    parsers = {
        'pdf': PDFParser,
        'csv': CSVParser,
        'xlsx': ExcelParser,
    }
    
    parser = parsers.get(file_type.lower())
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")
    
    return parser


