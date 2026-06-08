"""
Scheduled Publishing Logic

This module handles scheduled publishing for all flows,
calculating publish times based on configuration with randomization.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import pytz
import random

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class ScheduledPublisher:
    """
    Handles scheduled publishing logic for YouTube videos.
    
    Calculates publish times with randomization to appear more natural:
    - First video: random time in window (e.g., 15:50-16:10)
    - Subsequent videos: random intervals (e.g., 65-97 minutes)
    """
    
    def __init__(self, scheduled_config: Dict[str, Any]):
        """
        Initialize scheduled publisher.
        
        Args:
            scheduled_config: Scheduled publishing configuration
                Expected keys:
                - enabled: bool
                - timezone: str (e.g., "America/New_York")
                - start_time_window: dict with "start" and "end" (e.g., {"start": "15:50", "end": "16:10"})
                  OR legacy start_time: str (e.g., "16:00")
                - interval_minutes: dict with "min" and "max" (e.g., {"min": 65, "max": 97})
                  OR legacy interval_minutes: int (e.g., 75)
                - videos_per_day: int
        """
        self.config = scheduled_config
        self.enabled = scheduled_config.get("enabled", False)
        self.timezone_str = scheduled_config.get("timezone", "America/New_York")
        self.videos_per_day = scheduled_config.get("videos_per_day", 6)
        
        # Parse start time window (with backward compatibility)
        start_time_window = scheduled_config.get("start_time_window")
        if start_time_window and isinstance(start_time_window, dict):
            self.start_time_window = start_time_window
        else:
            # Legacy: single start_time
            legacy_start = scheduled_config.get("start_time", "16:00")
            self.start_time_window = {"start": legacy_start, "end": legacy_start}
        
        # Parse interval range (with backward compatibility)
        interval_minutes = scheduled_config.get("interval_minutes")
        if isinstance(interval_minutes, dict):
            self.interval_range = interval_minutes
        elif isinstance(interval_minutes, int):
            # Legacy: fixed interval
            self.interval_range = {"min": interval_minutes, "max": interval_minutes}
        else:
            # Default
            self.interval_range = {"min": 65, "max": 97}
        
        # Parse timezone
        try:
            self.timezone = pytz.timezone(self.timezone_str)
        except Exception as e:
            logger.warning(f"Invalid timezone {self.timezone_str}, using UTC: {e}")
            self.timezone = pytz.UTC
        
        # Cache for batch schedules (to ensure consistency within a batch)
        self._batch_schedule_cache: Optional[List[datetime]] = None
    
    def is_enabled(self) -> bool:
        """Check if scheduled publishing is enabled."""
        return self.enabled
    
    def _parse_time(self, time_str: str) -> tuple[int, int]:
        """Parse time string to (hour, minute) tuple."""
        hour, minute = map(int, time_str.split(":"))
        return hour, minute
    
    def _get_random_start_time(self, base_date: datetime) -> datetime:
        """
        Get random start time within configured window.
        
        Args:
            base_date: Base datetime to use for date
        
        Returns:
            Random datetime within start time window
        """
        start_hour, start_minute = self._parse_time(self.start_time_window["start"])
        end_hour, end_minute = self._parse_time(self.start_time_window["end"])
        
        # Convert to minutes since midnight
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute
        
        # Random minutes within window
        random_minutes = random.randint(start_minutes, end_minutes)
        
        # Convert back to hour and minute
        hour = random_minutes // 60
        minute = random_minutes % 60
        
        return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    def _get_random_interval(self) -> int:
        """Get random interval in minutes within configured range."""
        return random.randint(self.interval_range["min"], self.interval_range["max"])
    
    def calculate_publish_time(self, video_index: Optional[int] = None) -> Optional[datetime]:
        """
        Calculate publish time for a video with randomization.
        
        Args:
            video_index: Index of video in batch (0-based)
                        If None, returns None (immediate publish)
        
        Returns:
            Datetime for scheduled publish, or None for immediate publish
        """
        if not self.enabled:
            return None
        
        if video_index is None:
            return None
        
        # Use cached batch schedule if available
        if self._batch_schedule_cache and video_index < len(self._batch_schedule_cache):
            cached_time = self._batch_schedule_cache[video_index]
            # Verify cached time is still in the future
            now = datetime.now(self.timezone)
            if cached_time > now:
                return cached_time
            else:
                logger.warning(f"Cached time {cached_time} is in the past, recalculating")
                # Clear cache and recalculate
                self._batch_schedule_cache = None
        
        try:
            # Get current time in target timezone
            now = datetime.now(self.timezone)
            
            # YouTube requires minimum 2 hours in the future for scheduled publishing
            min_publish_time = now + timedelta(hours=2, minutes=5)  # Add 5 min buffer
            
            # Get random start time for first video
            publish_time = self._get_random_start_time(now)
            
            # Add random intervals for subsequent videos
            for i in range(video_index):
                interval = self._get_random_interval()
                publish_time += timedelta(minutes=interval)
            
            # If calculated time is too soon or in the past, schedule for next day
            if publish_time <= min_publish_time:
                logger.info(f"Calculated time {publish_time} is too soon (need 2+ hours), scheduling for next day")
                publish_time = self._get_random_start_time(now + timedelta(days=1))
                for i in range(video_index):
                    interval = self._get_random_interval()
                    publish_time += timedelta(minutes=interval)
            
            logger.info(f"Video {video_index + 1} scheduled for: {publish_time.strftime('%Y-%m-%d %H:%M %Z')}")
            
            return publish_time
            
        except Exception as e:
            logger.error(f"Error calculating publish time: {e}")
            return None
    
    def calculate_batch_schedule(self, num_videos: int, seed: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Calculate publish schedule for a batch of videos with randomization.
        Each flow gets its own random schedule.
        
        Args:
            num_videos: Number of videos in batch
            seed: Optional random seed for reproducibility (use flow name hash for consistency)
        
        Returns:
            List of schedule entries with video index and publish time
        """
        if not self.enabled:
            return [
                {
                    "video_index": i,
                    "publish_time": None,
                    "publish_immediately": True
                }
                for i in range(num_videos)
            ]
        
        # Set random seed if provided (for flow-specific randomization)
        if seed is not None:
            random.seed(seed)
        
        schedule = []
        
        try:
            # Get current time in target timezone
            now = datetime.now(self.timezone)
            
            # Get random start time for first video (uses TODAY's date with time from config window)
            publish_time = self._get_random_start_time(now)
            
            # If start time is in the past (e.g., it's already 17:00 but window is 15:50-16:10),
            # publish first video ASAP (now + 10 minutes buffer for video creation)
            if publish_time <= now:
                buffer_minutes = 10  # Minimum time for video creation
                publish_time = now + timedelta(minutes=buffer_minutes)
                logger.info(f"Start time window has passed, scheduling first video for {publish_time.strftime('%H:%M')} (now + {buffer_minutes} min)")
            
            # Cache the schedule for this batch
            self._batch_schedule_cache = []
            
            # Calculate schedule for each video
            for i in range(num_videos):
                schedule.append({
                    "video_index": i,
                    "publish_time": publish_time,
                    "publish_immediately": False,
                    "formatted_time": publish_time.strftime("%Y-%m-%d %H:%M %Z")
                })
                
                self._batch_schedule_cache.append(publish_time)
                
                # Calculate next video time with random interval
                if i < num_videos - 1:
                    interval = self._get_random_interval()
                    publish_time += timedelta(minutes=interval)
                    logger.debug(f"Video {i+1} -> {i+2}: +{interval} minutes")
            
            # Reset random seed
            if seed is not None:
                random.seed()
            
            return schedule
            
        except Exception as e:
            logger.error(f"Error calculating batch schedule: {e}")
            # Reset random seed on error
            if seed is not None:
                random.seed()
            # Return immediate publish schedule as fallback
            return [
                {
                    "video_index": i,
                    "publish_time": None,
                    "publish_immediately": True,
                    "error": str(e)
                }
                for i in range(num_videos)
            ]
    
    def clear_cache(self):
        """Clear cached batch schedule (call when starting new batch)."""
        self._batch_schedule_cache = None
    
    def get_schedule_summary(self) -> Dict[str, Any]:
        """
        Get summary of scheduling configuration.
        
        Returns:
            Dictionary with schedule configuration details
        """
        if not self.enabled:
            return {
                "enabled": False,
                "message": "Scheduled publishing is disabled"
            }
        
        try:
            now = datetime.now(self.timezone)
            
            # Calculate example schedule
            example_schedule = self.calculate_batch_schedule(self.videos_per_day)
            
            return {
                "enabled": True,
                "timezone": self.timezone_str,
                "start_time_window": self.start_time_window,
                "interval_range": self.interval_range,
                "videos_per_day": self.videos_per_day,
                "example_schedule": [
                    entry["formatted_time"] for entry in example_schedule
                ],
                "note": "Actual times will be randomized for each batch"
            }
            
        except Exception as e:
            return {
                "enabled": True,
                "error": str(e)
            }
