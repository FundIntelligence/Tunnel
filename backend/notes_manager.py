"""
Notes Management System for FundIQ MVP
Stores notes in JSON files (document-level and per-anomaly)
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data" / "notes"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class NotesManager:
    """Manages notes for documents and anomalies"""
    
    def __init__(self, notes_dir: str = None):
        self.notes_dir = Path(notes_dir) if notes_dir else DATA_DIR
        self.notes_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_notes_file(self, document_id: str) -> Path:
        """Get notes file path for document"""
        # Sanitize document_id for filename
        safe_id = document_id.replace('/', '_').replace('\\', '_')
        return self.notes_dir / f"{safe_id}.json"
    
    def _load_notes(self, document_id: str) -> List[Dict[str, Any]]:
        """Load notes from file"""
        notes_file = self._get_notes_file(document_id)
        
        if not notes_file.exists():
            return []
        
        try:
            with open(notes_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _save_notes(self, document_id: str, notes: List[Dict[str, Any]]):
        """Save notes to file"""
        notes_file = self._get_notes_file(document_id)
        
        with open(notes_file, 'w') as f:
            json.dump(notes, f, indent=2, default=str)
    
    def get_document_notes(self, document_id: str) -> List[Dict[str, Any]]:
        """Get all notes for a document"""
        all_notes = self._load_notes(document_id)
        # Filter document-level notes (no anomaly_id or anomaly_id is None)
        return [n for n in all_notes if not n.get('anomaly_id')]
    
    def get_anomaly_notes(self, document_id: str, anomaly_id: str = None) -> List[Dict[str, Any]]:
        """Get notes for a specific anomaly or all anomaly notes"""
        all_notes = self._load_notes(document_id)
        anomaly_notes = [n for n in all_notes if n.get('anomaly_id')]
        
        if anomaly_id:
            return [n for n in anomaly_notes if n.get('anomaly_id') == anomaly_id]
        
        return anomaly_notes
    
    def get_all_notes(self, document_id: str) -> List[Dict[str, Any]]:
        """Get all notes (document-level and anomaly) for a document"""
        return self._load_notes(document_id)
    
    def create_note(
        self,
        document_id: str,
        content: str,
        author: str = "system",
        anomaly_id: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new note"""
        notes = self._load_notes(document_id)
        
        note = {
            'id': str(uuid.uuid4()),
            'document_id': document_id,
            'anomaly_id': anomaly_id,
            'parent_id': parent_id,
            'author': author,
            'content': content,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        notes.append(note)
        self._save_notes(document_id, notes)
        
        return note
    
    def get_note(self, document_id: str, note_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific note"""
        notes = self._load_notes(document_id)
        return next((n for n in notes if n.get('id') == note_id), None)
    
    def get_note_replies(self, document_id: str, note_id: str) -> List[Dict[str, Any]]:
        """Get replies to a note (threaded comments)"""
        notes = self._load_notes(document_id)
        return [n for n in notes if n.get('parent_id') == note_id]
    
    def update_note(self, document_id: str, note_id: str, content: str) -> Optional[Dict[str, Any]]:
        """Update an existing note"""
        notes = self._load_notes(document_id)
        
        for note in notes:
            if note.get('id') == note_id:
                note['content'] = content
                note['updated_at'] = datetime.now().isoformat()
                self._save_notes(document_id, notes)
                return note
        
        return None
    
    def delete_note(self, document_id: str, note_id: str) -> bool:
        """Delete a note and its replies"""
        notes = self._load_notes(document_id)
        
        # Find note and its replies
        note_ids_to_delete = {note_id}
        for note in notes:
            if note.get('parent_id') == note_id:
                note_ids_to_delete.add(note.get('id'))
        
        # Remove notes
        notes = [n for n in notes if n.get('id') not in note_ids_to_delete]
        
        self._save_notes(document_id, notes)
        return True
    
    def get_thread(self, document_id: str, note_id: str) -> List[Dict[str, Any]]:
        """Get a note and all its replies (thread)"""
        notes = self._load_notes(document_id)
        
        # Find root note
        root_note = next((n for n in notes if n.get('id') == note_id), None)
        if not root_note:
            return []
        
        # Find all replies
        thread = [root_note]
        parent_ids = {note_id}
        changed = True
        
        while changed:
            changed = False
            for note in notes:
                if note.get('parent_id') in parent_ids and note.get('id') not in [n['id'] for n in thread]:
                    thread.append(note)
                    parent_ids.add(note.get('id'))
                    changed = True
        
        # Sort by creation time
        thread.sort(key=lambda n: n.get('created_at', ''))
        return thread


