"""
YouTube Uploader Service for Reddit2Shorts

This module provides YouTube video upload functionality with OAuth2 authentication.
"""

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import asyncio
import pickle
import os
import pytz
import requests
import httplib2

from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry
from reddit2shorts.core.exceptions import APIError, ConfigurationError

logger = get_logger(__name__)


class ProxyHTTPClient(httplib2.Http):
    """
    Custom HTTP client that properly handles HTTP proxy with authentication.
    
    Uses requests library (same approach as Gemini uses aiohttp).
    """
    
    def __init__(self, proxy_url: Optional[str] = None, **kwargs):
        """
        Initialize proxy HTTP client.
        
        Args:
            proxy_url: Proxy URL with auth (e.g., "http://user:pass@host:port")
        """
        super().__init__(**kwargs)
        self.proxy_url = proxy_url
        self.session = requests.Session()
        
        # Configure proxy exactly like Gemini does with aiohttp
        if self.proxy_url:
            # Set proxy for session (requests handles auth from URL automatically)
            self.session.proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
            
            logger.debug(f"ProxyHTTPClient configured with proxy (same as Gemini)")
    
    def request(self, uri, method="GET", body=None, headers=None, redirections=5, connection_type=None):
        """
        Make HTTP request using requests library with proxy support.
        
        Same approach as Gemini uses with aiohttp.
        """
        try:
            # Prepare headers
            req_headers = dict(headers) if headers else {}
            
            # Make request using requests library (like Gemini uses aiohttp)
            response = self.session.request(
                method=method,
                url=uri,
                data=body,
                headers=req_headers,
                allow_redirects=(redirections > 0),
                timeout=300
            )
            
            # Convert to httplib2 format
            response_dict = httplib2.Response({
                'status': str(response.status_code),
                'reason': response.reason,
            })
            
            # Copy headers
            for key, value in response.headers.items():
                response_dict[key.lower()] = value
            
            return (response_dict, response.content)
            
        except requests.exceptions.ProxyError as e:
            logger.error(f"ProxyHTTPClient proxy error: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"ProxyHTTPClient request failed: {e}")
            raise
            
        except requests.exceptions.ProxyError as e:
            logger.error(f"ProxyHTTPClient proxy error: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"ProxyHTTPClient request failed: {e}")
            raise


class YouTubeUploader:
    """
    Service for uploading videos to YouTube with OAuth2 authentication.
    
    Handles:
    - OAuth2 authentication flow
    - Token persistence and refresh
    - Video upload with metadata
    - Progress tracking
    """
    
    SCOPES = [
        'https://www.googleapis.com/auth/youtube',  # Manage YouTube account
        'https://www.googleapis.com/auth/youtube.upload',  # Upload videos
        'https://www.googleapis.com/auth/youtube.readonly',  # Read channel info
        'https://www.googleapis.com/auth/youtube.force-ssl',  # Full access
        'https://www.googleapis.com/auth/youtubepartner'  # Partner features (thumbnails, etc.)
    ]
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize YouTube uploader.
        
        Args:
            config: Configuration dictionary with client_secrets_file, token_file, etc.
        """
        self.client_secrets_file = config["client_secrets_file"]
        self.token_file = config.get("token_file", "youtube_token.pkl")  # Changed from credentials_file
        self.default_privacy = config.get("default_privacy", "unlisted")
        self.default_category = config.get("default_category", "22")  # People & Blogs
        self.default_tags = config.get("default_tags", [])
        
        # Proxy configuration
        self.proxy = config.get("proxy", None)  # Format: "http://user:pass@host:port" or "socks5://host:port"
        self.proxy_fallback = config.get("proxy_fallback", None)  # Secondary proxy if primary fails
        
        # Shorts optimization
        self.add_shorts_hashtag = config.get("add_shorts_hashtag", True)
        self.default_hashtags = config.get("default_hashtags", ["#Shorts"])
        
        # Thumbnail
        self.custom_thumbnail_path = config.get("custom_thumbnail_path", None)
        
        # Localization
        self.default_language = config.get("default_language", "en")
        self.default_audio_language = config.get("default_audio_language", "en")
        
        # Scheduled publishing (single video override)
        self.publish_at = config.get("publish_at", None)
        
        # Scheduled publishing configuration (for daily batch mode)
        self.scheduled_publishing = config.get("scheduled_publishing", {})
        
        # Initialize ScheduledPublisher for randomized scheduling
        from reddit2shorts.core.scheduled_publisher import ScheduledPublisher
        self.scheduler = ScheduledPublisher(self.scheduled_publishing)
        
        # Subscriber notification
        self.notify_subscribers = config.get("notify_subscribers", True)
        
        self.credentials = None
        self.youtube = None
        self.logger = logger
        
        # Setup proxy if configured
        if self.proxy:
            from reddit2shorts.utils.proxy import mask_proxy_url
            self.logger.info(f"Proxy configured: {mask_proxy_url(self.proxy)}")
    
    async def authenticate(self):
        """
        Authenticate with YouTube API using OAuth2.
        
        Loads existing credentials if available, refreshes if expired,
        or initiates new OAuth2 flow if needed.
        """
        self.logger.info("Authenticating with YouTube API")
        
        # Validate client secrets file exists
        if not os.path.exists(self.client_secrets_file):
            raise ConfigurationError(
                f"Client secrets file not found: {self.client_secrets_file}"
            )
        
        # Load token from file if exists
        if Path(self.token_file).exists():
            try:
                with open(self.token_file, 'rb') as token:
                    self.credentials = pickle.load(token)
                self.logger.info(f"Loaded existing token from: {self.token_file}")
            except Exception as e:
                self.logger.warning(f"Failed to load token: {e}")
                self.credentials = None
        
        # Refresh or get new credentials
        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                self.logger.info("Refreshing expired credentials")
                try:
                    self.credentials.refresh(Request())
                except Exception as e:
                    self.logger.warning(f"Failed to refresh credentials: {e}")
                    self.credentials = None
            
            if not self.credentials:
                self.logger.info("Starting OAuth2 flow (browser will open)")
                self.logger.info("You will be asked to authorize this app to upload videos")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, self.SCOPES
                )
                self.credentials = flow.run_local_server(port=0)
                self.logger.info("OAuth2 authorization successful!")
            
            # Save token
            try:
                with open(self.token_file, 'wb') as token:
                    pickle.dump(self.credentials, token)
                self.logger.info(f"Token saved to: {self.token_file}")
                self.logger.info("You can copy this file to other machines for reuse")
            except Exception as e:
                self.logger.warning(f"Failed to save token: {e}")
        
        # Build YouTube service with proxy support (with fallback)
        proxy_to_use = self.proxy
        if self.proxy:
            from reddit2shorts.utils.proxy import mask_proxy_url
            # Quick check if primary proxy is alive
            try:
                import requests as _r
                _r.get('https://www.google.com',
                        proxies={'http': self.proxy, 'https': self.proxy},
                        timeout=10)
                self.logger.info(f"Primary proxy OK: {mask_proxy_url(self.proxy)}")
            except Exception as _e:
                self.logger.warning(f"Primary proxy failed: {_e}")
                if self.proxy_fallback:
                    try:
                        _r.get('https://www.google.com',
                                proxies={'http': self.proxy_fallback, 'https': self.proxy_fallback},
                                timeout=10)
                        self.logger.info(f"Fallback proxy OK: {mask_proxy_url(self.proxy_fallback)}")
                        proxy_to_use = self.proxy_fallback
                    except Exception as _e2:
                        self.logger.warning(f"Fallback proxy also failed: {_e2}, trying without proxy")
                        proxy_to_use = None
                else:
                    self.logger.warning("No fallback proxy, trying without proxy")
                    proxy_to_use = None

        if proxy_to_use:
            from reddit2shorts.utils.proxy import mask_proxy_url
            self.logger.info(f"Setting up YouTube with proxy: {mask_proxy_url(proxy_to_use)}")
            http_client = ProxyHTTPClient(proxy_url=proxy_to_use)
            from google_auth_httplib2 import AuthorizedHttp
            authorized_http = AuthorizedHttp(self.credentials, http=http_client)
            self.youtube = build('youtube', 'v3', http=authorized_http)
            self.logger.info("YouTube service created with proxy (using ProxyHTTPClient with requests library)")
        else:
            # Build YouTube service without proxy
            self.youtube = build('youtube', 'v3', credentials=self.credentials)
            self.logger.info("YouTube service created without proxy")
        
        self.logger.info("YouTube authentication successful")
    
    def calculate_publish_time(self, video_index: int) -> Optional[str]:
        """
        Calculate publish time for a video using ScheduledPublisher with randomization.
        
        Args:
            video_index: Index of video in daily batch (0-based)
            
        Returns:
            ISO 8601 UTC timestamp string (e.g., "2026-02-08T21:00:00.000Z"),
            or None if scheduled publishing is disabled
        """
        if not self.scheduler.is_enabled():
            return None
        
        try:
            # Use scheduler to calculate publish time with randomization
            publish_dt = self.scheduler.calculate_publish_time(video_index)
            
            if publish_dt is None:
                return None
            
            # Convert to UTC
            publish_dt_utc = publish_dt.astimezone(pytz.UTC)
            
            # Format as ISO 8601 with milliseconds
            publish_time_str = publish_dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            self.logger.info(f"Video {video_index} scheduled for: {publish_time_str} UTC")
            
            return publish_time_str
            
        except Exception as e:
            self.logger.error(f"Error calculating publish time: {e}")
            return None
    
    def get_schedule_summary(self, total_videos: int) -> Dict[str, Any]:
        """
        Get a summary of the publishing schedule for multiple videos.
        
        Args:
            total_videos: Total number of videos to schedule
            
        Returns:
            Dictionary with schedule information including:
            - total_videos: Total number of videos
            - videos_per_day: Videos scheduled per day
            - total_days: Number of days needed
            - schedule: List of video schedules with dates and times
        """
        if not self.scheduled_publishing.get("enabled", False):
            return {
                "enabled": False,
                "message": "Scheduled publishing is disabled"
            }
        
        try:
            timezone_str = self.scheduled_publishing.get("timezone", "America/New_York")
            videos_per_day = self.scheduled_publishing.get("videos_per_day", 6)
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
            
            # Calculate total days needed
            total_days = (total_videos + videos_per_day - 1) // videos_per_day
            
            # Build schedule
            schedule = []
            days_map = {}
            
            for i in range(total_videos):
                publish_time_utc = self.calculate_publish_time(i)
                if publish_time_utc:
                    # Parse and convert to local timezone
                    dt_utc = datetime.strptime(publish_time_utc, "%Y-%m-%dT%H:%M:%S.%fZ")
                    dt_utc = pytz.UTC.localize(dt_utc)
                    dt_local = dt_utc.astimezone(tz)
                    
                    date_key = dt_local.strftime("%Y-%m-%d")
                    
                    if date_key not in days_map:
                        days_map[date_key] = []
                    
                    days_map[date_key].append({
                        "video_index": i,
                        "video_number": i + 1,
                        "local_time": dt_local.strftime("%H:%M %Z"),
                        "utc_time": publish_time_utc,
                        "date": date_key
                    })
                    
                    schedule.append({
                        "video_index": i,
                        "video_number": i + 1,
                        "local_time": dt_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "utc_time": publish_time_utc,
                        "date": date_key
                    })
            
            return {
                "enabled": True,
                "total_videos": total_videos,
                "videos_per_day": videos_per_day,
                "total_days": total_days,
                "timezone": timezone_str,
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "schedule": schedule,
                "days_breakdown": days_map
            }
            
        except Exception as e:
            self.logger.error(f"Error generating schedule summary: {e}")
            return {
                "enabled": True,
                "error": str(e)
            }
    
    @async_retry(max_attempts=3, delay=5.0)
    async def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        privacy: Optional[str] = None,
        thumbnail_path: Optional[Path] = None,
        publish_at: Optional[str] = None,
        video_index: Optional[int] = None
    ) -> Optional[str]:
        """
        Upload video to YouTube with metadata.
        
        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of tags (optional)
            category: YouTube category ID (optional, defaults to configured value)
            privacy: Privacy status - 'public', 'unlisted', or 'private' (optional)
            thumbnail_path: Path to custom thumbnail (optional, overrides config)
            publish_at: ISO 8601 UTC timestamp for scheduled publishing (optional, overrides config)
            video_index: Index of video in daily batch (0-based, for scheduled publishing calculation)
            
        Returns:
            YouTube video URL if successful, None otherwise
        """
        if not self.youtube:
            await self.authenticate()
        
        # Validate video file exists
        if not video_path.exists():
            raise APIError(f"Video file not found: {video_path}")
        
        self.logger.info(f"Uploading video: {title}")
        
        category = category or self.default_category
        privacy = privacy or self.default_privacy
        tags = tags or self.default_tags.copy()
        
        # Calculate publish time if scheduled publishing enabled and video_index provided
        if publish_at is None and video_index is not None:
            publish_at = self.calculate_publish_time(video_index)
        elif publish_at is None:
            # Check for single video override from config
            publish_at = self.publish_at
        
        # Validate publishAt format and timing
        if publish_at:
            try:
                # Parse ISO 8601 timestamp
                publish_dt = datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                publish_dt = pytz.UTC.localize(publish_dt)
                
                # Check if time is in the future (YouTube requires minimum 2 hours)
                now_utc = datetime.now(pytz.UTC)
                min_publish_time = now_utc + timedelta(hours=2)
                
                if publish_dt < min_publish_time:
                    self.logger.warning(
                        f"publishAt time {publish_at} is too soon (need 2+ hours in future). "
                        f"Uploading as '{privacy}' without scheduling."
                    )
                    publish_at = None
                else:
                    time_until = publish_dt - now_utc
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    self.logger.info(f"Video will be published in {hours}h {minutes}m")
                    
            except ValueError as e:
                self.logger.error(f"Invalid publishAt format '{publish_at}': {e}")
                self.logger.warning("Uploading without scheduling")
                publish_at = None
        
        # Add default hashtags to description (automatically)
        if self.default_hashtags:
            # Check which hashtags are not already in description
            hashtags_to_add = []
            for hashtag in self.default_hashtags:
                # Normalize hashtag (ensure it starts with #)
                if not hashtag.startswith('#'):
                    hashtag = f"#{hashtag}"
                
                # Check if hashtag already exists (case-insensitive)
                if hashtag.lower() not in description.lower():
                    hashtags_to_add.append(hashtag)
            
            # Add missing hashtags to description
            if hashtags_to_add:
                hashtags_line = " ".join(hashtags_to_add)
                # Add separator only if description is not empty
                if description.strip():
                    description = f"{description}\n\n{hashtags_line}"
                else:
                    description = hashtags_line
                self.logger.info(f"Added hashtags to description: {hashtags_line}")
        
        # Validate privacy status
        valid_privacy = ['public', 'unlisted', 'private']
        if privacy not in valid_privacy:
            self.logger.warning(f"Invalid privacy status '{privacy}', using 'unlisted'")
            privacy = 'unlisted'
        
        body = {
            'snippet': {
                'title': title[:100],  # YouTube limit: 100 characters
                'description': description[:5000],  # YouTube limit: 5000 characters
                'tags': tags[:500],  # YouTube limit: 500 tags
                'categoryId': category,
                'defaultLanguage': self.default_language,
                'defaultAudioLanguage': self.default_audio_language
            },
            'status': {
                'privacyStatus': privacy,
                'selfDeclaredMadeForKids': False,
                'license': 'youtube',
                'embeddable': True,
                'publicStatsViewable': True
            }
        }
        
        # Add scheduled publishing if configured
        # ВАЖНО: publishAt работает ТОЛЬКО с privacyStatus: "private"
        # См. https://developers.google.com/youtube/v3/docs/videos?hl=ru
        # "This property can only be set if the video's privacy status is private"
        if publish_at:
            body['status']['publishAt'] = publish_at
            body['status']['privacyStatus'] = 'private'  # ОБЯЗАТЕЛЬНО private для publishAt
            self.logger.info(f"Video will be published at: {publish_at} (uploading as private)")
            self.logger.info(f"YouTube will automatically change to '{privacy}' at scheduled time")
        
        
        media = MediaFileUpload(
            str(video_path),
            chunksize=-1,
            resumable=True,
            mimetype='video/mp4'
        )
        
        loop = asyncio.get_event_loop()
        
        try:
            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media,
                notifySubscribers=self.notify_subscribers  # Notify subscribers about new video
            )
            
            response = await loop.run_in_executor(None, self._execute_upload, request)
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Get actual status from response
            actual_privacy = response.get('status', {}).get('privacyStatus', 'unknown')
            actual_publish_at = response.get('status', {}).get('publishAt', None)
            
            if actual_publish_at:
                self.logger.info(f"✅ Video uploaded successfully (SCHEDULED)")
                self.logger.info(f"   URL: {video_url}")
                self.logger.info(f"   Status: {actual_privacy}")
                self.logger.info(f"   Will publish at: {actual_publish_at}")
            else:
                self.logger.info(f"✅ Video uploaded successfully ({actual_privacy.upper()})")
                self.logger.info(f"   URL: {video_url}")
            
            # Upload custom thumbnail if provided
            thumbnail = thumbnail_path or (Path(self.custom_thumbnail_path) if self.custom_thumbnail_path else None)
            if thumbnail and thumbnail.exists():
                await self._upload_thumbnail(video_id, thumbnail)
            
            return video_url
            
        except Exception as e:
            self.logger.error(f"Error uploading video: {e}")
            raise APIError(f"YouTube upload failed: {e}")
    
    def _execute_upload(self, request):
        """
        Execute upload request with progress tracking.
        
        Args:
            request: YouTube API upload request
            
        Returns:
            Upload response with video ID
        """
        response = None
        try:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.logger.info(f"Upload progress: {progress}%")
            return response
        finally:
            # Ensure media body is properly closed to release file handle
            if hasattr(request, 'media_body') and request.media_body:
                try:
                    if hasattr(request.media_body, 'stream'):
                        request.media_body.stream().close()
                except Exception as e:
                    self.logger.debug(f"Error closing media stream: {e}")
    
    async def _upload_thumbnail(self, video_id: str, thumbnail_path: Path):
        """
        Upload custom thumbnail for video.
        
        Args:
            video_id: YouTube video ID
            thumbnail_path: Path to thumbnail image (1280x720, <2MB, JPG/PNG)
        """
        try:
            self.logger.info(f"Uploading custom thumbnail: {thumbnail_path.name}")
            
            # Validate thumbnail
            if not thumbnail_path.exists():
                self.logger.warning(f"Thumbnail not found: {thumbnail_path}")
                return
            
            # Check file size (YouTube limit: 2MB)
            file_size = thumbnail_path.stat().st_size
            if file_size > 2 * 1024 * 1024:
                self.logger.warning(f"Thumbnail too large: {file_size / 1024 / 1024:.2f}MB (max 2MB)")
                return
            
            media = MediaFileUpload(
                str(thumbnail_path),
                mimetype='image/jpeg',
                resumable=True
            )
            
            loop = asyncio.get_event_loop()
            request = self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=media
            )
            
            await loop.run_in_executor(None, request.execute)
            self.logger.info(f"Custom thumbnail uploaded successfully")
            
        except Exception as e:
            self.logger.warning(f"Failed to upload thumbnail: {e}")
    
    async def get_scheduled_videos(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Get list of scheduled videos from channel.
        
        Args:
            max_results: Maximum number of videos to retrieve (default: 50)
        
        Returns:
            List of scheduled video information
        """
        if not self.youtube:
            await self.authenticate()
        
        try:
            self.logger.info("Fetching scheduled videos from channel...")
            
            loop = asyncio.get_event_loop()
            
            # Get channel's uploads playlist
            channels_response = await loop.run_in_executor(
                None,
                lambda: self.youtube.channels().list(
                    part='contentDetails',
                    mine=True
                ).execute()
            )
            
            if not channels_response.get('items'):
                self.logger.warning("No channel found")
                return []
            
            # Get videos from uploads playlist
            uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            playlist_response = await loop.run_in_executor(
                None,
                lambda: self.youtube.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=uploads_playlist_id,
                    maxResults=max_results
                ).execute()
            )
            
            video_ids = [item['contentDetails']['videoId'] for item in playlist_response.get('items', [])]
            
            if not video_ids:
                self.logger.info("No videos found in channel")
                return []
            
            # Get detailed video information
            videos_response = await loop.run_in_executor(
                None,
                lambda: self.youtube.videos().list(
                    part='snippet,status',
                    id=','.join(video_ids)
                ).execute()
            )
            
            # Filter scheduled videos
            scheduled_videos = []
            for video in videos_response.get('items', []):
                status = video.get('status', {})
                privacy = status.get('privacyStatus')
                publish_at = status.get('publishAt')
                
                if publish_at:  # Video is scheduled
                    scheduled_videos.append({
                        'video_id': video['id'],
                        'title': video['snippet']['title'],
                        'privacy_status': privacy,
                        'publish_at': publish_at,
                        'url': f"https://www.youtube.com/watch?v={video['id']}"
                    })
            
            self.logger.info(f"Found {len(scheduled_videos)} scheduled videos")
            return scheduled_videos
            
        except Exception as e:
            self.logger.error(f"Error fetching scheduled videos: {e}")
            return []
    
    async def update_video_schedule(
        self,
        video_id: str,
        new_publish_at: str,
        new_privacy: Optional[str] = None
    ) -> bool:
        """
        Update scheduled publish time for a video.
        
        Args:
            video_id: YouTube video ID
            new_publish_at: New ISO 8601 UTC timestamp
            new_privacy: New privacy status after publishing (optional)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.youtube:
            await self.authenticate()
        
        try:
            self.logger.info(f"Updating schedule for video {video_id}")
            
            loop = asyncio.get_event_loop()
            
            # Get current video details
            video_response = await loop.run_in_executor(
                None,
                lambda: self.youtube.videos().list(
                    part='snippet,status',
                    id=video_id
                ).execute()
            )
            
            if not video_response.get('items'):
                self.logger.error(f"Video {video_id} not found")
                return False
            
            video = video_response['items'][0]
            
            # Update status
            video['status']['publishAt'] = new_publish_at
            video['status']['privacyStatus'] = 'private'  # Required for publishAt
            
            if new_privacy:
                # This will be the status after publishing
                self.logger.info(f"Video will change to '{new_privacy}' at {new_publish_at}")
            
            # Update video
            await loop.run_in_executor(
                None,
                lambda: self.youtube.videos().update(
                    part='snippet,status',
                    body=video
                ).execute()
            )
            
            self.logger.info(f"✅ Schedule updated successfully")
            self.logger.info(f"   New publish time: {new_publish_at}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating video schedule: {e}")
            return False
