"""
Video Service for Reddit2Shorts

This module provides video creation functionality using an external video API.
It handles job submission, status polling, video download, and background music addition.
"""

import aiohttp
import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry
from reddit2shorts.core.exceptions import APIError, ResourceError

logger = get_logger(__name__)


@dataclass
class SubtitleSegment:
    """Represents a subtitle segment with text and timing"""
    text: str
    start_time: float
    end_time: float


class VideoService:
    """
    Service for creating videos with subtitles using external API.
    
    Handles:
    - Job submission with images, audio, and subtitles
    - Polling for job completion
    - Video download
    - Background music addition using ffmpeg
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize video service.
        
        Args:
            config: Configuration dictionary with api_url, api_key, and subtitle settings
        """
        self.api_url = config["api_url"]
        self.api_key = config["api_key"]
        self.subtitle_config = {
            "font": config.get("subtitle_font", "Arial"),
            "size": config.get("subtitle_size", 48),
            "color": config.get("subtitle_color", "#FFFFFF")
        }
        self.logger = logger
        self.poll_interval = 10  # seconds
        self.max_wait_time = 600  # 10 minutes
    
    async def create_video(
        self,
        images: List[Path],
        audio_path: Path,
        subtitles: List[SubtitleSegment],
        output_path: Path
    ) -> Optional[Path]:
        """
        Create video with images, audio, and subtitles.
        
        Args:
            images: List of image file paths
            audio_path: Path to audio file
            subtitles: List of subtitle segments
            output_path: Path where video should be saved
            
        Returns:
            Path to created video file, or None if failed
        """
        self.logger.info("Creating video with subtitles")
        
        try:
            # Upload assets and create video
            task_id = await self._submit_video_job(images, audio_path, subtitles)
            if not task_id:
                return None
            
            # Poll for completion
            video_url = await self._poll_video_status(task_id)
            if not video_url:
                return None
            
            # Download video
            return await self._download_video(video_url, output_path)
            
        except Exception as e:
            self.logger.error(f"Error creating video: {e}")
            raise APIError(f"Video creation failed: {e}")
    
    @async_retry(max_attempts=3, delay=2.0)
    async def _submit_video_job(
        self,
        images: List[Path],
        audio_path: Path,
        subtitles: List[SubtitleSegment]
    ) -> Optional[str]:
        """
        Submit video creation job to API.
        
        Args:
            images: List of image file paths
            audio_path: Path to audio file
            subtitles: List of subtitle segments
            
        Returns:
            Task ID for polling, or None if failed
        """
        self.logger.info("Submitting video creation job")
        
        async with aiohttp.ClientSession() as session:
            # Prepare multipart form data
            data = aiohttp.FormData()
            
            # Add images
            for i, img_path in enumerate(images):
                with open(img_path, 'rb') as f:
                    data.add_field(
                        f'image_{i}',
                        f,
                        filename=img_path.name,
                        content_type='image/jpeg'
                    )
            
            # Add audio
            with open(audio_path, 'rb') as f:
                data.add_field(
                    'audio',
                    f,
                    filename=audio_path.name,
                    content_type='audio/mpeg'
                )
            
            # Add subtitle data
            subtitle_data = {
                "segments": [
                    {
                        "text": seg.text,
                        "start": seg.start_time,
                        "end": seg.end_time
                    }
                    for seg in subtitles
                ],
                "config": self.subtitle_config
            }
            data.add_field('subtitles', json.dumps(subtitle_data))
            
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            async with session.post(
                f"{self.api_url}/create",
                headers=headers,
                data=data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    task_id = result.get("task_id")
                    self.logger.info(f"Video job submitted: {task_id}")
                    return task_id
                else:
                    error = await response.text()
                    self.logger.error(f"Failed to submit video job: {error}")
                    raise APIError(f"Video job submission failed: {error}")
    
    async def _poll_video_status(self, task_id: str) -> Optional[str]:
        """
        Poll video creation status until completion or timeout.
        
        Args:
            task_id: Task ID to poll
            
        Returns:
            Video URL when ready, or None if failed/timeout
        """
        self.logger.info(f"Polling video status for task {task_id}")
        
        start_time = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession() as session:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self.max_wait_time:
                    self.logger.error("Video creation timeout")
                    raise APIError("Video creation timeout after 10 minutes")
                
                headers = {"Authorization": f"Bearer {self.api_key}"}
                
                try:
                    async with session.get(
                        f"{self.api_url}/status/{task_id}",
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            status = result.get("status")
                            
                            if status == "completed":
                                video_url = result.get("video_url")
                                self.logger.info(f"Video ready: {video_url}")
                                return video_url
                            elif status == "failed":
                                error = result.get("error", "Unknown error")
                                self.logger.error(f"Video creation failed: {error}")
                                raise APIError(f"Video creation failed: {error}")
                            else:
                                self.logger.info(f"Video status: {status}")
                        else:
                            self.logger.warning(f"Status check failed: {response.status}")
                
                except aiohttp.ClientError as e:
                    self.logger.warning(f"Polling error: {e}, retrying...")
                
                await asyncio.sleep(self.poll_interval)
    
    @async_retry(max_attempts=3, delay=2.0)
    async def _download_video(self, video_url: str, output_path: Path) -> Optional[Path]:
        """
        Download completed video from URL.
        
        Args:
            video_url: URL to download video from
            output_path: Path where video should be saved
            
        Returns:
            Path to downloaded video, or None if failed
        """
        self.logger.info(f"Downloading video to {output_path}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as response:
                if response.status == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(output_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                    
                    self.logger.info(f"Video downloaded successfully")
                    return output_path
                else:
                    self.logger.error(f"Failed to download video: {response.status}")
                    raise APIError(f"Video download failed: HTTP {response.status}")
    
    async def add_background_music(
        self,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        music_volume: float = 0.2
    ) -> Optional[Path]:
        """
        Add background music to video using ffmpeg.
        
        Args:
            video_path: Path to input video
            music_path: Path to background music file
            output_path: Path where output video should be saved
            music_volume: Volume level for background music (0.0 to 1.0)
            
        Returns:
            Path to output video with music, or None if failed
        """
        self.logger.info("Adding background music to video")
        
        # Validate inputs
        if not video_path.exists():
            raise ResourceError(f"Video file not found: {video_path}")
        if not music_path.exists():
            raise ResourceError(f"Music file not found: {music_path}")
        
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-i', str(music_path),
            '-filter_complex',
            f'[1:a]volume={music_volume}[a1];[0:a][a1]amix=inputs=2:duration=shortest',
            '-c:v', 'copy',
            '-y',
            str(output_path)
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                self.logger.info("Background music added successfully")
                return output_path
            else:
                error_msg = stderr.decode()
                self.logger.error(f"ffmpeg error: {error_msg}")
                raise ResourceError(f"ffmpeg failed: {error_msg}")
                
        except FileNotFoundError:
            self.logger.error("ffmpeg not found. Please install ffmpeg.")
            raise ResourceError("ffmpeg not installed")
        except Exception as e:
            self.logger.error(f"Error adding background music: {e}")
            raise ResourceError(f"Background music addition failed: {e}")
    
    async def merge_videos(
        self,
        video_paths: List[Path],
        music_path: Optional[Path],
        output_path: Path,
        music_volume: float = 0.2
    ) -> Optional[Path]:
        """
        Merge multiple videos into one and optionally add background music.
        
        This matches the n8n "Start merging the videos" node functionality.
        
        Args:
            video_paths: List of video file paths to merge
            music_path: Optional path to background music file
            output_path: Path where merged video should be saved
            music_volume: Volume level for background music (0.0 to 1.0)
            
        Returns:
            Path to merged video, or None if failed
        """
        self.logger.info(f"Merging {len(video_paths)} videos")
        
        # Validate inputs
        for video_path in video_paths:
            if not video_path.exists():
                raise ResourceError(f"Video file not found: {video_path}")
        
        if len(video_paths) == 0:
            raise ResourceError("No videos to merge")
        
        # If only one video, just add music if provided
        if len(video_paths) == 1:
            if music_path and music_path.exists():
                return await self.add_background_music(
                    video_path=video_paths[0],
                    music_path=music_path,
                    output_path=output_path,
                    music_volume=music_volume
                )
            else:
                # Just copy the single video
                import shutil
                shutil.copy2(video_paths[0], output_path)
                return output_path
        
        # Create concat file for ffmpeg
        concat_file = output_path.parent / "concat_list.txt"
        with open(concat_file, 'w') as f:
            for video_path in video_paths:
                # Use absolute paths and escape special characters
                abs_path = video_path.absolute()
                f.write(f"file '{abs_path}'\n")
        
        try:
            # First, concatenate videos
            temp_output = output_path.parent / f"temp_merged_{output_path.name}"
            
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',
                '-y',
                str(temp_output)
            ]
            
            self.logger.info("Concatenating videos...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode()
                self.logger.error(f"ffmpeg concat error: {error_msg}")
                raise ResourceError(f"Video concatenation failed: {error_msg}")
            
            # Clean up concat file
            concat_file.unlink()
            
            # Add background music if provided
            if music_path and music_path.exists():
                self.logger.info("Adding background music to merged video...")
                result = await self.add_background_music(
                    video_path=temp_output,
                    music_path=music_path,
                    output_path=output_path,
                    music_volume=music_volume
                )
                # Clean up temp file
                temp_output.unlink()
                return result
            else:
                # No music, just rename temp file to output
                temp_output.rename(output_path)
                return output_path
                
        except FileNotFoundError:
            self.logger.error("ffmpeg not found. Please install ffmpeg.")
            raise ResourceError("ffmpeg not installed")
        except Exception as e:
            self.logger.error(f"Error merging videos: {e}")
            # Clean up temp files
            if concat_file.exists():
                concat_file.unlink()
            raise ResourceError(f"Video merge failed: {e}")
