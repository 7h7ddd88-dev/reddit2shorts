"""Chatterbox TTS provider implementation.

This module provides Chatterbox TTS integration with voice cloning support.

Requirements: 5.3, 5.4, 5.5
"""

from pathlib import Path
from typing import Optional

import aiohttp

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry

logger = get_logger(__name__)


class ChatterboxTTS(BaseTTSProvider):
    """Chatterbox TTS provider with voice cloning.
    
    This provider uses the Chatterbox TTS API which supports voice cloning
    and advanced speech synthesis parameters.
    
    Attributes:
        api_url: Chatterbox API base URL
        api_key: Optional API key for authentication
    
    Requirements:
        - 5.3: Use Chatterbox TTS API
        - 5.4: Retry on errors
        - 5.5: Save audio locally
    
    Example:
        >>> tts = ChatterboxTTS(
        ...     api_url="http://localhost:8000/api/v1/media/audio-tools/tts/chatterbox"
        ... )
        >>> audio_path = await tts.synthesize(
        ...     text="Hello world",
        ...     output_path=Path("output/audio.mp3"),
        ...     sample_audio_id="voice_sample_123",
        ...     exaggeration=0.5,
        ...     cfg_weight=0.5,
        ...     temperature=0.8
        ... )
    """
    
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None
    ):
        """Initialize Chatterbox TTS provider.
        
        Args:
            api_url: Chatterbox API endpoint URL
            api_key: Optional API key for authentication
        """
        self.api_url = api_url
        self.api_key = api_key
        logger.info(f"Chatterbox TTS initialized with URL: {api_url}")
    
    @async_retry(max_attempts=5, delay=2.0, backoff=2.0)
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "default",
        speed: float = 1.0,
        sample_audio_id: Optional[str] = None,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize speech using Chatterbox TTS.
        
        Args:
            text: Text to synthesize
            output_path: Path where to save the audio file
            voice: Voice identifier (not used if sample_audio_id provided)
            speed: Speech speed multiplier
            sample_audio_id: ID of voice sample for cloning
            exaggeration: Exaggeration parameter (0.0-1.0)
            cfg_weight: CFG weight parameter (0.0-1.0)
            temperature: Temperature parameter (0.0-1.0)
            **kwargs: Additional parameters
        
        Returns:
            Path to the saved audio file
        
        Raises:
            APIError: If synthesis fails
            RateLimitError: If rate limit is hit
        
        Requirements:
            - 5.3: Synthesize with Chatterbox
            - 5.4: Retry on errors
            - 5.5: Save audio locally
        """
        logger.info(
            f"Synthesizing speech with Chatterbox "
            f"(exaggeration={exaggeration}, cfg_weight={cfg_weight}, "
            f"temperature={temperature})"
        )
        logger.debug(f"Text: {text[:100]}...")
        
        # Prepare request data
        data = aiohttp.FormData()
        data.add_field('text', text)
        
        if sample_audio_id:
            data.add_field('sample_audio_id', sample_audio_id)
            logger.debug(f"Using voice sample: {sample_audio_id}")
        
        data.add_field('exaggeration', str(exaggeration))
        data.add_field('cfg_weight', str(cfg_weight))
        data.add_field('temperature', str(temperature))
        
        # Add any additional parameters
        for key, value in kwargs.items():
            data.add_field(key, str(value))
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {}
                if self.api_key:
                    headers['Authorization'] = f'Bearer {self.api_key}'
                
                async with session.post(
                    self.api_url,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=180)  # Longer timeout for voice cloning
                ) as response:
                    # Check for rate limit
                    if response.status == 429:
                        raise RateLimitError("Chatterbox TTS rate limit exceeded")
                    
                    # Check for errors
                    if response.status >= 400:
                        error_text = await response.text()
                        raise APIError(
                            f"Chatterbox TTS error {response.status}: {error_text}"
                        )
                    
                    # Read audio data
                    audio_data = await response.read()
                    
                    # Save to file
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(audio_data)
                    
                    logger.info(f"✅ Audio synthesized and saved to: {output_path}")
                    return output_path
                    
        except RateLimitError:
            raise
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Error synthesizing with Chatterbox: {e}")
            raise APIError(f"Chatterbox TTS synthesis failed: {e}") from e
    
    async def upload_voice_sample(
        self,
        audio_file_path: Path
    ) -> Optional[str]:
        """Upload a voice sample for cloning.
        
        Args:
            audio_file_path: Path to audio file to use as voice sample
        
        Returns:
            Sample audio ID if successful, None otherwise
        
        Example:
            >>> tts = ChatterboxTTS(api_url="...")
            >>> sample_id = await tts.upload_voice_sample(
            ...     Path("samples/my_voice.mp3")
            ... )
            >>> print(f"Sample ID: {sample_id}")
        """
        upload_url = self.api_url.replace('/tts/chatterbox', '/storage')
        
        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                
                # Read audio file
                audio_data = audio_file_path.read_bytes()
                data.add_field(
                    'file',
                    audio_data,
                    filename=audio_file_path.name,
                    content_type='audio/mpeg'
                )
                data.add_field('media_type', 'audio')
                
                headers = {}
                if self.api_key:
                    headers['Authorization'] = f'Bearer {self.api_key}'
                
                async with session.post(
                    upload_url,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        sample_id = result.get('file_id')
                        logger.info(f"Voice sample uploaded: {sample_id}")
                        return sample_id
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to upload voice sample: {response.status} - {error_text}"
                        )
                        return None
                        
        except Exception as e:
            logger.error(f"Error uploading voice sample: {e}")
            return None
