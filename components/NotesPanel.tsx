'use client';

import { useState, useEffect } from 'react';
import { MessageSquare, Send, Reply, Trash2, X } from 'lucide-react';

interface Note {
  id: string;
  document_id: string;
  anomaly_id?: string;
  parent_id?: string;
  author: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

interface NotesPanelProps {
  documentId: string;
  anomalyId?: string;
  onClose?: () => void;
}

export default function NotesPanel({ documentId, anomalyId, onClose }: NotesPanelProps) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newNoteContent, setNewNoteContent] = useState('');
  const [newNoteAuthor, setNewNoteAuthor] = useState('system');
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [replyContent, setReplyContent] = useState('');
  const [activeTab, setActiveTab] = useState<'document' | 'anomaly'>(
    anomalyId ? 'anomaly' : 'document'
  );

  useEffect(() => {
    loadNotes();
  }, [documentId, anomalyId]);

  const loadNotes = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch(`http://localhost:8000/documents/${documentId}/notes`);
      if (!response.ok) throw new Error('Failed to load notes');
      const data = await response.json();
      
      // Filter notes based on active tab
      let filteredNotes = data.notes || [];
      if (activeTab === 'anomaly' && anomalyId) {
        filteredNotes = filteredNotes.filter((n: Note) => n.anomaly_id === anomalyId);
      } else if (activeTab === 'document') {
        filteredNotes = filteredNotes.filter((n: Note) => !n.anomaly_id);
      }
      
      setNotes(filteredNotes);
    } catch (err: any) {
      setError(err.message || 'Failed to load notes');
    } finally {
      setLoading(false);
    }
  };

  const createNote = async () => {
    if (!newNoteContent.trim()) return;
    
    try {
      const url = anomalyId
        ? `http://localhost:8000/anomalies/${anomalyId}/notes`
        : `http://localhost:8000/documents/${documentId}/notes`;
      
      const body = anomalyId
        ? { content: newNoteContent, author: newNoteAuthor, document_id: documentId }
        : { content: newNoteContent, author: newNoteAuthor };
      
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      
      if (!response.ok) throw new Error('Failed to create note');
      
      setNewNoteContent('');
      loadNotes();
    } catch (err: any) {
      setError(err.message || 'Failed to create note');
    }
  };

  const createReply = async (parentId: string) => {
    if (!replyContent.trim()) return;
    
    try {
      const response = await fetch(`http://localhost:8000/documents/${documentId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: replyContent,
          author: newNoteAuthor,
          parent_id: parentId
        })
      });
      
      if (!response.ok) throw new Error('Failed to create reply');
      
      setReplyContent('');
      setReplyingTo(null);
      loadNotes();
    } catch (err: any) {
      setError(err.message || 'Failed to create reply');
    }
  };

  const deleteNote = async (noteId: string) => {
    if (!confirm('Delete this note and all replies?')) return;
    
    try {
      // Note: Delete endpoint would need to be added to backend
      // For now, just show error
      setError('Delete functionality requires backend endpoint');
    } catch (err: any) {
      setError(err.message || 'Failed to delete note');
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const getReplies = (noteId: string): Note[] => {
    return notes.filter(n => n.parent_id === noteId);
  };

  const getRootNotes = (): Note[] => {
    return notes.filter(n => !n.parent_id);
  };

  const renderNote = (note: Note, depth: number = 0) => {
    const replies = getReplies(note.id);
    const isReplying = replyingTo === note.id;
    
    return (
      <div key={note.id} className={`mb-4 ${depth > 0 ? 'ml-6 border-l-2 border-gray-200 pl-4' : ''}`}>
        <div className="bg-gray-50 rounded p-3">
          <div className="flex justify-between items-start mb-2">
            <div>
              <span className="font-medium text-sm">{note.author}</span>
              <span className="text-xs text-gray-500 ml-2">{formatDate(note.created_at)}</span>
            </div>
            {onClose && depth === 0 && (
              <button
                onClick={() => deleteNote(note.id)}
                className="text-red-600 hover:text-red-800 text-xs"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
          <p className="text-sm text-gray-700 mb-2">{note.content}</p>
          {depth === 0 && (
            <button
              onClick={() => setReplyingTo(replyingTo === note.id ? null : note.id)}
              className="text-blue-600 hover:text-blue-800 text-xs flex items-center gap-1"
            >
              <Reply className="h-3 w-3" />
              Reply
            </button>
          )}
        </div>
        
        {/* Reply form */}
        {isReplying && (
          <div className="ml-4 mt-2 mb-4">
            <textarea
              value={replyContent}
              onChange={(e) => setReplyContent(e.target.value)}
              placeholder="Write a reply..."
              className="w-full p-2 border rounded text-sm mb-2"
              rows={2}
            />
            <div className="flex gap-2">
              <button
                onClick={() => createReply(note.id)}
                className="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
              >
                <Send className="h-3 w-3 inline mr-1" />
                Send
              </button>
              <button
                onClick={() => {
                  setReplyingTo(null);
                  setReplyContent('');
                }}
                className="px-3 py-1 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        
        {/* Render replies recursively */}
        {replies.map(reply => renderNote(reply, depth + 1))}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="p-4 bg-white rounded-lg shadow">
        <div className="animate-pulse">Loading notes...</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-white rounded-lg shadow">
      {onClose && (
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">Notes</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X className="h-5 w-5" />
          </button>
        </div>
      )}
      
      {!onClose && <h3 className="text-lg font-semibold mb-4">Notes</h3>}

      {/* Tabs */}
      {anomalyId && (
        <div className="flex gap-2 mb-4 border-b">
          <button
            onClick={() => {
              setActiveTab('document');
              loadNotes();
            }}
            className={`px-4 py-2 text-sm font-medium ${activeTab === 'document' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
          >
            Document Notes
          </button>
          <button
            onClick={() => {
              setActiveTab('anomaly');
              loadNotes();
            }}
            className={`px-4 py-2 text-sm font-medium ${activeTab === 'anomaly' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
          >
            Anomaly Notes
          </button>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="mb-4 p-2 bg-red-50 border border-red-200 rounded text-red-800 text-sm">
          {error}
        </div>
      )}

      {/* Notes list */}
      <div className="max-h-96 overflow-y-auto mb-4">
        {getRootNotes().length === 0 ? (
          <p className="text-gray-500 text-sm">No notes yet. Add one below!</p>
        ) : (
          getRootNotes().map(note => renderNote(note))
        )}
      </div>

      {/* New note form */}
      <div className="border-t pt-4">
        <div className="mb-2">
          <input
            type="text"
            value={newNoteAuthor}
            onChange={(e) => setNewNoteAuthor(e.target.value)}
            placeholder="Your name"
            className="w-full p-2 border rounded text-sm mb-2"
          />
        </div>
        <textarea
          value={newNoteContent}
          onChange={(e) => setNewNoteContent(e.target.value)}
          placeholder={`Add a ${activeTab === 'anomaly' ? 'anomaly' : 'document'} note...`}
          className="w-full p-2 border rounded text-sm mb-2"
          rows={3}
        />
        <button
          onClick={createNote}
          disabled={!newNoteContent.trim()}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          <Send className="h-4 w-4" />
          Add Note
        </button>
      </div>
    </div>
  );
}

