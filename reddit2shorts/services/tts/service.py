"""TTS service orchestrator.

This module provides the main TTS service that manages provider selection
and configuration.

Requirements: 5.1
"""

from pathlib import Path
from typing import Any, Dict, Optional

from reddit2shorts.core.exceptions import APIError
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.services.tts.chatterbox import ChatterboxTTS
from reddit2shorts.services.tts.kokoro import KokoroTTS
from reddit2shorts.services.tts.kokoro_onnx import KokoroOnnxTTS
from reddit2shorts.services.tts.local_server import LocalServerTTS
from reddit2shorts.services.tts.pollinations_tts import PollinationsTTS
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class TTSService:
    """TTS service with provider selection.
    
    This service manages TTS providers and provides a unified interface
    for speech synthesis.
    
    Attributes:
        provider: Active TTS provider instance
        provider_name: Name of the active provider
        config: Configuration dictionary
    
    Requirements:
        - 5.1: Synthesize speech from text
    
    Example:
        >>> config = {
        ...     "provider": "kokoro",
        ...     "api_url": "http://localhost:8000/api/v1/media/audio-tools/tts/kokoro",
        ...     "voice": "af_bella",
        ...     "speed": 1.0
        ... }
        >>> service = TTSService(config)
        >>> audio_path = await service.synthesize(
        ...     text="Hello world",
        ...     output_path=Path("output/audio.mp3")
        ... )
    """
    
    PROVIDER_CLASSES = {
        "local": LocalServerTTS,
        "kokoro": KokoroOnnxTTS,  # Python библиотека kokoro-onnx
        "chatterbox": ChatterboxTTS,
        "pollinations": PollinationsTTS  # Pollinations.ai TTS with key rotation
    }
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize TTS service.
        
        Args:
            config: Configuration dictionary with provider settings
        
        Raises:
            ValueError: If provider is not recognized
        """
        self.config = config
        self.provider_name = config.get("provider", "local")
        
        # Create provider instance
        provider_class = self.PROVIDER_CLASSES.get(self.provider_name)
        if not provider_class:
            raise ValueError(f"Unknown TTS provider: {self.provider_name}")
        
        # Get API URL based on provider
        if self.provider_name == "local":
            api_url = config.get("local_url")
            if not api_url:
                raise ValueError("local_url is required for local provider")
            api_key = None
        elif self.provider_name == "kokoro":
            # Kokoro ONNX - Python библиотека, не требует API URL
            api_url = None
            api_key = None
        elif self.provider_name == "chatterbox":
            api_url = config.get("chatterbox_api_url")
            api_key = config.get("chatterbox_api_key")
            if not api_url:
                raise ValueError("chatterbox_api_url is required for chatterbox provider")
        elif self.provider_name == "pollinations":
            # Pollinations TTS - использует API keys для ротации
            api_keys = config.get("pollinations_api_keys")
            if not api_keys:
                raise ValueError("pollinations_api_keys is required for pollinations provider")
            
            # Get proxy from config (default_proxy)
            proxy = config.get("proxy")
            
            # Create provider with key rotation and proxy
            self.provider = PollinationsTTS(api_keys=api_keys, proxy=proxy)
            logger.info(f"TTS service initialized with provider: {self.provider_name}")
            return
        else:
            raise ValueError(f"Unknown provider: {self.provider_name}")
        
        self.provider = provider_class(api_url=api_url, api_key=api_key)
        
        logger.info(f"TTS service initialized with provider: {self.provider_name}")
    
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize speech from text.
        
        Args:
            text: Text to synthesize
            output_path: Path where to save the audio file
            voice: Voice identifier (uses config default if not provided)
            speed: Speech speed (uses config default if not provided)
            **kwargs: Additional provider-specific parameters
        
        Returns:
            Path to the saved audio file
        
        Raises:
            APIError: If synthesis fails
        
        Requirements:
            - 5.1: Synthesize speech from text
        
        Example:
            >>> service = TTSService(config)
            >>> audio_path = await service.synthesize(
            ...     text="Hello world",
            ...     output_path=Path("output/audio.mp3"),
            ...     voice="af_bella",
            ...     speed=1.2
            ... )
        """
        # Use config defaults if not provided
        if voice is None:
            if self.provider_name == "pollinations":
                voice = self.config.get("pollinations_voice")
                if not voice:
                    raise ValueError("pollinations_voice is required in config")
                logger.debug(f"Using voice from config: pollinations_voice={voice}")
            else:
                voice = self.config.get("kokoro_voice")
                if not voice:
                    raise ValueError("kokoro_voice is required in config")
        if speed is None:
            if self.provider_name == "pollinations":
                speed = self.config.get("pollinations_speed", 1.0)
            else:
                speed = self.config.get("kokoro_speed", 1.0)
        
        logger.info(
            f"Synthesizing speech with {self.provider_name} "
            f"(voice={voice}, speed={speed})"
        )
        
        try:
            # Add provider-specific parameters from config
            if self.provider_name == "local":
                kwargs.setdefault('tts_engine', self.config.get('tts_engine', 'kokoro'))
                kwargs.setdefault('chatterbox_clone_voice_id', self.config.get('chatterbox_clone_voice_id'))
                kwargs.setdefault('chatterbox_exaggeration', self.config.get('chatterbox_exaggeration', 1.0))
                kwargs.setdefault('chatterbox_cfg_weight', self.config.get('chatterbox_cfg_weight', 1.0))
                kwargs.setdefault('chatterbox_temperature', self.config.get('chatterbox_temperature', 1.0))
            elif self.provider_name == "chatterbox":
                kwargs.setdefault('exaggeration', self.config.get('exaggeration', 0.5))
                kwargs.setdefault('cfg_weight', self.config.get('cfg_weight', 0.5))
                kwargs.setdefault('temperature', self.config.get('temperature', 0.8))
                kwargs.setdefault('sample_audio_id', self.config.get('sample_audio_id'))
            elif self.provider_name == "pollinations":
                # Add Pollinations-specific parameters from config
                model = self.config.get('pollinations_model')
                if not model:
                    raise ValueError("pollinations_model is required in config")
                kwargs.setdefault('model', model)
                kwargs.setdefault('response_format', self.config.get('pollinations_response_format', 'mp3'))
            
            # Synthesize
            result = await self.provider.synthesize(
                text=text,
                output_path=output_path,
                voice=voice,
                speed=speed,
                **kwargs
            )
            
            return result
            
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise APIError(f"TTS synthesis failed: {e}") from e
    
    async def synthesize_segments(
        self,
        segments: list[tuple[str, Path]],
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs
    ) -> list[Path]:
        """Synthesize multiple text segments.
        
        Args:
            segments: List of (text, output_path) tuples
            voice: Voice identifier
            speed: Speech speed
            **kwargs: Additional parameters
        
        Returns:
            List of paths to saved audio files
        
        Example:
            >>> service = TTSService(config)
            >>> segments = [
            ...     ("Segment 1", Path("output/seg1.mp3")),
            ...     ("Segment 2", Path("output/seg2.mp3"))
            ... ]
            >>> audio_paths = await service.synthesize_segments(segments)
        """
        logger.info(f"Synthesizing {len(segments)} segments")
        
        results = []
        for i, (text, output_path) in enumerate(segments):
            logger.debug(f"Synthesizing segment {i+1}/{len(segments)}")
            
            try:
                result = await self.synthesize(
                    text=text,
                    output_path=output_path,
                    voice=voice,
                    speed=speed,
                    **kwargs
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to synthesize segment {i+1}: {e}")
                results.append(None)
        
        successful = sum(1 for r in results if r is not None)
        logger.info(
            f"Segment synthesis complete: {successful}/{len(segments)} successful"
        )
        
        return results
    
    def get_provider_name(self) -> str:
        """Get the name of the active provider.
        
        Returns:
            Provider name
        """
        return self.provider_name
    
    async def get_available_voices(self) -> list[str]:
        """Get list of available voices from the provider.
        
        Returns:
            List of voice names
        
        Example:
            >>> service = TTSService(config)
            >>> voices = await service.get_available_voices()
            >>> print(voices)
        """
        if hasattr(self.provider, 'get_available_voices'):
            return await self.provider.get_available_voices()
        else:
            logger.warning(
                f"Provider {self.provider_name} does not support voice listing"
            )
            return []
    
    async def upload_voice_sample(
        self,
        audio_file_path: Path
    ) -> Optional[str]:
        """Upload a voice sample for cloning (Chatterbox only).
        
        Args:
            audio_file_path: Path to audio file
        
        Returns:
            Sample audio ID if successful
        
        Example:
            >>> service = TTSService(config)  # config with provider="chatterbox"
            >>> sample_id = await service.upload_voice_sample(
            ...     Path("samples/my_voice.mp3")
            ... )
        """
        if hasattr(self.provider, 'upload_voice_sample'):
            return await self.provider.upload_voice_sample(audio_file_path)
        else:
            logger.warning(
                f"Provider {self.provider_name} does not support voice cloning"
            )
            return None
