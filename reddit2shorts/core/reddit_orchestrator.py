"""
Workflow Orchestrator for Reddit2Shorts

This module coordinates all steps of the video creation workflow:
Reddit → Sheets → LLM → Images → TTS → Video → YouTube
"""

from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, asdict
import asyncio
import signal
import random
from datetime import datetime
import json

from reddit2shorts.services.reddit import RedditClient, RedditStory
from reddit2shorts.services.sheets import GoogleSheetsClient
from reddit2shorts.services.llm.service import LLMService
from reddit2shorts.services.image import ImageGenerator
from reddit2shorts.services.tts.service import TTSService
from reddit2shorts.services.video import VideoService, SubtitleSegment
from reddit2shorts.services.video_local import LocalVideoService
from reddit2shorts.services.video_moviepy import MoviePyVideoService
from reddit2shorts.services.youtube import YouTubeUploader
from reddit2shorts.core.state import WorkflowState, WorkflowStatus
from reddit2shorts.core.registry import OrchestratorRegistry
from reddit2shorts.core.base_orchestrator import BaseOrchestrator
from reddit2shorts.core.mixins import SubtitlesMixin, MusicMixin
from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.file_manager import FileManager
from reddit2shorts.utils.processed_tracker import ProcessedTracker

logger = get_logger(__name__)


@dataclass
class WorkflowResult:
    """Result of processing a single story"""
    success: bool
    story_id: str
    video_url: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0


@OrchestratorRegistry.register(
    flow_name="reddit",
    config_key="reddit",
    cli_command="reddit",
    description="Create videos from Reddit stories"
)
class RedditOrchestrator(SubtitlesMixin, MusicMixin, BaseOrchestrator):
    """
    Orchestrates the complete workflow for creating videos from Reddit stories.
    
    Workflow steps:
    1. Fetch stories from Reddit
    2. Save to Google Sheets
    3. Generate script with LLM
    4. Generate images with Gemini
    5. Generate audio with TTS
    6. Create video with subtitles
    7. Add background music
    8. Upload to YouTube
    """
    
    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        """
        Initialize workflow orchestrator with all services.

        Args:
            config: Complete configuration dictionary
            dry_run: If True, skip YouTube upload and Sheets updates
        """
        # Initialize BaseOrchestrator first
        super().__init__(config, flow_name="reddit", dry_run=dry_run)
        
        from reddit2shorts.core.service_factory import ServiceFactory
        from reddit2shorts.core.scheduled_publisher import ScheduledPublisher

        self.shutdown_requested = False
        self.current_state = None

        # Initialize services using ServiceFactory
        reddit_config = config.get("reddit", {})
        
        # Check if Reddit should use Gemini
        if reddit_config.get("use_gemini", False):
            # Use Gemini for Reddit stories (better quality, structured output)
            self.logger.info("Reddit flow: Using Gemini with Structured Output")
            self.llm_service = self._create_gemini_llm_service(
                content_type="reddit motivational speech",
                temperature=0.7,
                max_tokens=2000,
                max_retries=10
            )
        else:
            # Use Cerebras/OpenRouter (default, more API keys)
            self.logger.info("Reddit flow: Using Cerebras/OpenRouter with JSON mode")
            llm_config = config.get("llm", {})
            self.llm_service = LLMService(llm_config)
        
        self.tts_service = ServiceFactory.create_tts_service(config, "reddit")
        # video_service, file_manager, scheduler, youtube_uploader already initialized by BaseOrchestrator

        # Reddit-specific services
        self.reddit_client = RedditClient(
            client_id=reddit_config.get("client_id"),
            client_secret=reddit_config.get("client_secret"),
            user_agent=reddit_config.get("user_agent", "reddit2shorts/1.0"),
            use_public_api=reddit_config.get("use_public_api", False)
        )

        # Image generator (with automatic proxy support)
        self.image_generator = ServiceFactory.create_image_service(config)

        # Google Sheets is optional (only needed for non-dry-run mode)
        try:
            self.sheets_client = GoogleSheetsClient(
                credentials_file=config["google_sheets"]["credentials_file"],
                spreadsheet_id=config["google_sheets"]["spreadsheet_id"],
                worksheet_name=config["google_sheets"]["worksheet_name"]
            )
        except Exception as e:
            self.logger.warning(f"Google Sheets client initialization failed: {e}")
            self.logger.warning("Google Sheets will not be available (dry-run mode only)")
            self.sheets_client = None

        # Initialize processed stories tracker (local JSON file)
        self.processed_tracker = ProcessedTracker(
            storage_path=config.get("processed_stories_file", "processed_stories.json")
        )

        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()

    def _get_script_schema(self) -> dict:
        """
        Get JSON schema for Reddit stories (3-4 scenes, max 40 seconds for YouTube Shorts).
        
        Returns:
            JSON schema dict for Gemini structured output
        """
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Engaging video title (max 100 characters)"
                },
                "description": {
                    "type": "string",
                    "description": "Video description for YouTube (max 500 characters)"
                },
                "scenes": {
                    "type": "array",
                    "description": "Array of 3-4 scenes forming a complete video under 40 seconds (optimal for YouTube Shorts)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Narration text for this scene (10-12 words maximum, keep it concise)"
                            },
                            "duration": {
                                "type": "number",
                                "description": "Duration of this scene in seconds (8-10 seconds)",
                                "minimum": 8.0,
                                "maximum": 10.0
                            },
                            "image_prompt": {
                                "type": "string",
                                "description": "Detailed prompt for image generation that captures the scene visually"
                            }
                        },
                        "required": ["text", "duration", "image_prompt"]
                    },
                    "minItems": 3,
                    "maxItems": 4
                }
            },
            "required": ["title", "description", "scenes"]
        }
    
    def _create_script_prompt(self, story_title: str, story_text: str) -> str:
        """
        Create prompt for generating Reddit story video script.
        
        Args:
            story_title: Reddit story title
            story_text: Reddit story text
            
        Returns:
            Formatted prompt for Gemini
        """
        art_style = "Create cinematic, high-quality images with dramatic lighting and composition. Use realistic style with emotional depth."
        content_type = "motivational speech"
        
        prompt = f"""You are a professional video script writer specializing in creating engaging short-form content from Reddit stories.

**Story Title:** {story_title}

**Story Content:**
{story_text}

Create a compelling {content_type} video script that:
1. Is UNDER 40 SECONDS when spoken (optimal for YouTube Shorts)
2. Captures the essence and emotion of this story in a CONCISE way
3. Is engaging, emotional, and suitable for short-form video (YouTube Shorts, TikTok)
4. Breaks naturally into 3-4 scenes, each 8-10 seconds long

For each scene provide:
- Narration text (10-12 words MAXIMUM) - what the narrator says, keep it SHORT and PUNCHY
- Duration in seconds (8-10 seconds)
- Image generation prompt - detailed description for creating a cinematic image

**Art Style for Images:**
{art_style}

**CRITICAL REQUIREMENTS:**
- Total duration MUST be 30-40 seconds (NOT 60 seconds!)
- Create EXACTLY 3-4 scenes (no more, no less)
- Each scene 8-10 seconds
- Narration MUST be SHORT: 10-12 words per scene maximum
- Make the narration conversational, engaging, and CONCISE
- Each scene should flow naturally into the next
- Image prompts should be detailed and cinematic
- Focus on the KEY MESSAGE, skip unnecessary details"""

        return prompt


    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_requested = True
            
            # Save current state if processing
            if self.current_state:
                self._save_state(self.current_state.workflow_id, self.current_state)
                self.logger.info("Current state saved")
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _fetch_unprocessed_stories(
        self,
        subreddit: str,
        needed: int,
        max_attempts: int = 5
    ) -> List[RedditStory]:
        """
        Smart fetch: Get unprocessed stories in batches until we have enough.
        
        Optimized algorithm:
        1. Start with batch_size = needed * 2
        2. Fetch batch, filter already processed
        3. If not enough, increase batch_size and fetch more
        4. Continue until we have enough or max_attempts reached
        
        Args:
            subreddit: Subreddit to fetch from
            needed: Number of unprocessed stories needed
            max_attempts: Maximum number of fetch attempts (default: 5)
            
        Returns:
            List of unprocessed stories (up to 'needed' count)
        """
        unprocessed_stories = []
        seen_ids = set()  # Track seen story IDs to avoid duplicates
        total_fetched = 0
        total_filtered = 0
        batch_size = needed * 2  # Start with 2x multiplier
        
        self.logger.info(f"[SEARCH] Smart fetch: Looking for {needed} unprocessed stories from r/{subreddit}")
        
        for attempt in range(1, max_attempts + 1):
            # Check if we have enough
            if len(unprocessed_stories) >= needed:
                break
            
            # Fetch a batch
            self.logger.info(f"  [FETCH] Attempt {attempt}/{max_attempts}: Fetching {batch_size} stories...")
            
            try:
                batch = await self.reddit_client.fetch_stories(
                    subreddit=subreddit,
                    limit=batch_size
                )
            except Exception as e:
                self.logger.error(f"  [FAIL] Error fetching stories: {e}")
                break
            
            if not batch:
                self.logger.warning(f"  [WARN]  No stories returned from Reddit on attempt {attempt}")
                break
            
            total_fetched += len(batch)
            
            # Filter unprocessed stories from this batch
            batch_unprocessed_count = 0
            for story in batch:
                # Skip if already seen (Reddit sometimes returns duplicates)
                if story.id in seen_ids:
                    continue
                
                seen_ids.add(story.id)
                
                # Check if already processed
                if not self.processed_tracker.is_processed(story.id):
                    unprocessed_stories.append(story)
                    batch_unprocessed_count += 1
                else:
                    total_filtered += 1
            
            self.logger.info(
                f"  [OK] Found {batch_unprocessed_count} unprocessed "
                f"(total: {len(unprocessed_stories)}/{needed}, "
                f"filtered: {len(batch) - batch_unprocessed_count})"
            )
            
            # If we have enough, stop
            if len(unprocessed_stories) >= needed:
                break
            
            # Adaptive batch size: If we got very few unprocessed, increase batch size
            unprocessed_rate = batch_unprocessed_count / len(batch) if batch else 0
            
            if unprocessed_rate < 0.3:  # Less than 30% unprocessed
                # Increase batch size more aggressively
                batch_size = int(batch_size * 2)
                self.logger.debug(f"  📈 Low unprocessed rate ({unprocessed_rate:.1%}), increasing batch to {batch_size}")
            elif unprocessed_rate < 0.5:  # Less than 50% unprocessed
                batch_size = int(batch_size * 1.5)
                self.logger.debug(f"  📈 Medium unprocessed rate ({unprocessed_rate:.1%}), increasing batch to {batch_size}")
            
            # Cap batch size at 100 (Reddit API limit)
            batch_size = min(batch_size, 100)
        
        # Summary
        self.logger.info(f"[OK] Smart fetch complete:")
        self.logger.info(f"   [INFO] Total fetched: {total_fetched} stories")
        self.logger.info(f"   [FAIL] Already processed: {total_filtered} stories")
        self.logger.info(f"   [OK] Unprocessed found: {len(unprocessed_stories)} stories")
        
        if len(unprocessed_stories) < needed:
            self.logger.warning(f"[WARN]  Could only find {len(unprocessed_stories)}/{needed} unprocessed stories after {attempt} attempts")
            self.logger.warning(f"[TIP] Try: 1) Clear processed_stories.json, 2) Change time_filter to 'day', 3) Different subreddit")
        
        # Return only what we need
        return unprocessed_stories[:needed]
    
    async def run_workflow(self, num_videos: int = 1, dry_run: bool = False, **kwargs) -> List[WorkflowResult]:
        """
        Run complete workflow for multiple videos.
        
        Args:
            num_videos: Number of videos to create
            dry_run: If True, skip YouTube upload and Sheets updates
            **kwargs: Additional arguments (subreddit, etc.)
            
        Returns:
            List of workflow results
        """
        # Extract subreddit from kwargs or use config default
        subreddit = kwargs.get("subreddit") or self.config["reddit"]["subreddit"]
        
        # Check if scheduled publishing is enabled (используем общую секцию)
        scheduled_config = self.config.get("scheduled_publishing", {})
        
        if scheduled_config.get("enabled", False) and num_videos > 1 and not dry_run:
            # Use scheduled publishing for multiple videos
            self.logger.info(f"Scheduled publishing enabled - using run_daily_batch()")
            return await self.run_daily_batch(**kwargs)
        
        self.logger.info(f"Starting workflow: {num_videos} videos from r/{subreddit}")
        
        # Authenticate YouTube
        if not dry_run:
            await self.youtube_uploader.authenticate()
        
        # Smart fetch: Get unprocessed stories in batches
        stories = await self._fetch_unprocessed_stories(subreddit, num_videos)
        
        if not stories:
            self.logger.error("[FAIL] No unprocessed stories available")
            self.logger.info("[TIP] Solutions:")
            self.logger.info("  1. Clear processed tracker: rm processed_stories.json")
            self.logger.info("  2. Change time_filter in config.yaml to 'week' or 'day'")
            self.logger.info("  3. Try a different subreddit")
            return []
        
        if len(stories) < num_videos:
            self.logger.warning(f"[WARN]  Only {len(stories)} unprocessed stories available, need {num_videos}")
            self.logger.warning(f"Will create {len(stories)} videos instead")
            num_videos = len(stories)
        
        # Process each story
        results = []
        processed = 0
        
        for story in stories:
            if processed >= num_videos:
                break
            
            # Check for shutdown request
            if self.shutdown_requested:
                self.logger.info("Shutdown requested, stopping workflow")
                break
            
            try:
                result = await self.process_story(story, dry_run)
                results.append(result)
                
                if result.success:
                    processed += 1
                    
            except Exception as e:
                self.logger.error(f"Error processing story {story.id}: {e}")
                results.append(WorkflowResult(
                    success=False,
                    story_id=story.id,
                    error=str(e)
                ))
        
        self.logger.info(f"Workflow complete: {processed}/{num_videos} videos created")
        return results
    
    async def create_video(self, dry_run: bool = False, **kwargs) -> WorkflowResult:
        """
        Create a single video from a Reddit story.
        
        This method is required by BaseOrchestrator and provides a simple interface
        for creating one video. It fetches a single unprocessed story and processes it.
        
        Args:
            dry_run: If True, skip YouTube upload and Sheets updates
            **kwargs: Additional arguments (subreddit, etc.)
            
        Returns:
            WorkflowResult with success status and details
        """
        # Extract subreddit from kwargs or use config default
        subreddit = kwargs.get("subreddit") or self.config["reddit"]["subreddit"]
        
        self.logger.info(f"Creating single video from r/{subreddit}")
        
        # Authenticate YouTube if not dry run
        if not dry_run:
            await self.youtube_uploader.authenticate()
        
        # Fetch one unprocessed story
        stories = await self._fetch_unprocessed_stories(subreddit, num_needed=1)
        
        if not stories:
            self.logger.error("[FAIL] No unprocessed stories available")
            return WorkflowResult(
                success=False,
                story_id="unknown",
                error="No unprocessed stories available"
            )
        
        # Process the story
        story = stories[0]
        return await self.process_story(story, dry_run)
    
    async def run_daily_batch(self, **kwargs) -> List[WorkflowResult]:
        """
        Run daily batch workflow with scheduled publishing.
        Creates multiple videos and uploads them with staggered publish times.
        
        Args:
            subreddit: Subreddit to fetch from (optional, uses config default)
            
        Returns:
            List of workflow results
        """
        # Get configuration from reddit.youtube
        scheduled_config = self.config.get("scheduled_publishing", {})
        
        if not scheduled_config.get("enabled", False):
            self.logger.error("Scheduled publishing is not enabled in config")
            return []
        
        num_videos = scheduled_config.get("videos_per_day", 6)
        
        self.logger.info("="*80)
        self.logger.info(f"DAILY BATCH MODE: Creating {num_videos} videos with scheduled publishing")
        self.logger.info("="*80)
        
        # Clear scheduler cache and set seed for this flow
        self.youtube_uploader.scheduler.clear_cache()
        flow_seed = hash("reddit") % (2**31)  # Consistent seed for reddit flow
        
        # Calculate and log schedule
        schedule = self.youtube_uploader.scheduler.calculate_batch_schedule(num_videos, seed=flow_seed)
        self.logger.info("\nScheduled publish times (randomized for reddit):")
        for entry in schedule:
            if not entry.get("publish_immediately"):
                self.logger.info(f"  Video {entry['video_index'] + 1}: {entry['formatted_time']}")
        
        # Authenticate YouTube
        self.logger.info("[AUTH] Authenticating YouTube...")
        await self.youtube_uploader.authenticate()
        self.logger.info("[AUTH] YouTube authentication complete")
        
        # Smart fetch: Get unprocessed stories in batches
        subreddit = kwargs.get("subreddit") or self.config["reddit"]["subreddit"]
        stories = await self._fetch_unprocessed_stories(subreddit, num_videos)
        
        if not stories:
            self.logger.error("[FAIL] No unprocessed stories available")
            self.logger.info("[TIP] Solutions:")
            self.logger.info("  1. Clear processed tracker: rm processed_stories.json")
            self.logger.info("  2. Change time_filter in config.yaml to 'week' or 'day'")
            self.logger.info("  3. Try a different subreddit")
            return []
        
        if len(stories) < num_videos:
            self.logger.warning(f"[WARN]  Only {len(stories)} unprocessed stories available, need {num_videos}")
            self.logger.warning(f"Will create {len(stories)} videos instead")
            num_videos = len(stories)
        
        # Process each story with video index for scheduled publishing
        results = []
        processed = 0
        
        for story in stories:
            if processed >= num_videos:
                break
            
            # Check for shutdown request
            if self.shutdown_requested:
                self.logger.info("Shutdown requested, stopping workflow")
                break
            
            try:
                # Set current video index for scheduled publishing
                self._current_video_index = processed
                
                self.logger.info(f"\n{'='*80}")
                self.logger.info(f"Processing video {processed + 1}/{num_videos}")
                self.logger.info(f"{'='*80}\n")
                
                result = await self.process_story(story, dry_run=False)
                results.append(result)
                
                if result.success:
                    processed += 1
                    self.logger.info(f"[OK] Video {processed}/{num_videos} completed")
                else:
                    self.logger.warning(f"[FAIL] Video failed: {result.error}")
                    
            except Exception as e:
                self.logger.error(f"Error processing story {story.id}: {e}")
                results.append(WorkflowResult(
                    success=False,
                    story_id=story.id,
                    error=str(e)
                ))
            finally:
                # Clear video index
                self._current_video_index = None
        
        # Summary
        self.logger.info("\n" + "="*80)
        self.logger.info("DAILY BATCH COMPLETE")
        self.logger.info("="*80)
        self.logger.info(f"[OK] Successful: {processed}/{num_videos}")
        self.logger.info(f"[FAIL] Failed: {len(results) - processed}")
        
        # Show scheduled publish times
        if processed > 0:
            self.logger.info("\n[SCHEDULE] SCHEDULED PUBLISH TIMES:")
            for i in range(processed):
                publish_time = self.youtube_uploader.calculate_publish_time(i)
                if publish_time:
                    self.logger.info(f"   Video {i+1}: {publish_time}")
        
        self.logger.info("="*80 + "\n")
        
        return results
    
    async def process_story(
        self, 
        story: RedditStory, 
        dry_run: bool = False
    ) -> WorkflowResult:
        """
        Process single story through complete pipeline.
        
        Args:
            story: Reddit story to process
            dry_run: If True, skip YouTube upload and Sheets updates
            
        Returns:
            Workflow result with success status and details
        """
        start_time = datetime.now()
        workflow_id = f"{story.id}_{int(start_time.timestamp())}"
        
        self.logger.info(f"Processing story: {story.title}")
        
        # Create workflow state
        state = WorkflowState(
            workflow_id=workflow_id,
            story_id=story.id,
            status=WorkflowStatus.PENDING,
            current_step="starting"
        )
        
        # Store current state for signal handler
        self.current_state = state
        
        try:
            # Step 1: Save to Google Sheets
            self.logger.info("Step 1: Saving to Google Sheets")
            state.status = WorkflowStatus.PENDING
            
            # Fallback check (should not happen if called from run_workflow/run_daily_batch)
            # This is here for safety in case process_story is called directly
            if self.processed_tracker.is_processed(story.id):
                self.logger.warning(f"Story {story.id} already processed (this should have been filtered earlier)")
                return WorkflowResult(
                    success=False,
                    story_id=story.id,
                    error="Story already processed"
                )
            
            if not dry_run:
                # Also check Google Sheets (backup check)
                if self.sheets_client and await self.sheets_client.story_exists(story.id):
                    self.logger.info(f"Story {story.id} already exists in sheets, skipping")
                    # Add to local tracker if not there
                    self.processed_tracker.mark_processed(story.id)
                    return WorkflowResult(
                        success=False,
                        story_id=story.id,
                        error="Story already processed"
                    )
                
                # Save to Google Sheets
                if self.sheets_client:
                    await self.sheets_client.append_story({
                        'id': story.id,
                        'title': story.title,
                        'text': story.text,
                        'author': story.author,
                        'url': story.url,
                        'score': story.score,
                        'created_at': story.created_utc.isoformat(),
                        'status': 'processing'
                })
            
            # Step 2: Generate script with LLM
            self.logger.info("Step 2: Generating script")
            state.status = WorkflowStatus.GENERATING_SCRIPT
            
            # Get schema and prompt
            schema = self._get_script_schema()
            prompt = self._create_script_prompt(story.title, story.text)
            
            # Generate with new API (uses max_tokens from config.yaml gemini section: 8000)
            script_data = await self.llm_service.generate_with_schema(
                prompt=prompt,
                schema=schema
            )
            
            # Convert to GeneratedScript format (scenes -> segments)
            from reddit2shorts.services.llm.base import GeneratedScript, ScriptSegment
            segments = []
            current_time = 0.0
            for scene in script_data.get("scenes", []):
                duration = scene["duration"]
                segments.append(ScriptSegment(
                    text=scene["text"],
                    start_time=current_time,
                    end_time=current_time + duration,
                    duration=duration,
                    image_prompt=scene.get("image_prompt", "")
                ))
                current_time += duration
            
            # Build full text from segments
            full_text = ' '.join(seg.text for seg in segments)
            
            script = GeneratedScript(
                title=script_data.get("title", story.title),
                description=script_data.get("description", ""),
                full_text=full_text,
                segments=segments,
                total_duration=sum(s.duration for s in segments)
            )
            
            # Save script
            script_path = self.file_manager.get_script_path(workflow_id)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(json.dumps(asdict(script), indent=2))
            state.script_path = str(script_path)
            
            # Step 3-6: Loop over segments (matching n8n "Loop Over Items")
            self.logger.info("Step 3-6: Processing segments (Loop Over Items)")
            state.status = WorkflowStatus.GENERATING_IMAGES
            
            segment_videos = []
            
            for i, segment in enumerate(script.segments):
                self.logger.info(f"Processing segment {i+1}/{len(script.segments)}")
                
                # Step 3: Generate image for this segment
                self.logger.info(f"  - Generating image for segment {i+1}")
                image_prompt = segment.image_prompt or self._create_segment_image_prompt(story, segment, i)
                img_path = self.file_manager.get_image_path(workflow_id, i)
                img_path.parent.mkdir(parents=True, exist_ok=True)
                image_result = await self.image_generator.generate_image(image_prompt, img_path)
                
                if not image_result:
                    raise Exception(f"Failed to generate image for segment {i+1}")
                
                # Step 4: Generate TTS for this segment
                self.logger.info(f"  - Generating TTS for segment {i+1}")
                state.status = WorkflowStatus.GENERATING_AUDIO
                audio_path = self.file_manager.get_audio_path(workflow_id, suffix=f"_seg{i}")
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_result = await self.tts_service.synthesize(
                    text=segment.text,
                    output_path=audio_path
                )
                
                if not audio_result:
                    raise Exception(f"Failed to generate audio for segment {i+1}")
                
                # Get actual audio duration
                actual_audio_duration = self._get_audio_duration(audio_result)
                
                # Step 5: Create video for this segment
                self.logger.info(f"  - Creating video for segment {i+1} with random Ken Burns effect")
                state.status = WorkflowStatus.CREATING_VIDEO
                
                subtitles = [
                    SubtitleSegment(
                        text=segment.text,
                        start_time=0.0,
                        end_time=actual_audio_duration
                    )
                ]
                
                video_path = self.file_manager.get_video_path(workflow_id, f"seg{i}")
                video_path.parent.mkdir(parents=True, exist_ok=True)
                # Each segment gets a random Ken Burns effect
                ken_burns_effect = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left'])
                self.logger.info(f"  - Segment {i+1}: Selected Ken Burns effect = {ken_burns_effect}")
                self.logger.info(f"  - Random state check: {random.random()}")  # Debug: check if random is working
                
                video_result = await self.video_service.create_video(
                    images=[image_result],
                    audio_path=audio_result,
                    subtitles=subtitles,
                    output_path=video_path,
                    ken_burns_effect=ken_burns_effect
                )
                
                if not video_result:
                    raise Exception(f"Failed to create video for segment {i+1}")
                
                segment_videos.append(video_result)
                self.logger.info(f"  [OK] Segment {i+1} complete")
            
            # Save segment data to state
            state.image_paths = [str(self.file_manager.get_image_path(workflow_id, i)) for i in range(len(script.segments))]
            state.audio_path = str(self.file_manager.get_audio_path(workflow_id, suffix="_seg0"))  # First segment audio
            
            # Step 6: Merge all segment videos (matching n8n "Start merging the videos")
            self.logger.info("Step 6: Merging segment videos")
            state.status = WorkflowStatus.CREATING_VIDEO
            
            music_path = self._get_music_path()
            final_video_path = self.file_manager.get_video_path(workflow_id, "final")
            
            if music_path.exists():
                final_result = await self.video_service.merge_videos(
                    video_paths=segment_videos,
                    music_path=music_path,
                    output_path=final_video_path,
                    music_volume=self.config["video"].get("background_music_volume", 0.1)
                )
            else:
                self.logger.warning("Background music not found, merging without music")
                final_result = await self.video_service.merge_videos(
                    video_paths=segment_videos,
                    music_path=None,
                    output_path=final_video_path,
                    music_volume=0.0
                )
            
            if not final_result:
                raise Exception("Failed to merge videos")
            
            state.video_path = str(final_result)
            
            # Move final video to output directory
            output_video_path = self.file_manager.move_to_output(workflow_id, final_result)
            self.logger.info(f"Final video saved to: {output_video_path}")
            
            # Step 7: Upload to YouTube
            if not dry_run:
                self.logger.info("Step 7: Uploading to YouTube")
                state.status = WorkflowStatus.UPLOADING
                
                # Get video index if running in batch mode (for scheduled publishing)
                video_index = getattr(self, '_current_video_index', None)
                
                # Get tags from reddit.youtube config
                reddit_config = self.config.get("reddit", {})
                youtube_config = reddit_config.get("youtube", {})
                tags = youtube_config.get("default_tags", [])
                
                video_url = await self.youtube_uploader.upload_video(
                    video_path=final_result,
                    title=self._create_video_title(story),
                    description=self._create_video_description(story),
                    tags=tags,
                    video_index=video_index
                )
                
                # Update Google Sheets with video URL
                if self.sheets_client:
                    await self.sheets_client.update_status(
                        story_id=story.id,
                        status="completed",
                        video_url=video_url
                    )
                
                state.youtube_url = video_url
                
                # Mark as processed in local tracker
                self.processed_tracker.mark_processed(story.id)
            else:
                self.logger.info("Dry run: Skipping YouTube upload")
                video_url = None
                # In dry-run, don't mark as processed
            
            # Complete workflow status
            state.status = WorkflowStatus.COMPLETED
            duration = (datetime.now() - start_time).total_seconds()
            
            # Save final state BEFORE cleanup (so it gets deleted with temp files)
            self._save_state(workflow_id, state)
            
            # Clear current state
            self.current_state = None
            
            self.logger.info(f"Story processed successfully in {duration:.2f}s")
            
            return WorkflowResult(
                success=True,
                story_id=story.id,
                video_url=video_url,
                duration=duration
            )
            
        except Exception as e:
            self.logger.error(f"Error in workflow: {e}", exc_info=True)
            state.status = WorkflowStatus.FAILED
            state.error = str(e)
            
            # Save error state
            self._save_state(workflow_id, state)
            
            # Clear current state
            self.current_state = None
            
            # Update Google Sheets with error
            if not dry_run and self.sheets_client:
                try:
                    await self.sheets_client.update_status(
                        story_id=story.id,
                        status="failed"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to update Google Sheets: {e}")
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return WorkflowResult(
                success=False,
                story_id=story.id,
                error=str(e),
                duration=duration
            )
        finally:
            # Cleanup temp files always (even on error)
            if self.config.get("cleanup_temp_files", True):
                try:
                    self.logger.info(f"Cleaning up temp files for {workflow_id}")
                    self._cleanup_temp_files(workflow_id)
                except Exception as cleanup_error:
                    self.logger.warning(f"Failed to cleanup temp files: {cleanup_error}")
    
    def _create_image_prompts(self, story: RedditStory, script: Any) -> List[str]:
        """
        Create image generation prompts based on story content.
        
        Args:
            story: Reddit story
            script: Generated script
            
        Returns:
            List of image prompts
        """
        # Create 3 image prompts based on story content
        base_prompt = f"Motivational image for story about {story.title}"
        return [
            f"{base_prompt}, scene 1: opening, inspiring atmosphere",
            f"{base_prompt}, scene 2: middle, emotional moment",
            f"{base_prompt}, scene 3: conclusion, uplifting ending"
        ]
    
    def _create_segment_image_prompt(self, story: RedditStory, segment: Any, index: int) -> str:
        """
        Create image generation prompt for a specific segment.
        
        Args:
            story: Reddit story
            segment: Script segment
            index: Segment index
            
        Returns:
            Image prompt for this segment
        """
        base_prompt = f"Motivational image for story about {story.title}"
        
        # Create contextual prompt based on segment position
        total_segments = index + 1  # Approximate
        if index == 0:
            return f"{base_prompt}, opening scene: inspiring atmosphere, beginning of journey"
        elif index < 2:
            return f"{base_prompt}, middle scene {index}: emotional moment, character development"
        else:
            return f"{base_prompt}, conclusion scene: uplifting ending, achievement, success"
    
    def _create_video_title(self, story: RedditStory) -> str:
        """
        Create YouTube video title from story.
        
        Args:
            story: Reddit story
            
        Returns:
            Video title (max 100 characters)
        """
        title = story.title
        if len(title) > 100:
            title = title[:97] + "..."
        return title
    
    def _create_video_description(self, story: RedditStory) -> str:
        """
        Create YouTube video description.
        
        Args:
            story: Reddit story
            
        Returns:
            Video description (empty string - hashtags added by YouTubeUploader from config)
        """
        # Return empty description - hashtags will be added by YouTubeUploader
        # from config.youtube.default_hashtags
        return ""
    
    def _save_state(self, workflow_id: str, state: WorkflowState):
        """
        Save workflow state to file.
        
        Args:
            workflow_id: Workflow identifier
            state: Current workflow state
        """
        try:
            state_path = self.file_manager.get_workflow_dir(workflow_id) / "state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state.to_dict(), indent=2))
        except Exception as e:
            self.logger.warning(f"Failed to save state: {e}")
    
    def _load_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """
        Load workflow state from file.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Loaded workflow state, or None if not found
        """
        try:
            state_path = self.file_manager.get_workflow_dir(workflow_id) / "state.json"
            if state_path.exists():
                state_data = json.loads(state_path.read_text())
                return WorkflowState.from_dict(state_data)
        except Exception as e:
            self.logger.warning(f"Failed to load state: {e}")
        return None
    
    async def resume_workflow(self, workflow_id: str) -> WorkflowResult:
        """
        Resume a failed or interrupted workflow from saved state.
        
        Args:
            workflow_id: Workflow identifier to resume
            
        Returns:
            Workflow result
        """
        self.logger.info(f"Resuming workflow: {workflow_id}")
        
        # Load saved state
        state = self._load_state(workflow_id)
        if not state:
            raise ValueError(f"No saved state found for workflow {workflow_id}")
        
        if state.status == WorkflowStatus.COMPLETED:
            self.logger.info("Workflow already completed")
            return WorkflowResult(
                success=True,
                story_id=state.story_id,
                video_url=state.youtube_url
            )
        
        # Reconstruct story from state
        # Note: This is a simplified version - in production you'd want to save full story data
        story = RedditStory(
            id=state.story_id,
            title="Resumed workflow",
            text="",
            author="",
            url="",
            score=0,
            created_utc=datetime.now()
        )
        
        # Continue from where it left off
        # This is a simplified implementation - full implementation would resume from exact step
        self.logger.warning("Resume functionality is basic - will restart workflow")
        return await self.process_story(story, dry_run=False)
 