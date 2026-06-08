"""Google Sheets client for storing and tracking Reddit stories.

This module provides a client for interacting with Google Sheets API to store
Reddit stories, track processing status, and manage video metadata.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from reddit2shorts.core.exceptions import APIError
from reddit2shorts.models.reddit import RedditStory
from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry

logger = get_logger(__name__)


class GoogleSheetsClient:
    """Client for interacting with Google Sheets.
    
    This client provides methods to store Reddit stories, check for duplicates,
    and update processing status in Google Sheets.
    
    Attributes:
        credentials: Google OAuth2 credentials
        service: Google Sheets API service
        spreadsheet_id: ID of the target spreadsheet
        worksheet_name: Name of the worksheet to use
        logger: Logger instance
    
    Requirements:
        - 2.1: Save stories to Google Sheets
        - 2.2: Record title, text, author, URL, date, status
        - 2.3: Skip duplicate stories
        - 2.4: Retry on errors
        - 2.5: Use OAuth2 authentication
    """
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    def __init__(
        self,
        credentials_file: str,
        spreadsheet_id: str,
        worksheet_name: str = "Stories"
    ):
        """Initialize Google Sheets client.
        
        Args:
            credentials_file: Path to service account credentials JSON file
            spreadsheet_id: Google Sheets spreadsheet ID
            worksheet_name: Name of the worksheet (default: "Stories")
        
        Raises:
            FileNotFoundError: If credentials file doesn't exist
            APIError: If authentication fails
        
        Example:
            >>> client = GoogleSheetsClient(
            ...     credentials_file="credentials.json",
            ...     spreadsheet_id="1ABC...XYZ",
            ...     worksheet_name="Stories"
            ... )
        """
        try:
            self.credentials = Credentials.from_service_account_file(
                credentials_file,
                scopes=self.SCOPES
            )
            self.service = build('sheets', 'v4', credentials=self.credentials)
            self.spreadsheet_id = spreadsheet_id
            self.worksheet_name = worksheet_name
            self.logger = logger
            self.logger.info(
                f"Google Sheets client initialized for spreadsheet: {spreadsheet_id}"
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Credentials file not found: {credentials_file}"
            ) from e
        except Exception as e:
            raise APIError(f"Failed to initialize Google Sheets client: {e}") from e
    
    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def append_story(
        self,
        story: RedditStory,
        status: str = "pending"
    ) -> bool:
        """Append a story to Google Sheets.
        
        Checks if the story already exists before appending to avoid duplicates.
        
        Args:
            story: RedditStory object to append
            status: Processing status (default: "pending")
        
        Returns:
            True if story was appended, False if it already exists
        
        Raises:
            APIError: If append operation fails after retries
        
        Requirements:
            - 2.1: Save story to Google Sheets
            - 2.2: Record all story metadata
            - 2.3: Skip duplicates
            - 2.4: Retry on errors
        
        Example:
            >>> client = GoogleSheetsClient(creds, sheet_id, "Stories")
            >>> story = RedditStory(...)
            >>> appended = await client.append_story(story)
            >>> print(f"Story appended: {appended}")
        """
        self.logger.info(f"Attempting to append story: {story.id}")
        
        # Check if story already exists
        if await self.story_exists(story.id):
            self.logger.info(f"Story {story.id} already exists, skipping")
            return False
        
        # Prepare row data
        values = [[
            story.id,
            story.title,
            story.text,
            story.author,
            story.url,
            story.score,
            story.created_utc.isoformat(),
            status,
            datetime.now().isoformat(),
            ""  # video_id column (empty initially)
        ]]
        
        body = {'values': values}
        range_name = f"{self.worksheet_name}!A:J"
        
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    valueInputOption='RAW',
                    body=body
                ).execute()
            )
            
            self.logger.info(f"Successfully appended story: {story.id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error appending story {story.id}: {e}")
            raise APIError(f"Failed to append story to Google Sheets: {e}") from e
    
    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def story_exists(self, story_id: str) -> bool:
        """Check if a story already exists in the sheet.
        
        Args:
            story_id: Reddit story ID to check
        
        Returns:
            True if story exists, False otherwise
        
        Raises:
            APIError: If check operation fails after retries
        
        Requirements:
            - 2.3: Check for duplicate stories
        
        Example:
            >>> client = GoogleSheetsClient(creds, sheet_id, "Stories")
            >>> exists = await client.story_exists("abc123")
            >>> print(f"Story exists: {exists}")
        """
        range_name = f"{self.worksheet_name}!A:A"
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name
                ).execute()
            )
            
            values = result.get('values', [])
            exists = any(row and row[0] == story_id for row in values)
            
            self.logger.debug(f"Story {story_id} exists: {exists}")
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking if story exists: {e}")
            raise APIError(f"Failed to check story existence: {e}") from e
    
    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def update_status(
        self,
        story_id: str,
        status: str,
        video_id: Optional[str] = None
    ) -> bool:
        """Update the processing status of a story.
        
        Args:
            story_id: Reddit story ID
            status: New status (e.g., "processing", "completed", "failed")
            video_id: Optional video ID to store
        
        Returns:
            True if update was successful, False if story not found
        
        Raises:
            APIError: If update operation fails after retries
        
        Requirements:
            - 2.1: Update story status
            - 2.4: Retry on errors
        
        Example:
            >>> client = GoogleSheetsClient(creds, sheet_id, "Stories")
            >>> updated = await client.update_status(
            ...     story_id="abc123",
            ...     status="completed",
            ...     video_id="video_123"
            ... )
        """
        self.logger.info(
            f"Updating status for story {story_id}: {status}"
        )
        
        # Find the row with this story_id
        range_name = f"{self.worksheet_name}!A:J"
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name
                ).execute()
            )
            
            values = result.get('values', [])
            
            # Find the row index
            row_index = None
            for i, row in enumerate(values):
                if row and row[0] == story_id:
                    row_index = i + 1  # Sheets uses 1-based indexing
                    break
            
            if row_index is None:
                self.logger.warning(f"Story {story_id} not found in sheet")
                return False
            
            # Update the status and video_id columns
            update_range = f"{self.worksheet_name}!H{row_index}:J{row_index}"
            update_values = [[
                status,
                datetime.now().isoformat(),
                video_id or ""
            ]]
            
            await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=update_range,
                    valueInputOption='RAW',
                    body={'values': update_values}
                ).execute()
            )
            
            self.logger.info(
                f"Successfully updated status for story {story_id}"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating status for story {story_id}: {e}")
            raise APIError(f"Failed to update story status: {e}") from e
    
    @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_pending_stories(
        self,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all stories with 'pending' status.
        
        Args:
            limit: Maximum number of stories to return (None for all)
        
        Returns:
            List of story dictionaries with keys: id, title, text, author, url, score
        
        Raises:
            APIError: If fetch operation fails after retries
        
        Example:
            >>> client = GoogleSheetsClient(creds, sheet_id, "Stories")
            >>> pending = await client.get_pending_stories(limit=5)
            >>> for story in pending:
            ...     print(story['id'])
        """
        self.logger.info("Fetching pending stories from Google Sheets")
        
        range_name = f"{self.worksheet_name}!A:J"
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name
                ).execute()
            )
            
            values = result.get('values', [])
            
            # Skip header row and filter for pending status
            pending_stories = []
            for row in values[1:]:  # Skip header
                if len(row) >= 8 and row[7] == "pending":
                    story_dict = {
                        'id': row[0],
                        'title': row[1],
                        'text': row[2],
                        'author': row[3],
                        'url': row[4],
                        'score': int(row[5]) if row[5] else 0,
                        'created_utc': row[6],
                        'status': row[7]
                    }
                    pending_stories.append(story_dict)
                    
                    if limit and len(pending_stories) >= limit:
                        break
            
            self.logger.info(f"Found {len(pending_stories)} pending stories")
            return pending_stories
            
        except Exception as e:
            self.logger.error(f"Error fetching pending stories: {e}")
            raise APIError(f"Failed to fetch pending stories: {e}") from e
    
    async def initialize_sheet(self) -> bool:
        """Initialize the sheet with headers if it's empty.
        
        Creates the header row with column names if the sheet is empty.
        
        Returns:
            True if headers were added, False if sheet already has data
        
        Raises:
            APIError: If initialization fails
        
        Example:
            >>> client = GoogleSheetsClient(creds, sheet_id, "Stories")
            >>> initialized = await client.initialize_sheet()
        """
        self.logger.info("Checking if sheet needs initialization")
        
        range_name = f"{self.worksheet_name}!A1:J1"
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name
                ).execute()
            )
            
            values = result.get('values', [])
            
            # If sheet is empty or doesn't have headers, add them
            if not values or not values[0]:
                headers = [[
                    'id',
                    'title',
                    'content',
                    'author',
                    'url',
                    'score',
                    'created_at',
                    'status',
                    'updated_at',
                    'video_id'
                ]]
                
                await loop.run_in_executor(
                    None,
                    lambda: self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_name,
                        valueInputOption='RAW',
                        body={'values': headers}
                    ).execute()
                )
                
                self.logger.info("Sheet initialized with headers")
                return True
            
            self.logger.info("Sheet already has headers")
            return False
            
        except Exception as e:
            self.logger.error(f"Error initializing sheet: {e}")
            raise APIError(f"Failed to initialize sheet: {e}") from e
