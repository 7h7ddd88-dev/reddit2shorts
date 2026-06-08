"""Local AI Agents No-Code Tools Video service.

This module provides video generation using the local server (как в n8n).
"""

import aiohttp
import asyncio
from pathlib import Path
from typing import List, Optional
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class LocalVideoService:
    """Video generation using local AI Agents No-Code Tools server (как в n8n)."""
    
    def __init__(self, config: dict):
        """Initialize local video service.
        
        Args:
            config: Configuration dict with:
                - local_url: URL локального сервера
                - subtitle_*: параметры субтитров
                - background_music_volume: громкость музыки
        """
        self.base_url = config.get('local_url', 'http://localhost:8000')
        self.subtitle_font = config.get('subtitle_font', 'Arial')
        self.subtitle_size = config.get('subtitle_size', 48)
        self.subtitle_color = config.get('subtitle_color', '#FFFFFF')
        self.background_music_volume = config.get('background_music_volume', 0.2)
        self.polling_interval = config.get('polling_interval', 10)
        self.timeout = config.get('timeout', 600)
        self.logger = logger
    
    async def create_video(
        self,
        images: List[Path],
        audio_path: Path,
        subtitles: list,
        output_path: Path
    ) -> Optional[Path]:
        """Create video with subtitles using local server (как в n8n).
        
        Args:
            images: List of image paths (обычно 1 для segment)
            audio_path: Path to audio file
            subtitles: List of subtitle segments
            output_path: Path to save video
            
        Returns:
            Path to generated video, or None on failure
        """
        try:
            # 1. Upload image
            image_id = await self._upload_file(images[0], 'image')
            if not image_id:
                return None
            
            # 2. Upload audio
            audio_id = await self._upload_file(audio_path, 'audio')
            if not audio_id:
                return None
            
            # 3. Generate video with TTS captions
            url = f"{self.base_url}/api/v1/media/video-tools/generate/tts-captioned-video"
            
            # Extract text from subtitles
            text = subtitles[0].text if subtitles else ""
            
            self.logger.info(f"Generating video: image_id={image_id}, audio_id={audio_id}")
            
            async with aiohttp.ClientSession() as session:
                data = {
                    'background_id': image_id,
                    'audio_id': audio_id,
                    'text': text
                }
                
                async with session.post(url, json=data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"Video generation failed: {response.status} - {error_text}")
                        return None
                    
                    result = await response.json()
                    file_id = result.get('file_id')
                    
                    if not file_id:
                        self.logger.error("No file_id in video generation response")
                        return None
                    
                    self.logger.info(f"Video generation started: file_id={file_id}")
                    
                    # 4. Wait for completion
                    if not await self._wait_for_completion(file_id):
                        return None
                    
                    # 5. Download video
                    return await self._download_file(file_id, output_path)
                    
        except Exception as e:
            self.logger.error(f"Video creation failed: {e}")
            return None
    
    async def merge_videos(
        self,
        video_paths: List[Path],
        music_path: Optional[Path],
        output_path: Path,
        music_volume: float = 0.2
    ) -> Optional[Path]:
        """Merge videos using local server (как в n8n).
        
        Args:
            video_paths: List of video paths to merge
            music_path: Path to background music
            output_path: Path to save merged video
            music_volume: Music volume (0.0-1.0)
            
        Returns:
            Path to merged video, or None on failure
        """
        try:
            # 1. Upload all videos
            video_ids = []
            for i, video_path in enumerate(video_paths):
                self.logger.info(f"Uploading video {i+1}/{len(video_paths)}")
                video_id = await self._upload_file(video_path, 'video')
                if not video_id:
                    return None
                video_ids.append(video_id)
            
            # 2. Upload music
            music_id = None
            if music_path and music_path.exists():
                self.logger.info("Uploading background music")
                music_id = await self._upload_file(music_path, 'audio')
            
            # 3. Merge videos
            url = f"{self.base_url}/api/v1/media/video-tools/merge"
            
            self.logger.info(f"Merging {len(video_ids)} videos")
            
            async with aiohttp.ClientSession() as session:
                data = {
                    'video_ids': video_ids,
                    'background_music_volume': music_volume
                }
                
                if music_id:
                    data['background_music_id'] = music_id
                
                async with session.post(url, json=data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"Video merge failed: {response.status} - {error_text}")
                        return None
                    
                    result = await response.json()
                    file_id = result.get('file_id')
                    
                    if not file_id:
                        self.logger.error("No file_id in merge response")
                        return None
                    
                    self.logger.info(f"Video merge started: file_id={file_id}")
                    
                    # 4. Wait for completion
                    if not await self._wait_for_completion(file_id):
                        return None
                    
                    # 5. Download merged video
                    return await self._download_file(file_id, output_path)
                    
        except Exception as e:
            self.logger.error(f"Video merge failed: {e}")
            return None
    
    async def _upload_file(self, file_path: Path, file_type: str) -> Optional[str]:
        """Upload file to local server storage.
        
        Args:
            file_path: Path to file
            file_type: Type of file (image, audio, video)
            
        Returns:
            File ID, or None on failure
        """
        url = f"{self.base_url}/api/v1/media/storage"
        
        self.logger.info(f"Uploading {file_type}: {file_path.name}")
        
        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field('file',
                              file_path.read_bytes(),
                              filename=file_path.name,
                              content_type=f'{file_type}/*')
                data.add_field('type', file_type)
                
                async with session.post(url, data=data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"Upload failed: {response.status} - {error_text}")
                        return None
                    
                    result = await response.json()
                    file_id = result.get('file_id')
                    
                    if file_id:
                        self.logger.info(f"Uploaded {file_type}: file_id={file_id}")
                    
                    return file_id
                    
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            return None
    
    async def _wait_for_completion(self, file_id: str) -> bool:
        """Wait for file processing to complete.
        
        Args:
            file_id: File ID to check
            
        Returns:
            True if completed successfully, False otherwise
        """
        status_url = f"{self.base_url}/api/v1/media/storage/{file_id}/status"
        
        self.logger.info(f"Waiting for completion: file_id={file_id}")
        
        start_time = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession() as session:
            while True:
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self.timeout:
                    self.logger.error(f"Timeout waiting for file_id={file_id}")
                    return False
                
                # Check status
                try:
                    async with session.get(status_url) as response:
                        if response.status != 200:
                            self.logger.error(f"Status check failed: {response.status}")
                            return False
                        
                        result = await response.json()
                        status = result.get('status')
                        
                        if status == 'completed':
                            self.logger.info(f"Processing completed: file_id={file_id}")
                            return True
                        elif status == 'failed':
                            error = result.get('error', 'Unknown error')
                            self.logger.error(f"Processing failed: {error}")
                            return False
                        elif status in ['processing', 'pending']:
                            self.logger.debug(f"Status: {status}, waiting...")
                        else:
                            self.logger.warning(f"Unknown status: {status}")
                        
                except Exception as e:
                    self.logger.error(f"Status check error: {e}")
                    return False
                
                # Wait before next check
                await asyncio.sleep(self.polling_interval)
    
    async def _download_file(self, file_id: str, output_path: Path) -> Optional[Path]:
        """Download file from local server storage.
        
        Args:
            file_id: File ID to download
            output_path: Path to save file
            
        Returns:
            Path to downloaded file, or None on failure
        """
        download_url = f"{self.base_url}/api/v1/media/storage/{file_id}"
        
        self.logger.info(f"Downloading: file_id={file_id}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"Download failed: {response.status} - {error_text}")
                        return None
                    
                    # Save to file
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(await response.read())
                    
                    self.logger.info(f"Downloaded: {output_path}")
                    return output_path
                    
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return None
