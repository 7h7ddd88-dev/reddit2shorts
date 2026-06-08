"""Reddit data models for the reddit2shorts application.

This module defines data structures for Reddit stories and related functionality.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RedditStory:
    """Represents a Reddit story/post.
    
    Attributes:
        id: Unique Reddit post ID
        title: Post title
        text: Post content/selftext
        author: Reddit username of the author
        url: URL to the Reddit post
        score: Post score (upvotes - downvotes)
        created_utc: Timestamp when the post was created
        subreddit: Name of the subreddit
    """
    
    id: str
    title: str
    text: str
    author: str
    url: str
    score: int
    created_utc: datetime
    subreddit: str
    
    def is_valid(
        self,
        min_score: int = 100,
        min_length: int = 200,
        max_length: Optional[int] = None
    ) -> bool:
        """Check if the story meets quality criteria.
        
        This method validates the story against configurable quality thresholds
        to ensure only suitable content is processed for video creation.
        
        Args:
            min_score: Minimum score (upvotes - downvotes) required
            min_length: Minimum text length in characters
            max_length: Maximum text length in characters (None for no limit)
        
        Returns:
            True if the story meets all quality criteria, False otherwise
        
        Examples:
            >>> story = RedditStory(
            ...     id="abc123",
            ...     title="Great story",
            ...     text="A" * 300,
            ...     author="user123",
            ...     url="https://reddit.com/r/test/abc123",
            ...     score=150,
            ...     created_utc=datetime.now(),
            ...     subreddit="test"
            ... )
            >>> story.is_valid(min_score=100, min_length=200)
            True
            >>> story.is_valid(min_score=200, min_length=200)
            False
        """
        # Check score threshold
        if self.score < min_score:
            return False
        
        # Check text length
        text_length = len(self.text)
        if text_length < min_length:
            return False
        
        if max_length is not None and text_length > max_length:
            return False
        
        # Check for empty or whitespace-only content
        if not self.text.strip():
            return False
        
        if not self.title.strip():
            return False
        
        return True
    
    def to_dict(self) -> dict:
        """Convert the story to a dictionary for serialization.
        
        Returns:
            Dictionary representation of the story
        """
        return {
            'id': self.id,
            'title': self.title,
            'text': self.text,
            'author': self.author,
            'url': self.url,
            'score': self.score,
            'created_utc': self.created_utc.isoformat(),
            'subreddit': self.subreddit
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RedditStory':
        """Create a RedditStory from a dictionary.
        
        Args:
            data: Dictionary containing story data
        
        Returns:
            RedditStory instance
        """
        # Handle datetime conversion
        created_utc = data['created_utc']
        if isinstance(created_utc, str):
            created_utc = datetime.fromisoformat(created_utc)
        
        return cls(
            id=data['id'],
            title=data['title'],
            text=data['text'],
            author=data['author'],
            url=data['url'],
            score=data['score'],
            created_utc=created_utc,
            subreddit=data['subreddit']
        )
