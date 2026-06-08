"""
Processed Stories Tracker

Tracks which Reddit stories have been processed to avoid duplicates.
Uses local JSON file for fast lookups + Google Sheets as backup.
"""

import json
from pathlib import Path
from typing import Set, Optional
from datetime import datetime

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class ProcessedTracker:
    """
    Tracks processed story IDs using local JSON file.
    
    Fast local storage for duplicate detection.
    Google Sheets is used as backup/history but not for duplicate checks.
    """
    
    def __init__(self, storage_path: str = "processed_stories.json"):
        """
        Initialize tracker.
        
        Args:
            storage_path: Path to JSON file storing processed IDs
        """
        self.storage_path = Path(storage_path)
        self.processed_ids: Set[str] = set()
        self.logger = logger
        
        # Load existing IDs
        self._load()
    
    def _load(self):
        """Load processed IDs from file."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_ids = set(data.get('processed_ids', []))
                    self.logger.info(f"Loaded {len(self.processed_ids)} processed story IDs")
            except Exception as e:
                self.logger.warning(f"Failed to load processed IDs: {e}")
                self.processed_ids = set()
        else:
            self.logger.info("No existing processed stories file, starting fresh")
            self.processed_ids = set()
    
    def _save(self):
        """Save processed IDs to file."""
        try:
            data = {
                'processed_ids': list(self.processed_ids),
                'last_updated': datetime.now().isoformat(),
                'total_count': len(self.processed_ids)
            }
            
            # Create parent directory if needed
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to temp file first, then rename (atomic operation)
            temp_path = self.storage_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            temp_path.replace(self.storage_path)
            self.logger.debug(f"Saved {len(self.processed_ids)} processed story IDs")
            
        except Exception as e:
            self.logger.error(f"Failed to save processed IDs: {e}")
    
    def is_processed(self, story_id: str) -> bool:
        """
        Check if story has been processed.
        
        Args:
            story_id: Reddit story ID
            
        Returns:
            True if story was already processed
        """
        return story_id in self.processed_ids
    
    def mark_processed(self, story_id: str):
        """
        Mark story as processed.
        
        Args:
            story_id: Reddit story ID
        """
        if story_id not in self.processed_ids:
            self.processed_ids.add(story_id)
            self._save()
            self.logger.info(f"Marked story {story_id} as processed")
    
    def get_count(self) -> int:
        """
        Get total count of processed stories.
        
        Returns:
            Number of processed stories
        """
        return len(self.processed_ids)
    
    def clear(self):
        """Clear all processed IDs (use with caution!)."""
        self.processed_ids.clear()
        self._save()
        self.logger.warning("Cleared all processed story IDs")
    
    def remove(self, story_id: str) -> bool:
        """
        Remove story from processed list.
        
        Args:
            story_id: Reddit story ID
            
        Returns:
            True if story was removed, False if not found
        """
        if story_id in self.processed_ids:
            self.processed_ids.remove(story_id)
            self._save()
            self.logger.info(f"Removed story {story_id} from processed list")
            return True
        return False
