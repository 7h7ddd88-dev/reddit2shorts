"""
Base Orchestrator for all video generation flows.

Provides common functionality:
- Service initialization
- Utility methods
- Workflow patterns
- Dry-run support
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime
import shutil
import time

from reddit2shorts.utils.logger import get_logger


class BaseOrchestrator(ABC):
    """
    Base class for all orchestrators.
    
    Provides:
    - Automatic service initialization
    - Common utility methods
    - Standard workflow patterns
    - Dry-run mode support
    """
    
    def __init__(self, config: Dict[str, Any], flow_name: str, dry_run: bool = False):
        """
        Initialize base orchestrator.
        
        Args:
            config: Full configuration from config.yaml
            flow_name: Name of the flow (knights, darkmotiv, brainrot, etc.)
            dry_run: If True, skip YouTube upload
        """
        self.config = config
        self.flow_name = flow_name
        self.dry_run = dry_run
        self.logger = get_logger(f"{self.__class__.__name__}")
        
        # Initialize services
        self._init_services()
        
        self.logger.info(f"{self.__class__.__name__} initialized")
        self.logger.info(f"  Flow: {flow_name}")
        self.logger.info(f"  Dry run: {dry_run}")
    
    def _init_services(self):
        """Initialize all necessary services through ServiceFactory."""
        from reddit2shorts.core.service_factory import ServiceFactory
        from reddit2shorts.core.scheduled_publisher import ScheduledPublisher
        
        # Merge flow-specific video config with global video config
        video_config = self.config.get("video", {}).copy()
        flow_config = self.config.get(self.flow_name, {})
        
        # Override with flow-specific video settings if they exist
        if "end_picture_path" in flow_config:
            video_config["end_picture_path"] = flow_config["end_picture_path"]
            self.logger.info(f"Using flow-specific end_picture_path: {flow_config['end_picture_path']}")
        
        if "end_picture_duration" in flow_config:
            video_config["end_picture_duration"] = flow_config["end_picture_duration"]
        
        # Create video service with merged config
        provider = video_config.get("provider", "moviepy")
        if provider == "moviepy":
            from reddit2shorts.services.video_moviepy import MoviePyVideoService
            self.video_service = MoviePyVideoService(video_config)
        else:
            self.video_service = ServiceFactory.create_video_service(self.config)
        
        self.file_manager = ServiceFactory.create_file_manager(self.config, self.flow_name)
        self.tts_service = ServiceFactory.create_tts_service(self.config, self.flow_name)
        
        # Scheduler for daily batch
        scheduled_config = self.config.get("scheduled_publishing", {})
        self.scheduler = ScheduledPublisher(scheduled_config)
        
        # YouTube uploader (optional for dry-run)
        if not self.dry_run:
            self.youtube_uploader = ServiceFactory.create_youtube_uploader(
                self.config, self.flow_name
            )
            self.logger.info("YouTube uploader initialized")
        else:
            self.youtube_uploader = None
            self.logger.info("Dry-run mode: YouTube uploader disabled")
    
    # ========== Helper methods ==========
    
    def _create_llm_service(
        self,
        content_type: str = "",
        art_style: str = ""
    ):
        """
        Создание LLM сервиса для конкретного флоу.
        
        Args:
            content_type: Тип контента для LLM
            art_style: Стиль для генерации изображений
            
        Returns:
            LLMService instance
        """
        from reddit2shorts.services.llm.service import LLMService
        
        # Get LLM config from flow-specific or general config
        flow_config = self.config.get(self.flow_name, {})
        llm_config = flow_config.get("llm", {})
        
        # Check if we should use shared Gemini config
        if llm_config.get("use_shared_gemini", False):
            # Use Gemini configuration from config.gemini
            gemini_config = self.config.get("gemini", {})
            
            # Check if Gemini should use proxy
            use_proxy = gemini_config.get("use_proxy", True)
            default_proxy = self.config.get("default_proxy") if use_proxy else None
            
            if use_proxy and default_proxy:
                self.logger.info(f"Using shared Gemini config with default_proxy: {default_proxy}")
            else:
                self.logger.info("Using shared Gemini config without proxy (direct connection)")
            
            llm_config_full = {
                "max_retries": llm_config.get("max_retries", 10),
                "providers": [{
                    "name": "gemini",
                    "enabled": True,
                    "api_keys": gemini_config.get("api_keys", []),
                    "model": gemini_config.get("model", "gemini-2.5-flash"),
                    "temperature": gemini_config.get("temperature", 0.7),
                    "max_tokens": gemini_config.get("max_tokens", 8000),
                    "proxy": default_proxy  # Will be None if use_proxy=false
                }]
            }
        else:
            # Use general LLM config (Cerebras/OpenRouter) or flow-specific full config
            llm_config_full = llm_config if llm_config.get("providers") else self.config.get("llm", {})
            
            # Add default proxy to all providers if not specified
            if "providers" in llm_config_full:
                default_proxy = self.config.get("default_proxy")
                if default_proxy:
                    for provider in llm_config_full["providers"]:
                        if "proxy" not in provider:
                            provider["proxy"] = default_proxy
        
        if not llm_config_full:
            raise ValueError(f"No LLM config found for flow '{self.flow_name}'")
        
        return LLMService(
            llm_config_full,
            content_type=content_type,
            art_style=art_style
        )
    
    def _create_gemini_llm_service(
        self,
        content_type: str = "motivational speech",
        temperature: float = 0.7,
        max_tokens: int = 8000,
        max_retries: int = 10
    ) -> "LLMService":
        """
        Create LLM service using shared Gemini config with automatic proxy.
        
        This is a convenience method for flows that use Gemini.
        Automatically adds default_proxy from config.
        
        Args:
            content_type: Type of content to generate
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            max_retries: Maximum retry attempts
            
        Returns:
            LLMService instance configured with Gemini
            
        Example:
            >>> self.llm_service = self._create_gemini_llm_service(
            ...     content_type="brainrot viral video",
            ...     temperature=0.8
            ... )
        """
        from reddit2shorts.services.llm.service import LLMService
        
        gemini_config = self.config.get("gemini", {})
        default_proxy = self.config.get("default_proxy")
        
        llm_config = {
            "max_retries": max_retries,
            "providers": [{
                "name": "gemini",
                "enabled": True,
                "api_keys": gemini_config.get("api_keys", []),
                "model": gemini_config.get("model", "gemini-2.5-flash"),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "proxy": default_proxy  # Automatically add default proxy
            }]
        }
        
        self.logger.debug(f"Created Gemini LLM service with proxy: {bool(default_proxy)}")
        
        return LLMService(llm_config, content_type=content_type)
    
    def _create_gemini_llm_config(
        self,
        max_retries: int = 10,
        temperature: float = 0.7,
        max_tokens: int = 8000
    ) -> dict:
        """
        Create LLM config for Gemini with automatic proxy support.
        
        This is a helper method for orchestrators that need to create LLMService manually.
        Automatically adds default_proxy from config.
        
        Args:
            max_retries: Maximum retry attempts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            LLM config dict ready for LLMService
            
        Example:
            >>> llm_config = self._create_gemini_llm_config()
            >>> self.llm_service = LLMService(llm_config)
        """
        gemini_config = self.config.get("gemini", {})
        default_proxy = self.config.get("default_proxy")
        
        return {
            "max_retries": max_retries,
            "providers": [{
                "name": "gemini",
                "enabled": True,
                "api_keys": gemini_config.get("api_keys", []),
                "model": gemini_config.get("model", "gemini-2.5-flash"),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "proxy": default_proxy  # Automatically add proxy
            }]
        }
    
    # ========== Abstract methods (must be implemented in subclasses) ==========
    
    @abstractmethod
    async def create_video(self, **kwargs) -> Any:
        """
        Create a single video.
        
        Must be implemented in each subclass.
        
        Returns:
            WorkflowResult object specific to the flow
        """
        pass
    
    # ========== Common workflow patterns ==========
    
    async def run_workflow(self, num_videos: int = 1, **kwargs) -> List[Any]:
        """
        Run workflow to create multiple videos.
        
        Args:
            num_videos: Number of videos to create
            **kwargs: Additional arguments passed to create_video()
            
        Returns:
            List of workflow results
        """
        results = []
        
        self.logger.info(f"Starting workflow: {num_videos} video(s)")
        
        for i in range(num_videos):
            self.logger.info(f"Creating video {i+1}/{num_videos}")
            
            try:
                result = await self.create_video(**kwargs)
                results.append(result)
                
                if result.success:
                    self.logger.info(f"[OK] Video {i+1}/{num_videos} created successfully")
                else:
                    self.logger.error(f"[FAIL] Video {i+1}/{num_videos} failed")
                    
            except Exception as e:
                self.logger.error(f"[FAIL] Video {i+1}/{num_videos} failed with exception: {e}")
                # Create failed result
                from reddit2shorts.core.state import WorkflowResult
                failed_result = WorkflowResult(
                    success=False,
                    video_id=f"{self.flow_name}_{i}",
                    video_url=None,
                    duration=0,
                    error=str(e)
                )
                results.append(failed_result)
        
        successful = sum(1 for r in results if r.success)
        self.logger.info(f"Workflow complete: {successful}/{num_videos} successful")
        
        return results
    
    async def run_daily_batch(self, **kwargs) -> List[Any]:
        """
        Run daily batch with scheduled publishing.
        
        Args:
            **kwargs: Additional arguments passed to create_video()
            
        Returns:
            List of workflow results
        """
        self.logger.info("Starting daily batch workflow")
        
        # Get number of videos from config
        flow_config = self.config.get(self.flow_name, {})
        num_videos = flow_config.get("videos_per_day", 1)
        
        # Create videos
        results = await self.run_workflow(num_videos=num_videos, **kwargs)
        
        # Schedule publishing if not dry-run
        if not self.dry_run and self.youtube_uploader:
            self.logger.info("Scheduling video publishing")
            
            for i, result in enumerate(results):
                if result.success and hasattr(result, 'video_url'):
                    publish_time = self.scheduler.calculate_publish_time(i)
                    self.logger.info(f"Video {i+1} scheduled for: {publish_time}")
        
        return results
    
    # ========== Common utility methods ==========
    
    def _cleanup_temp_files(self, video_id: str):
        """
        Clean up temporary files for a specific video.
        Delegates to FileManager.cleanup_workflow().
        
        Args:
            video_id: Video identifier
        """
        self.file_manager.cleanup_workflow(video_id)
    
    def _cleanup_old_temp_dirs(self, max_age_hours: int = 24):
        """
        Clean up old temporary directories.
        Delegates to FileManager.cleanup_old_temp_files().
        
        Args:
            max_age_hours: Maximum age in hours before cleanup (default: 24)
        """
        # Convert hours to days for FileManager
        days = max_age_hours / 24.0
        self.file_manager.cleanup_old_temp_files(days=days)
    
    def _get_audio_duration(self, audio_path: Path) -> float:
        """
        Get duration of audio file.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Duration in seconds
        """
        from moviepy import AudioFileClip
        
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        audio.close()
        
        return duration
    
    async def _extract_audio_segment(
        self,
        audio_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float
    ) -> float:
        """
        Extract a segment from audio file.
        
        Args:
            audio_path: Source audio file
            output_path: Output audio file
            start_time: Start time in seconds
            end_time: End time in seconds
            
        Returns:
            Actual duration of extracted segment in seconds
        """
        from moviepy import AudioFileClip
        
        audio = AudioFileClip(str(audio_path))
        
        # Clamp end_time to audio duration to avoid errors
        actual_end_time = min(end_time, audio.duration)
        
        segment = audio.subclipped(start_time, actual_end_time)
        segment.write_audiofile(str(output_path), logger=None)
        
        # Get actual duration of extracted segment
        actual_duration = segment.duration
        
        audio.close()
        segment.close()
        
        return actual_duration
    
    def _create_video_title(self, script: Any, max_length: int = 100) -> str:
        """
        Create video title from script.
        
        Args:
            script: Generated script object
            max_length: Maximum title length
            
        Returns:
            Video title
        """
        # Try to get title from script
        if hasattr(script, 'title') and script.title:
            return script.title[:max_length]
        
        # Fallback: use first segment text
        if hasattr(script, 'segments') and script.segments:
            first_text = script.segments[0].text
            return first_text[:max_length]
        
        # Last resort: generic title
        return f"{self.flow_name.title()} Video"
    
    def _create_video_description(
        self,
        script: Any,
        hashtags: Optional[List[str]] = None
    ) -> str:
        """
        Create video description.
        
        Args:
            script: Generated script object
            hashtags: List of hashtags to include
            
        Returns:
            Video description
        """
        description_parts = []
        
        # Add description from script if available
        if hasattr(script, 'description') and script.description:
            description_parts.append(script.description)
        
        # Add hashtags
        if hashtags:
            hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
            description_parts.append(f"\n\n{hashtag_str}")
        
        return "\n".join(description_parts) if description_parts else ""
    
    def _generate_video_id(self) -> str:
        """
        Generate unique video ID.
        
        Returns:
            Video ID string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.flow_name}_{timestamp}"

    
    async def _run_daily_batch_base(self, create_video_func):
        """
        Базовая реализация daily batch с scheduled publishing.
        
        Args:
            create_video_func: Async функция для создания одного видео (принимает video_index)
            
        Returns:
            Список результатов
        """
        scheduled_config = self.config.get("scheduled_publishing", {})
        
        if not scheduled_config.get("enabled", False):
            self.logger.error(f"Scheduled publishing is not enabled for {self.flow_name}")
            return []
        
        num_videos = scheduled_config.get("videos_per_day", 6)
        
        self.logger.info("="*80)
        self.logger.info(f"{self.flow_name.upper()} DAILY BATCH: Creating {num_videos} videos with scheduled publishing")
        self.logger.info("="*80)
        
        # Clear scheduler cache and set seed for this flow
        self.youtube_uploader.scheduler.clear_cache()
        flow_seed = hash(self.flow_name) % (2**31)  # Consistent seed for this flow
        
        # Calculate and log schedule
        schedule = self.youtube_uploader.scheduler.calculate_batch_schedule(num_videos, seed=flow_seed)
        self.logger.info(f"\nScheduled publish times (randomized for {self.flow_name}):")
        for entry in schedule:
            if not entry.get("publish_immediately"):
                self.logger.info(f"  Video {entry['video_index'] + 1}: {entry['formatted_time']}")
        
        # Аутентификация
        await self.youtube_uploader.authenticate()
        
        # Создание видео
        results = []
        
        for i in range(num_videos):
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"Processing video {i+1}/{num_videos}")
            self.logger.info(f"{'='*80}\n")
            
            try:
                result = await create_video_func(i)
                results.append(result)
                
                if result.success:
                    self.logger.info(f"[OK] Video {i+1}/{num_videos} completed")
                else:
                    self.logger.warning(f"[FAIL] Video failed: {result.error}")
                    
            except Exception as e:
                self.logger.error(f"Error creating video {i+1}: {e}")
                # Import WorkflowResult from state module
                from reddit2shorts.core.state import WorkflowResult
                
                results.append(WorkflowResult(
                    success=False,
                    video_id=f"{self.flow_name}_{i}",
                    error=str(e)
                ))
        
        # Summary
        successful = sum(1 for r in results if r.success)
        self.logger.info("\n" + "="*80)
        self.logger.info(f"{self.flow_name.upper()} DAILY BATCH COMPLETE")
        self.logger.info("="*80)
        self.logger.info(f"[OK] Successful: {successful}/{num_videos}")
        self.logger.info(f"[FAIL] Failed: {len(results) - successful}")
        
        # Показать scheduled publish times ТОЛЬКО для успешно загруженных видео
        if successful > 0:
            self.logger.info("\n📅 SCHEDULED PUBLISH TIMES:")
            successful_count = 0
            for i, result in enumerate(results):
                if result.success and hasattr(result, 'video_url') and result.video_url:
                    publish_time = self.youtube_uploader.calculate_publish_time(i)
                    if publish_time:
                        successful_count += 1
                        self.logger.info(f"   Video {successful_count}: {publish_time} - {result.video_url}")
        
        self.logger.info("="*80 + "\n")
        
        return results
