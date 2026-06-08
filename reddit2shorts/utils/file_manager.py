"""
File Manager for Reddit2Shorts

This module provides file management utilities for organizing workflow files,
including scripts, images, audio, and video files. It also handles cleanup
of old temporary files.

Requirements: 15.1, 15.5
"""

from pathlib import Path
from datetime import datetime, timedelta
import shutil
from typing import Optional
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class FileManager:
    """
    Manages file operations for Reddit2Shorts workflows.
    
    Handles creation and organization of workflow directories, provides
    path generation for various file types, and manages cleanup of old
    temporary files.
    """
    
    def __init__(self, output_dir: Path, temp_dir: Path, subfolder: Optional[str] = None):
        """
        Initialize FileManager.
        
        Args:
            output_dir: Directory for final output videos
            temp_dir: Directory for temporary workflow files
            subfolder: Optional subfolder within output_dir (e.g., "longform", "reddit")
        """
        self.output_dir = Path(output_dir)
        if subfolder:
            self.output_dir = self.output_dir / subfolder
        self.temp_dir = Path(temp_dir)
        
        # Create directories if they don't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"FileManager initialized: output={self.output_dir}, temp={self.temp_dir}")
    
    def get_workflow_dir(self, workflow_id: str) -> Path:
        """
        Get or create workflow directory.
        
        Args:
            workflow_id: Unique identifier for the workflow
            
        Returns:
            Path to the workflow directory
        """
        workflow_dir = self.temp_dir / workflow_id
        workflow_dir.mkdir(parents=True, exist_ok=True)
        return workflow_dir
    
    def get_script_path(self, workflow_id: str) -> Path:
        """
        Get path for script file.
        
        Args:
            workflow_id: Unique identifier for the workflow
            
        Returns:
            Path to the script JSON file
        """
        return self.get_workflow_dir(workflow_id) / "script.json"
    
    def get_image_path(self, workflow_id: str, index: int) -> Path:
        """
        Get path for image file.
        
        Args:
            workflow_id: Unique identifier for the workflow
            index: Image index number
            
        Returns:
            Path to the image file
        """
        return self.get_workflow_dir(workflow_id) / f"image_{index}.jpg"
    
    def get_audio_path(self, workflow_id: str, suffix: str = "") -> Path:
        """
        Get path for audio file.
        
        Args:
            workflow_id: Unique identifier for the workflow
            suffix: Optional suffix for filename (e.g., "_seg0")
            
        Returns:
            Path to the audio MP3 file
        """
        return self.get_workflow_dir(workflow_id) / f"audio{suffix}.mp3"
    
    def get_video_path(self, workflow_id: str, suffix: str = "final") -> Path:
        """
        Get path for video file.
        
        Args:
            workflow_id: Unique identifier for the workflow
            suffix: Video file suffix (e.g., "final", "raw", "with_music")
            
        Returns:
            Path to the video MP4 file
        """
        return self.get_workflow_dir(workflow_id) / f"video_{suffix}.mp4"
    
    def move_to_output(self, workflow_id: str, video_path: Path) -> Path:
        """
        Move final video to output directory.
        
        Args:
            workflow_id: Unique identifier for the workflow
            video_path: Path to the video file to move
            
        Returns:
            Path to the video in the output directory
        """
        output_path = self.output_dir / f"{workflow_id}.mp4"
        shutil.copy2(video_path, output_path)
        logger.info(f"Video saved to {output_path}")
        return output_path
    
    def cleanup_old_temp_files(self, days: int = 7):
        """
        Clean up temporary files older than specified days.
        
        Removes workflow directories that haven't been modified in the
        specified number of days.
        
        Args:
            days: Number of days after which to remove temp files (default: 7)
        """
        logger.info(f"Cleaning up temp files older than {days} days")
        
        cutoff_time = datetime.now() - timedelta(days=days)
        removed_count = 0
        
        for item in self.temp_dir.iterdir():
            if item.is_dir():
                # Check directory modification time
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < cutoff_time:
                    try:
                        shutil.rmtree(item)
                        logger.info(f"Removed old temp directory: {item}")
                        removed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to remove {item}: {e}")
        
        logger.info(f"Cleanup complete: removed {removed_count} directories")
    
    def cleanup_workflow(self, workflow_id: str):
        """
        Clean up specific workflow files.
        
        Removes all files and directories associated with a specific workflow.
        Uses retry logic for Windows file locking issues.
        
        Args:
            workflow_id: Unique identifier for the workflow to clean up
        """
        import gc
        import time
        
        workflow_dir = self.get_workflow_dir(workflow_id)
        if workflow_dir.exists():
            try:
                # Count files before cleanup
                files_before = sum(1 for _ in workflow_dir.rglob('*') if _.is_file())
                
                # Force garbage collection to release file handles
                gc.collect()
                time.sleep(0.5)
                
                # Try to remove directory with retry logic for Windows file locking
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        shutil.rmtree(workflow_dir)
                        logger.info(f"Cleaned up {files_before} temporary files for workflow {workflow_id}")
                        break
                    except PermissionError as e:
                        if attempt < max_retries - 1:
                            logger.debug(f"Cleanup attempt {attempt + 1} failed, retrying...")
                            time.sleep(1.0)
                        else:
                            raise e
            except Exception as e:
                logger.warning(f"Failed to clean up workflow {workflow_id}: {e}")
