"""
Notes module for Reze.
Allows saving, retrieving, and listing notes per group.
"""

from typing import Optional, List
from reze.database import db

def get_note_content(chat_id: int, name: str) -> Optional[str]:
    return db.get_note(chat_id, name)

def list_notes(chat_id: int) -> List[str]:
    return db.get_notes(chat_id)
