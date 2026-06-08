"""
Service Factory for creating and initializing services.

This module provides a centralized way to create services used by orchestrators,
reducing code duplication and making it easier to add new flows.
"""

from typing import Dict, Any, Optional
from pathlib import Path

from reddit2shorts.services.llm.service import LLMService
from reddit2shorts.services.tts.service import TTSService
from reddit2shorts.services.video_moviepy import MoviePyVideoService
from reddit2shorts.services.video_local import LocalVideoService
from reddit2shorts.services.video import VideoService
from reddit2shorts.services.youtube import YouTubeUploader
from reddit2shorts.utils.file_manager import FileManager
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class ServiceFactory:
    """
    Factory for creating services used by orchestrators.
    
    This centralizes service initialization logic that was previously
    duplicated across multiple orchestrator classes.
    """
    
    @staticmethod
    def create_llm_service(config: Dict[str, Any]) -> LLMService:
        """
        Create LLM service from configuration.
        
        Args:
            config: Full configuration dictionary
            
        Returns:
            Initialized LLM service
        """
        llm_config = config.get("llm", {})
        return LLMService(llm_config)
    
    @staticmethod
    def create_tts_service(
        config: Dict[str, Any],
        flow_name: Optional[str] = None
    ) -> TTSService:
        """
        Create TTS service from configuration.
        
        Supports flow-specific TTS configurations (e.g., knights.tts, darkmotiv.tts)
        or falls back to default TTS config.
        
        Args:
            config: Full configuration dictionary
            flow_name: Optional flow name (e.g., "knights", "darkmotiv", "reddit")
                      If provided, looks for flow-specific TTS config
            
        Returns:
            Initialized TTS service
        """
        # Convert Pydantic model to dict if needed
        if hasattr(config, 'model_dump'):
            config = config.model_dump(mode='json')  # Include all fields, even defaults
        
        # Try flow-specific TTS config first
        tts_config = None
        if flow_name:
            flow_config = config.get(flow_name, {})
            flow_tts_config = flow_config.get("tts")
            if flow_tts_config:
                logger.info(f"Using flow-specific TTS config for {flow_name}")
                tts_config = flow_tts_config.copy()
        
        # Fall back to global TTS config
        if tts_config is None:
            logger.info("Using global TTS config")
            tts_config = config.get("tts", {}).copy()
        else:
            # Merge with global TTS config for missing parameters
            global_tts_config = config.get("tts", {})
            
            # Подставляем model и response_format из глобального конфига, если их нет
            if "pollinations_model" not in tts_config and "pollinations_model" in global_tts_config:
                tts_config["pollinations_model"] = global_tts_config["pollinations_model"]
                logger.info(f"Using pollinations_model from global config: {tts_config['pollinations_model']}")
            
            if "pollinations_response_format" not in tts_config and "pollinations_response_format" in global_tts_config:
                tts_config["pollinations_response_format"] = global_tts_config["pollinations_response_format"]
                logger.info(f"Using pollinations_response_format from global config: {tts_config['pollinations_response_format']}")
        
        logger.info(f"DEBUG: TTS config keys: {list(tts_config.keys())}")
        logger.info(f"DEBUG: pollinations_voice = {tts_config.get('pollinations_voice')}")
        
        # Если используется pollinations и нет ключей в tts секции,
        # берем их из общей pollinations секции
        if tts_config.get("provider") == "pollinations":
            if not tts_config.get("pollinations_api_keys"):
                pollinations_config = config.get("pollinations", {})
                api_keys = pollinations_config.get("api_keys")
                if api_keys:
                    tts_config["pollinations_api_keys"] = api_keys
                    logger.info("Using Pollinations API keys from global pollinations section")
            
            # Add default proxy if not specified
            if "proxy" not in tts_config:
                default_proxy = config.get("default_proxy")
                if default_proxy:
                    tts_config["proxy"] = default_proxy
                    logger.info(f"Using default proxy for Pollinations TTS")
        
        return TTSService(tts_config)
    
    @staticmethod
    def create_video_service(config: Dict[str, Any]) -> VideoService:
        """
        Create video service from configuration.
        
        Supports multiple providers: moviepy, local, api
        
        Args:
            config: Full configuration dictionary
            
        Returns:
            Initialized video service
        """
        video_config = config.get("video", {})
        provider = video_config.get("provider", "moviepy")
        
        if provider == "moviepy":
            logger.info("Creating MoviePy VideoService")
            return MoviePyVideoService(video_config)
        elif provider == "local":
            logger.info("Creating Local VideoService")
            return LocalVideoService(video_config)
        else:
            logger.info(f"Creating VideoService with provider: {provider}")
            return VideoService(video_config)
    
    @staticmethod
    def create_youtube_uploader(
        config: Dict[str, Any], 
        flow_name: Optional[str] = None
    ) -> YouTubeUploader:
        """
        Create YouTube uploader from configuration.
        
        Supports flow-specific YouTube configurations (e.g., knights, darkmotiv)
        or falls back to default YouTube config.
        
        Args:
            config: Full configuration dictionary
            flow_name: Optional flow name (e.g., "knights", "darkmotiv")
                      If provided, looks for flow-specific YouTube config
            
        Returns:
            Initialized YouTube uploader
        """
        # Try flow-specific config first
        if flow_name:
            flow_config = config.get(flow_name, {})
            youtube_config = flow_config.get("youtube")
            if youtube_config:
                logger.info(f"Creating YouTube uploader for {flow_name} flow")
                # CRITICAL FIX: Add scheduled_publishing to youtube_config
                # YouTube uploader needs this for scheduled publishing to work
                youtube_config_with_scheduling = youtube_config.copy()
                youtube_config_with_scheduling["scheduled_publishing"] = config.get("scheduled_publishing", {})
                return YouTubeUploader(youtube_config_with_scheduling)
        
        # Fall back to default YouTube config
        youtube_config = config.get("youtube", {})
        logger.info("Creating YouTube uploader with default config")
        # Also add scheduled_publishing for default config
        youtube_config_with_scheduling = youtube_config.copy()
        youtube_config_with_scheduling["scheduled_publishing"] = config.get("scheduled_publishing", {})
        return YouTubeUploader(youtube_config_with_scheduling)
    
    @staticmethod
    def create_image_service(config: Dict[str, Any]) -> "ImageGenerator":
        """
        Create image generation service from configuration.
        
        Automatically adds default_proxy from config for Pollinations Image API.
        
        Args:
            config: Full configuration dictionary
            
        Returns:
            Initialized ImageGenerator
        """
        from reddit2shorts.services.image import ImageGenerator
        
        image_config = config.get("image", {}).copy()
        
        # Add pollinations config (API keys)
        image_config["pollinations"] = config.get("pollinations", {})
        
        # Add default proxy if not specified
        if "proxy" not in image_config:
            default_proxy = config.get("default_proxy")
            if default_proxy:
                image_config["proxy"] = default_proxy
                logger.info("Using default proxy for Pollinations Image API")
        
        return ImageGenerator(image_config)
    
    @staticmethod
    def create_file_manager(
        config: Dict[str, Any],
        flow_name: Optional[str] = None
    ) -> FileManager:
        """
        Create file manager from configuration.
        
        Supports flow-specific output/temp directories or uses defaults.
        
        Args:
            config: Full configuration dictionary
            flow_name: Optional flow name (e.g., "knights", "darkmotiv", "longform")
                      If provided, looks for flow-specific directories and creates subfolder
            
        Returns:
            Initialized file manager
        """
        # Try flow-specific directories first
        if flow_name:
            flow_config = config.get(flow_name, {})
            output_dir = flow_config.get("output_dir")
            temp_dir = flow_config.get("temp_dir")
            
            if output_dir and temp_dir:
                logger.info(f"Creating FileManager for {flow_name} flow")
                return FileManager(
                    output_dir=Path(output_dir),
                    temp_dir=Path(temp_dir),
                    subfolder=None  # Flow-specific dirs don't need subfolder
                )
        
        # Fall back to default directories with subfolder
        output_dir = config.get("output_dir", "./output")
        temp_dir = config.get("temp_dir", "./temp")
        
        logger.info("Creating FileManager with default directories")
        return FileManager(
            output_dir=Path(output_dir),
            temp_dir=Path(temp_dir),
            subfolder=flow_name  # Use flow_name as subfolder (e.g., "longform")
        )
