"""
Thumbnail generation utilities.

This module provides utilities for creating video thumbnails.
"""

from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageOps

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


def create_thumbnail(
    background_path: Path,
    text: str,
    miniature_image_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    circle_size_percent: float = 0.4,
    circle_position: tuple = (0.10, 0.95),
    text_position: tuple = (0.55, 40),
    text_width_percent: float = 0.40,
    font_size_percent: float = 0.08
) -> Path:
    """
    Create thumbnail by overlaying text and circular miniature on background.
    
    Args:
        background_path: Path to background image (e.g., preview.jpg)
        text: Text to overlay on thumbnail
        miniature_image_path: Optional path to image for circular miniature
        output_path: Optional output path (defaults to temp file)
        circle_size_percent: Size of circular miniature as % of height (default: 0.4)
        circle_position: Position of circle as (x%, y%) from top-left (default: (0.10, 0.95))
        text_position: Position of text as (x%, y_pixels) (default: (0.55, 40))
        text_width_percent: Width of text area as % of width (default: 0.40)
        font_size_percent: Font size as % of height (default: 0.08)
        
    Returns:
        Path to created thumbnail
        
    Example:
        >>> thumbnail = create_thumbnail(
        ...     background_path=Path("preview.jpg"),
        ...     text="The Brutal Truth About Success",
        ...     miniature_image_path=Path("first_image.jpg"),
        ...     output_path=Path("thumbnail.jpg")
        ... )
    """
    try:
        # Load background template
        if not background_path.exists():
            raise FileNotFoundError(f"Background not found: {background_path}")
        
        template = Image.open(background_path)
        width, height = template.size
        
        # Add circular miniature if provided
        if miniature_image_path and miniature_image_path.exists():
            miniature = Image.open(miniature_image_path)
            
            # Calculate circle size
            circle_size = int(height * circle_size_percent)
            
            # Resize miniature to circle size
            miniature = miniature.resize((circle_size, circle_size), Image.Resampling.LANCZOS)
            
            # Create circular mask
            mask = Image.new('L', (circle_size, circle_size), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, circle_size, circle_size), fill=255)
            
            # Apply mask to miniature
            output = ImageOps.fit(miniature, (circle_size, circle_size), centering=(0.5, 0.5))
            output.putalpha(mask)
            
            # Calculate circle position
            circle_x = int(width * circle_position[0])
            circle_y = int(height * circle_position[1]) - circle_size  # Position from bottom
            
            # Paste circular miniature on template
            template.paste(output, (circle_x, circle_y), output)
            logger.debug(f"Added circular miniature at ({circle_x}, {circle_y})")
        
        # Add text overlay
        draw = ImageDraw.Draw(template)
        
        # Load font
        try:
            font_size = int(height * font_size_percent)
            # Try bold font first
            font = ImageFont.truetype("arialbd.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()
                logger.warning("Using default font (bold font not found)")
        
        # Calculate text area
        text_x = int(width * text_position[0])
        text_width = int(width * text_width_percent)
        text_y = text_position[1]
        
        # Word wrap text
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= text_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        # Draw text lines
        for i, line in enumerate(lines):
            y = text_y + i * font_size * 1.2
            draw.text((text_x, y), line, fill='white', font=font)
        
        logger.debug(f"Added text: {len(lines)} lines")
        
        # Save thumbnail
        if output_path is None:
            output_path = Path("thumbnail_temp.jpg")
        
        template.save(output_path, quality=95)
        logger.info(f"Thumbnail created: {output_path}")
        
        return output_path
        
    except Exception as e:
        logger.error(f"Failed to create thumbnail: {e}", exc_info=True)
        raise


def add_thumbnail_to_video_start(
    video_path: Path,
    thumbnail_path: Path,
    output_path: Path,
    duration: float = 0.1
) -> Path:
    """
    Add thumbnail image to the start of video for specified duration.
    
    Args:
        video_path: Path to input video
        thumbnail_path: Path to thumbnail image
        output_path: Path for output video
        duration: Duration to show thumbnail in seconds (default: 0.1)
        
    Returns:
        Path to output video with thumbnail at start
        
    Example:
        >>> final_video = add_thumbnail_to_video_start(
        ...     video_path=Path("video.mp4"),
        ...     thumbnail_path=Path("thumbnail.jpg"),
        ...     output_path=Path("video_with_thumbnail.mp4"),
        ...     duration=0.1
        ... )
    """
    try:
        from moviepy.editor import VideoFileClip, ImageClip, concatenate_videoclips
        
        logger.info(f"Adding thumbnail to video start (duration: {duration}s)")
        
        # Load video
        video = VideoFileClip(str(video_path))
        
        # Create thumbnail clip
        thumbnail_clip = ImageClip(str(thumbnail_path), duration=duration)
        
        # Resize thumbnail to match video dimensions
        thumbnail_clip = thumbnail_clip.resize(video.size)
        
        # Set FPS to match video
        thumbnail_clip = thumbnail_clip.set_fps(video.fps)
        
        # Concatenate thumbnail + video
        final_video = concatenate_videoclips([thumbnail_clip, video], method="compose")
        
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
        thumbnail_clip.close()
        final_video.close()
        
        logger.info(f"Video with thumbnail created: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Failed to add thumbnail to video: {e}", exc_info=True)
        raise
