"""
Structured debug logging for FundIQ MVP
Logs to backend/data/debug.log with human-readable format
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FILE = DATA_DIR / "debug.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB


class DebugLogger:
    """Structured debug logger for FundIQ"""
    
    def __init__(self, log_file: str = None):
        self.log_file = log_file or str(LOG_FILE)
        self.logger = logging.getLogger("fundiq_debug")
        self.logger.setLevel(logging.DEBUG)
        
        # File handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # Custom formatter
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Add handler if not already added
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
    
    def _format_data(self, data: Any) -> str:
        """Format complex data for logging"""
        if isinstance(data, (dict, list)):
            try:
                return json.dumps(data, indent=2, default=str)
            except:
                return str(data)
        return str(data)
    
    def log(self, level: str, module: str, message: str, data: Optional[Dict[str, Any]] = None):
        """Log with structured format"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] [{level.upper()}] [{module}] {message}"
        
        if data:
            log_message += f" | {self._format_data(data)}"
        
        # Write to file
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.logger.log(log_level, log_message)
        
        # Also print to console for immediate visibility
        print(log_message)
    
    def log_upload(self, file_name: str, file_type: str, file_size: int, document_id: str):
        """Log file upload event"""
        self.log("INFO", "UPLOAD", f"File uploaded: {file_name}", {
            "file_name": file_name,
            "file_type": file_type,
            "file_size": file_size,
            "document_id": document_id
        })
    
    def log_parse_start(self, document_id: str, file_type: str):
        """Log parse start event"""
        self.log("INFO", "PARSE", f"Starting parse for document {document_id}", {
            "document_id": document_id,
            "file_type": file_type,
            "timestamp": datetime.now().isoformat()
        })
    
    def log_parse_complete(self, document_id: str, rows_extracted: int, parse_time: float):
        """Log parse completion"""
        self.log("INFO", "PARSE", f"Parse completed: {rows_extracted} rows extracted", {
            "document_id": document_id,
            "rows_extracted": rows_extracted,
            "parse_time_seconds": parse_time
        })
    
    def log_anomaly_detection(self, document_id: str, anomalies_count: int, detection_time: float):
        """Log anomaly detection completion"""
        self.log("INFO", "ANOMALY", f"Anomaly detection completed: {anomalies_count} anomalies found", {
            "document_id": document_id,
            "anomalies_count": anomalies_count,
            "detection_time_seconds": detection_time
        })
    
    def log_anomaly(self, anomaly_type: str, severity: str, description: str, row_index: int):
        """Log individual anomaly"""
        self.log("WARNING", "ANOMALY", f"Anomaly detected: {description}", {
            "anomaly_type": anomaly_type,
            "severity": severity,
            "row_index": row_index
        })
    
    def log_error(self, module: str, error: Exception, context: Optional[Dict[str, Any]] = None):
        """Log error with context"""
        self.log("ERROR", module, f"Error: {str(error)}", {
            "error_type": type(error).__name__,
            "context": context or {}
        })
    
    def log_insight_generation(self, document_id: str, insights_count: int):
        """Log insight generation"""
        self.log("INFO", "INSIGHTS", f"Generated {insights_count} insights", {
            "document_id": document_id,
            "insights_count": insights_count
        })
    
    def get_recent_logs(self, lines: int = 100) -> str:
        """Get recent log lines"""
        try:
            with open(self.log_file, 'r') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
        except FileNotFoundError:
            return "No logs found"
        except Exception as e:
            return f"Error reading logs: {str(e)}"


# Global instance
debug_logger = DebugLogger()


