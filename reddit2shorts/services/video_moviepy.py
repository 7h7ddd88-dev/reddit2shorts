"""MoviePy Video service.

This module provides video generation using MoviePy Python library (NO external server needed).
"""

from pathlib import Path
from typing import List, Optional
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class MoviePyVideoService:
    """Video generation using MoviePy Python library (полностью локально, без сервера)."""
    
    def __init__(self, config: dict):
        """Initialize MoviePy video service.
        
        Args:
            config: Configuration dict with:
                - subtitle_font: Font for subtitles
                - subtitle_size: Font size
                - subtitle_color: Text color
                - background_music_volume: Music volume (0.0-1.0)
                - watermark_path: Path to watermark image (optional)
                - watermark_scale: Watermark scale (0.0-1.0, default 0.15)
                - watermark_opacity: Watermark opacity (0.0-1.0, default 0.7)
                - watermark_padding_x: Padding from right edge (default 20)
                - watermark_padding_y: Padding from top edge (default 20)
                - end_picture_path: Path to end picture (optional)
                - end_picture_duration: Duration to show end picture in seconds (default 3.0)
        """
        self.subtitle_font = config.get('subtitle_font', 'Arial')
        self.subtitle_size = config.get('subtitle_size', 48)
        self.subtitle_color = config.get('subtitle_color', '#FFFFFF')
        self.background_music_volume = config.get('background_music_volume', 0.2)
        self.watermark_path = config.get('watermark_path', None)
        self.watermark_scale = config.get('watermark_scale', 0.15)
        self.watermark_opacity = config.get('watermark_opacity', 0.7)
        self.watermark_padding_x = config.get('watermark_padding_x', 20)
        self.watermark_padding_y = config.get('watermark_padding_y', 20)
        self.end_picture_path = config.get('end_picture_path', None)
        self.end_picture_duration = config.get('end_picture_duration', 3.0)
        self.logger = logger
    
    def _wrap_text(self, text: str, max_width: int) -> str:
        """Wrap text to fit within max_width, breaking only at word boundaries.
        
        Args:
            text: Text to wrap
            max_width: Maximum width in pixels
            
        Returns:
            Wrapped text with newlines
        """
        from PIL import Image, ImageDraw, ImageFont
        
        # Load font to measure text width
        try:
            font = ImageFont.truetype(self.subtitle_font, self.subtitle_size)
        except Exception as e:
            self.logger.warning(f"Failed to load font {self.subtitle_font}: {e}, using default")
            font = ImageFont.load_default()
        
        # Create dummy image for text measurement
        dummy_img = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            # Try adding word to current line
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            
            if width <= max_width:
                # Word fits, add it
                current_line.append(word)
            else:
                # Word doesn't fit, start new line
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        # Add last line
        if current_line:
            lines.append(' '.join(current_line))
        
        return '\n'.join(lines)
    
    async def create_video(
        self,
        images: List[Path],
        audio_path: Path,
        subtitles: list,
        output_path: Path,
        ken_burns_effect: Optional[str] = None,
        subtitle_mode: str = "word"  # "word" or "sentence"
    ) -> Optional[Path]:
        """Create video with subtitles using MoviePy.
        
        Args:
            images: List of image paths (обычно 1 для segment)
            audio_path: Path to audio file
            subtitles: List of subtitle segments
            output_path: Path to save video
            ken_burns_effect: Specific Ken Burns effect to use (zoom_in, zoom_out, pan_right, pan_left)
                             If None, random effect will be chosen
            subtitle_mode: "word" for word-by-word (shorts), "sentence" for full sentence (longform)
            
        Returns:
            Path to generated video, or None on failure
        """
        try:
            # MoviePy 2.x: импорт напрямую из moviepy
            from moviepy import (
                ImageClip, AudioFileClip, TextClip, 
                CompositeVideoClip, concatenate_videoclips
            )
            
            self.logger.info(f"Creating video with MoviePy: {len(images)} images, audio={audio_path.name}")
            
            # Load audio to get duration
            audio = AudioFileClip(str(audio_path))
            duration = audio.duration
            
            # Create video from image with Ken Burns effect (slow zoom/pan)
            image_clip = ImageClip(str(images[0])).with_duration(duration)
            
            # Ensure dimensions are even (required by libx264)
            w, h = image_clip.size
            if w % 2 != 0:
                w = w - 1
            if h % 2 != 0:
                h = h - 1
            if (w, h) != image_clip.size:
                self.logger.info(f"Adjusting dimensions from {image_clip.size} to ({w}, {h}) for libx264 compatibility")
                image_clip = image_clip.resized((w, h))
            
            # Add Ken Burns effect with random variation (or specified effect)
            import random
            if ken_burns_effect:
                effect_type = ken_burns_effect
                self.logger.info(f"Using specified Ken Burns effect: {effect_type}")
            else:
                effect_type = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left'])
                self.logger.info(f"Randomly selected Ken Burns effect: {effect_type}")
            
            def apply_ken_burns(get_frame, t):
                """Apply Ken Burns effect (zoom or pan)"""
                frame = get_frame(t)
                h, w = frame.shape[:2]
                progress = t / duration  # 0.0 to 1.0
                
                from PIL import Image
                import numpy as np
                
                if effect_type == 'zoom_in':
                    # Zoom in from 100% to 115%
                    zoom = 1.0 + (0.15 * progress)
                    new_h, new_w = int(h * zoom), int(w * zoom)
                    img = Image.fromarray(frame)
                    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                    # Center crop
                    left = (new_w - w) // 2
                    top = (new_h - h) // 2
                    img_cropped = img_resized.crop((left, top, left + w, top + h))
                    return np.array(img_cropped)
                
                elif effect_type == 'zoom_out':
                    # Zoom out from 115% to 100%
                    zoom = 1.15 - (0.15 * progress)
                    new_h, new_w = int(h * zoom), int(w * zoom)
                    img = Image.fromarray(frame)
                    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                    # Center crop
                    left = (new_w - w) // 2
                    top = (new_h - h) // 2
                    img_cropped = img_resized.crop((left, top, left + w, top + h))
                    return np.array(img_cropped)
                
                elif effect_type == 'pan_right':
                    # Pan from left to right with slight zoom
                    zoom = 1.1
                    new_h, new_w = int(h * zoom), int(w * zoom)
                    img = Image.fromarray(frame)
                    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                    # Pan from left to right
                    left = int((new_w - w) * progress)
                    top = (new_h - h) // 2
                    img_cropped = img_resized.crop((left, top, left + w, top + h))
                    return np.array(img_cropped)
                
                else:  # pan_left
                    # Pan from right to left with slight zoom
                    zoom = 1.1
                    new_h, new_w = int(h * zoom), int(w * zoom)
                    img = Image.fromarray(frame)
                    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                    # Pan from right to left
                    left = int((new_w - w) * (1.0 - progress))
                    top = (new_h - h) // 2
                    img_cropped = img_resized.crop((left, top, left + w, top + h))
                    return np.array(img_cropped)
            
            # Apply Ken Burns effect to image clip
            image_clip = image_clip.transform(apply_ken_burns)
            
            self.logger.info(f"Applied Ken Burns effect: {effect_type}")
            
            # Add subtitles (word-by-word or sentence mode)
            subtitle_clips = []
            
            if subtitle_mode == "sentence":
                # Longform mode: show each sentence word-by-word (typewriter effect)
                # Each sentence REPLACES the previous one (not accumulates)
                SENTENCE_GAP = 0.2  # 200ms gap between sentences to prevent overlap
                
                for sub in subtitles:
                    if not sub.text.strip():
                        continue
                    
                    # Calculate max text width in pixels (90% of video width)
                    max_text_width_px = int(image_clip.w * 0.9)
                    
                    # Show each sentence separately (typewriter effect per sentence)
                    # Each sentence REPLACES the previous one
                    sentence_words = sub.text.split()
                    if not sentence_words:
                        continue
                    
                    time_per_word = (sub.end_time - sub.start_time - SENTENCE_GAP) / len(sentence_words)
                    
                    # Create cumulative text clips for THIS sentence only
                    # ВАЖНО: Каждый клип показывается только до появления следующего слова
                    # Последний клип (полное предложение) показывается до конца с gap
                    for i in range(len(sentence_words)):
                        # Build text with all words up to current index (within this sentence)
                        cumulative_text = ' '.join(sentence_words[:i+1])
                        
                        # Wrap text for better readability (pass width in pixels)
                        wrapped_text = self._wrap_text(cumulative_text, max_width=max_text_width_px)
                        
                        word_start = sub.start_time + (i * time_per_word)
                        
                        # КРИТИЧНО: Каждый клип заменяется следующим
                        # Последний клип (полное предложение) показывается до конца минус gap
                        if i == len(sentence_words) - 1:
                            # Последнее слово - показываем до конца предложения минус gap
                            word_end = sub.end_time - SENTENCE_GAP
                        else:
                            # Промежуточные слова - показываем только до появления следующего
                            word_end = word_start + time_per_word
                        
                        # Create text clip showing all words up to current
                        txt_clip = TextClip(
                            text=wrapped_text,
                            font_size=self.subtitle_size,
                            color=self.subtitle_color,
                            font=self.subtitle_font,
                            method='caption',
                            size=(max_text_width_px, None),  # Use calculated pixel width
                            stroke_color='black',
                            stroke_width=2,
                            margin=(10, 20)  # Smaller margins for more space
                        )
                        
                        # Position subtitles at BOTTOM (85% from top, near bottom)
                        x_pos = 'center'
                        y_pos = int(image_clip.h * 0.85)
                        
                        # Устанавливаем время: каждый клип заменяется следующим (typewriter эффект)
                        # Последний клип остаётся до конца предложения, затем gap перед следующим
                        txt_clip = txt_clip.with_position((x_pos, y_pos)).with_start(word_start).with_end(word_end)
                        subtitle_clips.append(txt_clip)
            else:
                # Short video mode: word-by-word, centered
                for sub in subtitles:
                    # Split text into words and create individual clips for each word
                    words = sub.text.split()
                    if not words:
                        continue
                    
                    # Use the subtitle's actual timing inside this segment.
                    # Using the full segment duration for every subtitle can cause
                    # visible drift, especially on later fragments.
                    segment_duration = max(0.01, sub.end_time - sub.start_time)
                    time_per_word = segment_duration / len(words)
                    
                    for i, word in enumerate(words):
                        word_start = sub.start_time + (i * time_per_word)
                        word_end = word_start + time_per_word
                        
                        # Create text clip for this word
                        txt_clip = TextClip(
                            text=word,
                            font_size=self.subtitle_size,
                            color=self.subtitle_color,
                            font=self.subtitle_font,
                            method='label',
                            stroke_color='black',
                            stroke_width=2,
                            margin=(20, 30)
                        )
                        
                        # Position subtitles in center (45% from top)
                        x_pos = 'center'
                        y_pos = int(image_clip.h * 0.45)
                        
                        txt_clip = txt_clip.with_position((x_pos, y_pos)).with_start(word_start).with_duration(word_end - word_start)
                        subtitle_clips.append(txt_clip)
            
            # Add watermark if configured
            watermark_clip = None
            if self.watermark_path and Path(self.watermark_path).exists():
                try:
                    self.logger.info(f"Adding watermark: {self.watermark_path}")
                    
                    # Load watermark and convert to RGBA to preserve transparency
                    from PIL import Image as PILImage
                    watermark_img = PILImage.open(self.watermark_path)
                    if watermark_img.mode != 'RGBA':
                        self.logger.info(f"Converting watermark from {watermark_img.mode} to RGBA")
                        watermark_img = watermark_img.convert('RGBA')
                    
                    # Save temporary RGBA version
                    temp_watermark = Path(self.watermark_path).parent / f"temp_{Path(self.watermark_path).name}"
                    watermark_img.save(temp_watermark)
                    
                    # Load watermark image from RGBA version
                    watermark = ImageClip(str(temp_watermark))
                    
                    # Calculate watermark size (scale based on video width)
                    watermark_width = int(image_clip.w * self.watermark_scale)
                    watermark = watermark.resized(width=watermark_width)
                    
                    # Set opacity
                    watermark = watermark.with_opacity(self.watermark_opacity)
                    
                    # Position in top-right corner with configurable padding
                    x_pos = image_clip.w - watermark.w - self.watermark_padding_x
                    y_pos = self.watermark_padding_y
                    
                    # Set duration and position
                    watermark_clip = watermark.with_duration(duration).with_position((x_pos, y_pos))
                    
                    self.logger.info(f"Watermark added: {watermark.w}x{watermark.h} at ({x_pos}, {y_pos})")
                except Exception as e:
                    self.logger.warning(f"Failed to add watermark: {e}")
                    watermark_clip = None
            
            # Composite video with subtitles and watermark
            clips_to_composite = [image_clip] + subtitle_clips
            if watermark_clip:
                clips_to_composite.append(watermark_clip)
            
            if len(clips_to_composite) > 1:
                # Set size explicitly to avoid black background
                video = CompositeVideoClip(
                    clips_to_composite,
                    size=image_clip.size  # Use image size explicitly
                ).with_duration(duration)
            else:
                video = image_clip
            
            # Add audio
            video = video.with_audio(audio)
            
            # Write output with better encoding settings
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Use unique temp audio file to avoid conflicts in parallel execution
            temp_audio = output_path.parent / f"temp-audio-{output_path.stem}.m4a"
            video.write_videofile(
                str(output_path),
                fps=24,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile=str(temp_audio),
                remove_temp=True,
                logger=None,  # Suppress moviepy logs
                preset='medium',  # Better encoding quality
                ffmpeg_params=['-pix_fmt', 'yuv420p']  # Ensure compatibility
            )
            
            # Cleanup resources properly
            try:
                video.close()
            except Exception as e:
                self.logger.debug(f"Error closing video clip: {e}")
            try:
                audio.close()
            except Exception as e:
                self.logger.debug(f"Error closing audio clip: {e}")
            
            self.logger.info(f"Video created: {output_path}")
            return output_path
            
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
        """Merge videos using MoviePy.
        
        Args:
            video_paths: List of video paths to merge
            music_path: Path to background music
            output_path: Path to save merged video
            music_volume: Music volume (0.0-1.0)
            
        Returns:
            Path to merged video, or None on failure
        """
        try:
            # MoviePy 2.x: импорт напрямую из moviepy
            from moviepy import (
                VideoFileClip, AudioFileClip, concatenate_videoclips,
                CompositeAudioClip, concatenate_audioclips, ImageClip,
                CompositeVideoClip, ColorClip
            )
            
            self.logger.info(f"Merging {len(video_paths)} videos with MoviePy")
            
            # Load all video clips with resize_algorithm for better quality
            clips = []
            for path in video_paths:
                try:
                    clip = VideoFileClip(str(path), audio=True, fps_source='fps')
                    clips.append(clip)
                except Exception as e:
                    self.logger.error(f"Failed to load clip {path}: {e}")
                    raise
            
            # Ensure all clips have the same properties
            if clips:
                target_size = clips[0].size
                target_fps = clips[0].fps
                self.logger.info(f"Target video: {target_size[0]}x{target_size[1]} @ {target_fps}fps")
                
                # Normalize all clips to same size and FPS
                normalized_clips = []
                for i, clip in enumerate(clips):
                    # Resize if needed
                    if clip.size != target_size:
                        self.logger.warning(f"Clip {i} has different size {clip.size}, resizing to {target_size}")
                        clip = clip.resized(target_size)
                    
                    # Set FPS if needed
                    if clip.fps != target_fps:
                        self.logger.warning(f"Clip {i} has different FPS {clip.fps}, setting to {target_fps}")
                        clip = clip.with_fps(target_fps)
                    
                    normalized_clips.append(clip)
                clips = normalized_clips
            
            # Concatenate videos directly without any padding or transitions
            # Use method="compose" with padding=0 to avoid black screens
            final_video = concatenate_videoclips(
                clips, 
                method="compose",
                bg_color=None,  # No background color
                padding=0  # No padding between clips
            )
            
            # Add end picture/video if configured
            if self.end_picture_path and Path(self.end_picture_path).exists():
                try:
                    self.logger.info(f"Adding end media: {self.end_picture_path} for {self.end_picture_duration}s")
                    
                    video_w, video_h = final_video.size
                    end_path = Path(self.end_picture_path)
                    
                    # Check if it's a video or image
                    if end_path.suffix.lower() in ['.mp4', '.mov', '.avi', '.mkv']:
                        # It's a video - load as VideoFileClip
                        from moviepy import VideoFileClip
                        end_clip = VideoFileClip(str(self.end_picture_path))
                        
                        # Trim or loop to match desired duration
                        if end_clip.duration > self.end_picture_duration:
                            end_clip = end_clip.subclipped(0, self.end_picture_duration)
                        elif end_clip.duration < self.end_picture_duration:
                            # Loop video to fill duration
                            from moviepy import concatenate_videoclips
                            loops_needed = int(self.end_picture_duration / end_clip.duration) + 1
                            end_clip = concatenate_videoclips([end_clip] * loops_needed)
                            end_clip = end_clip.subclipped(0, self.end_picture_duration)
                        
                        # Resize to match video dimensions
                        if end_clip.size != (video_w, video_h):
                            end_clip = end_clip.resized((video_w, video_h))
                    else:
                        # It's an image - create ImageClip
                        end_clip = ImageClip(str(self.end_picture_path)).with_duration(self.end_picture_duration)
                        
                        # Scale to fit within video dimensions while maintaining aspect ratio
                        pic_w, pic_h = end_clip.size
                        scale_w = video_w / pic_w
                        scale_h = video_h / pic_h
                        scale = min(scale_w, scale_h)
                        
                        new_w = int(pic_w * scale)
                        new_h = int(pic_h * scale)
                        end_clip = end_clip.resized((new_w, new_h))
                        end_clip = end_clip.with_position('center')
                        
                        # Create black background
                        from moviepy import ColorClip
                        black_bg = ColorClip(size=(video_w, video_h), color=(0, 0, 0)).with_duration(self.end_picture_duration)
                        
                        # Composite picture on black background
                        end_clip = CompositeVideoClip(
                            [black_bg, end_clip],
                            size=(video_w, video_h)
                        ).with_duration(self.end_picture_duration)
                    
                    # Set FPS to match video
                    end_clip = end_clip.with_fps(final_video.fps)
                    
                    # Concatenate main video with end media
                    final_video = concatenate_videoclips(
                        [final_video, end_clip],
                        method="compose",
                        bg_color=None,
                        padding=0
                    )
                    
                    self.logger.info(f"End media added successfully")
                except Exception as e:
                    self.logger.warning(f"Failed to add end picture: {e}")
            
            # Add background music if provided
            if music_path and music_path.exists():
                self.logger.info(f"Adding background music: {music_path.name}")
                
                # Load music
                music = AudioFileClip(str(music_path))
                
                # Loop music to match video duration
                if music.duration < final_video.duration:
                    n_loops = int(final_video.duration / music.duration) + 1
                    music = concatenate_audioclips([music] * n_loops)
                
                # Trim music to video duration
                music = music.subclipped(0, final_video.duration)
                
                # Reduce music volume
                music = music.with_volume_scaled(music_volume)
                
                # Mix original audio with music
                original_audio = final_video.audio
                if original_audio:
                    final_audio = CompositeAudioClip([original_audio, music])
                else:
                    final_audio = music
                
                final_video = final_video.with_audio(final_audio)
            
            # Write output with better encoding settings
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Use unique temp audio file to avoid conflicts in parallel execution
            temp_audio = output_path.parent / f"temp-audio-{output_path.stem}.m4a"
            final_video.write_videofile(
                str(output_path),
                fps=24,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile=str(temp_audio),
                remove_temp=True,
                logger=None,  # Suppress moviepy logs
                preset='medium',  # Better encoding quality
                ffmpeg_params=['-pix_fmt', 'yuv420p'],  # Ensure compatibility
                write_logfile=False  # Disable log file
            )
            
            # Cleanup resources properly
            try:
                final_video.close()
            except Exception as e:
                self.logger.debug(f"Error closing final video clip: {e}")
            for clip in clips:
                try:
                    clip.close()
                except Exception as e:
                    self.logger.debug(f"Error closing clip: {e}")
            
            self.logger.info(f"Videos merged: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Video merge failed: {e}")
            return None
    
    async def add_background_music(
        self,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        music_volume: float = 0.1
    ) -> Optional[Path]:
        """Add background music to video.
        
        Args:
            video_path: Path to input video
            music_path: Path to background music
            output_path: Path to save output video
            music_volume: Music volume (0.0-1.0)
            
        Returns:
            Path to output video, or None on failure
        """
        try:
            from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips
            
            self.logger.info(f"Adding background music: {music_path.name}")
            
            # Load video
            video = VideoFileClip(str(video_path))
            
            # Load music
            music = AudioFileClip(str(music_path))
            
            # Loop music to match video duration
            if music.duration < video.duration:
                n_loops = int(video.duration / music.duration) + 1
                self.logger.info(f"Looping music {n_loops} times to match video duration")
                music = concatenate_audioclips([music] * n_loops)
            
            # Trim music to video duration
            music = music.subclipped(0, video.duration)
            
            # Reduce music volume
            music = music.with_volume_scaled(music_volume)
            
            # Mix original audio with music
            original_audio = video.audio
            if original_audio:
                final_audio = CompositeAudioClip([original_audio, music])
            else:
                final_audio = music
            
            # Set audio to video
            final_video = video.with_audio(final_audio)
            
            # Write output
            final_video.write_videofile(
                str(output_path),
                codec='libx264',
                audio_codec='aac',
                fps=video.fps,
                preset='medium',
                logger=None
            )
            
            # Cleanup
            video.close()
            music.close()
            final_video.close()
            
            self.logger.info(f"Background music added: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Failed to add background music: {e}")
            return None

    async def prepend_thumbnail_frame(
        self,
        video_path: Path,
        thumbnail_path: Path,
        output_path: Path,
        duration: float = 0.1
    ) -> Optional[Path]:
        """Prepend thumbnail image as first frame to video.
        
        Args:
            video_path: Path to input video
            thumbnail_path: Path to thumbnail image
            output_path: Path to save output video
            duration: Duration to show thumbnail in seconds (default: 0.1)
            
        Returns:
            Path to output video, or None on failure
            
        Example:
            >>> await video_service.prepend_thumbnail_frame(
            ...     video_path=Path("video.mp4"),
            ...     thumbnail_path=Path("thumbnail.jpg"),
            ...     output_path=Path("video_with_thumb.mp4"),
            ...     duration=0.1
            ... )
        """
        try:
            from moviepy import VideoFileClip, ImageClip, concatenate_videoclips
            
            self.logger.info(f"Prepending thumbnail frame ({duration}s) to video")
            
            # Load video
            video = VideoFileClip(str(video_path))
            
            # Load thumbnail as image clip
            thumbnail_clip = ImageClip(str(thumbnail_path)).with_duration(duration)
            
            # Resize thumbnail to match video dimensions
            thumbnail_clip = thumbnail_clip.resized(video.size)
            
            # Set FPS to match video
            thumbnail_clip = thumbnail_clip.with_fps(video.fps)
            
            # Concatenate thumbnail + video
            final_video = concatenate_videoclips(
                [thumbnail_clip, video],
                method="compose",
                bg_color=None,
                padding=0
            )
            
            # Write output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Use unique temp audio file to avoid conflicts in parallel execution
            temp_audio = output_path.parent / f"temp-audio-{output_path.stem}.m4a"
            final_video.write_videofile(
                str(output_path),
                fps=video.fps,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile=str(temp_audio),
                remove_temp=True,
                logger=None,
                preset='medium',
                ffmpeg_params=['-pix_fmt', 'yuv420p'],
                write_logfile=False
            )
            
            # Cleanup
            video.close()
            thumbnail_clip.close()
            final_video.close()
            
            self.logger.info(f"Thumbnail frame prepended: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Failed to prepend thumbnail frame: {e}")
            return None
