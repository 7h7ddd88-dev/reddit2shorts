"""Reddit client for fetching stories from Reddit.

This module provides a client for interacting with the Reddit API using either:
1. PRAW (Python Reddit API Wrapper) - requires authentication
2. Public JSON API - no authentication required (как в n8n)

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime

# PRAW is optional - only needed for PRAW mode
try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False

from reddit2shorts.models.reddit import RedditStory
from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry

logger = get_logger(__name__)


class RedditClient:
    """Client for fetching stories from Reddit.
    
    This client supports two modes:
    1. PRAW mode - uses official Reddit API with authentication
    2. Public API mode - uses public JSON endpoint (как n8n workflow)
    
    Attributes:
        reddit: PRAW Reddit instance (if using PRAW mode)
        use_public_api: Whether to use public API instead of PRAW
        logger: Logger instance for this client
    
    Requirements:
        - 1.1: Fetch posts from specified subreddit
        - 1.2: Extract title, text, author, URL
        - 1.3: Filter stories by quality criteria
        - 1.4: Return list of valid stories
        - 1.5: Retry on API errors with exponential backoff
    """
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: str = "reddit2shorts/1.0",
        use_public_api: bool = False
    ):
        """Initialize Reddit client.
        
        Args:
            client_id: Reddit API client ID (required if use_public_api=False)
            client_secret: Reddit API client secret (required if use_public_api=False)
            user_agent: User agent string for API requests
            use_public_api: If True, use public JSON API (no auth required, как n8n)
        
        Example:
            >>> # Public API mode (как n8n)
            >>> client = RedditClient(use_public_api=True)
            
            >>> # PRAW mode (с аутентификацией)
            >>> client = RedditClient(
            ...     client_id="your_client_id",
            ...     client_secret="your_client_secret",
            ...     use_public_api=False
            ... )
        """
        self.use_public_api = use_public_api
        self.user_agent = user_agent
        self.logger = logger
        
        if use_public_api:
            self.reddit = None
            self.logger.info("Reddit client initialized in PUBLIC API mode (как n8n)")
        else:
            if not PRAW_AVAILABLE:
                raise ImportError(
                    "PRAW library is required for PRAW mode. "
                    "Install it with: pip install praw"
                )
            if not client_id or not client_secret:
                raise ValueError("client_id and client_secret required when use_public_api=False")
            
            self.reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent
            )
            self.logger.info("Reddit client initialized in PRAW mode")
    
    @async_retry(max_attempts=3, delay=2.0, backoff=2.0)
    async def fetch_stories(
        self,
        subreddit: str,
        limit: int = 10,
        min_score: int = 100,
        min_length: int = 200,
        max_length: Optional[int] = None,
        sort: str = "hot",
        time_filter: str = "month"
    ) -> List[RedditStory]:
        """Fetch stories from a subreddit with quality filtering.
        
        This method fetches posts from the specified subreddit and filters them
        based on quality criteria (score, text length).
        
        Args:
            subreddit: Name of the subreddit to fetch from (e.g., "selfimprovement")
            limit: Maximum number of valid stories to return
            min_score: Minimum score (upvotes - downvotes) required
            min_length: Minimum text length in characters
            max_length: Maximum text length in characters (None for no limit)
            sort: Sort method - "hot", "new", "top", or "rising"
            time_filter: Time filter for "top" sort - "hour", "day", "week", "month", "year", "all"
        
        Returns:
            List of RedditStory objects that meet quality criteria
        
        Raises:
            Exception: If Reddit API returns an error after all retry attempts
        
        Requirements:
            - 1.1: Fetch posts from specified subreddit
            - 1.2: Extract title, text, author, URL
            - 1.3: Filter by quality criteria
            - 1.4: Return list of valid stories
            - 1.5: Retry on API errors
        
        Example:
            >>> client = RedditClient(client_id, client_secret, user_agent)
            >>> stories = await client.fetch_stories(
            ...     subreddit="selfimprovement",
            ...     limit=5,
            ...     min_score=100,
            ...     min_length=200
            ... )
            >>> len(stories) <= 5
            True
        """
        # Route to appropriate implementation based on mode
        if self.use_public_api:
            return await self._fetch_stories_public_api(
                subreddit=subreddit,
                limit=limit,
                min_score=min_score,
                min_length=min_length,
                max_length=max_length,
                sort=sort,
                time_filter=time_filter
            )
        
        # PRAW mode (original implementation)
        self.logger.info(
            f"Fetching stories from r/{subreddit} using PRAW "
            f"(limit={limit}, min_score={min_score}, min_length={min_length})"
        )
        
        # Run PRAW operations in executor to avoid blocking
        loop = asyncio.get_event_loop()
        posts = await loop.run_in_executor(
            None,
            self._fetch_posts_sync,
            subreddit,
            limit,
            sort
        )
        
        # Filter and convert posts to RedditStory objects
        stories = []
        for post in posts:
            # Skip stickied posts
            if post.stickied:
                self.logger.debug(f"Skipping stickied post: {post.id}")
                continue
            
            # Create RedditStory object
            story = self._post_to_story(post)
            
            # Apply quality filtering
            if story.is_valid(
                min_score=min_score,
                min_length=min_length,
                max_length=max_length
            ):
                stories.append(story)
                self.logger.debug(
                    f"Added story: {story.id} (score={story.score}, "
                    f"length={len(story.text)})"
                )
                
                # Stop if we have enough stories
                if len(stories) >= limit:
                    break
            else:
                self.logger.debug(
                    f"Filtered out story: {post.id} "
                    f"(score={post.score}, length={len(post.selftext)})"
                )
        
        self.logger.info(
            f"Fetched {len(stories)} valid stories from r/{subreddit}"
        )
        return stories
    
    def _fetch_posts_sync(
        self,
        subreddit: str,
        limit: int,
        sort: str
    ) -> List:
        """Synchronous method to fetch posts from Reddit.
        
        This method is called via run_in_executor to avoid blocking.
        Fetches more posts than needed to account for filtering.
        
        Args:
            subreddit: Name of the subreddit
            limit: Number of stories needed
            sort: Sort method
        
        Returns:
            List of PRAW Submission objects
        """
        subreddit_obj = self.reddit.subreddit(subreddit)
        
        # Fetch more posts than needed to account for filtering
        # Use 3x multiplier to ensure we get enough valid stories
        fetch_limit = limit * 3
        
        # Get posts based on sort method
        if sort == "hot":
            posts = list(subreddit_obj.hot(limit=fetch_limit))
        elif sort == "new":
            posts = list(subreddit_obj.new(limit=fetch_limit))
        elif sort == "top":
            posts = list(subreddit_obj.top(limit=fetch_limit, time_filter="week"))
        elif sort == "rising":
            posts = list(subreddit_obj.rising(limit=fetch_limit))
        else:
            raise ValueError(f"Invalid sort method: {sort}")
        
        return posts
    
    def _post_to_story(self, post) -> RedditStory:
        """Convert a PRAW Submission to a RedditStory.
        
        Args:
            post: PRAW Submission object
        
        Returns:
            RedditStory object
        
        Requirements:
            - 1.2: Extract title, text, author, URL
        """
        from datetime import datetime
        
        return RedditStory(
            id=post.id,
            title=post.title,
            text=post.selftext,
            author=str(post.author) if post.author else "[deleted]",
            url=f"https://reddit.com{post.permalink}",
            score=post.score,
            created_utc=datetime.fromtimestamp(post.created_utc),
            subreddit=post.subreddit.display_name
        )
    
    async def get_story_by_id(self, story_id: str) -> Optional[RedditStory]:
        """Fetch a specific story by its Reddit ID.
        
        Args:
            story_id: Reddit post ID
        
        Returns:
            RedditStory object if found, None otherwise
        
        Example:
            >>> client = RedditClient(client_id, client_secret, user_agent)
            >>> story = await client.get_story_by_id("abc123")
        """
        self.logger.info(f"Fetching story by ID: {story_id}")
        
        try:
            loop = asyncio.get_event_loop()
            post = await loop.run_in_executor(
                None,
                self.reddit.submission,
                story_id
            )
            
            # Load the submission data
            await loop.run_in_executor(None, lambda: post.selftext)
            
            story = self._post_to_story(post)
            self.logger.info(f"Successfully fetched story: {story_id}")
            return story
            
        except Exception as e:
            self.logger.error(f"Error fetching story {story_id}: {e}")
            return None

    async def _fetch_stories_public_api(
        self,
        subreddit: str,
        limit: int,
        min_score: int,
        min_length: int,
        max_length: Optional[int],
        sort: str,
        time_filter: str
    ) -> List[RedditStory]:
        """Fetch stories using public Reddit JSON API (как n8n).
        
        This method uses the public Reddit JSON endpoint that doesn't require
        authentication, matching the n8n workflow behavior.
        
        Args:
            subreddit: Subreddit name
            limit: Number of stories to fetch
            min_score: Minimum score filter
            min_length: Minimum text length
            max_length: Maximum text length
            sort: Sort method (hot, new, top, rising)
            time_filter: Time filter for top sort
        
        Returns:
            List of filtered RedditStory objects
        """
        # Build URL как в n8n: https://www.reddit.com/r/{subreddit}/top.json?t=month&limit=100
        base_url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
        params = {"limit": limit * 3}  # Fetch more to account for filtering
        
        if sort == "top":
            params["t"] = time_filter
        
        self.logger.info(
            f"Fetching from public API: {base_url} "
            f"(params={params}, как n8n workflow)"
        )
        
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": self.user_agent}
            
            async with session.get(base_url, params=params, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Reddit API error: {response.status} - {error_text}"
                    )
                
                data = await response.json()
        
        # Parse response как n8n: data.children[]
        posts = data.get("data", {}).get("children", [])
        self.logger.info(f"Received {len(posts)} posts from Reddit public API")
        
        # Filter and convert to RedditStory objects
        stories = []
        for post_wrapper in posts:
            post_data = post_wrapper.get("data", {})
            
            # Skip stickied posts
            if post_data.get("stickied", False):
                continue
            
            # Extract fields как в n8n
            story = RedditStory(
                id=post_data.get("id", ""),
                title=post_data.get("title", ""),
                text=post_data.get("selftext", ""),
                author=post_data.get("author", "[deleted]"),
                url=f"https://reddit.com{post_data.get('permalink', '')}",
                score=post_data.get("score", 0),
                created_utc=datetime.fromtimestamp(post_data.get("created_utc", 0)),
                subreddit=post_data.get("subreddit", subreddit)
            )
            
            # Apply quality filtering
            if story.is_valid(
                min_score=min_score,
                min_length=min_length,
                max_length=max_length
            ):
                stories.append(story)
                self.logger.debug(
                    f"Added story: {story.id} (score={story.score}, "
                    f"length={len(story.text)})"
                )
                
                if len(stories) >= limit:
                    break
        
        self.logger.info(
            f"Fetched {len(stories)} valid stories from public API"
        )
        return stories
