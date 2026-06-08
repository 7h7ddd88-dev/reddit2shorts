"""Kokoro TTS provider implementation.

This module provides Kokoro TTS integration for speech synthesis.

Requirements: 5.2, 5.4, 5.5
"""

from pathlib import Path
from typing import Optional

import aiohttp

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.utils.logger import get_logger
from reddit2shorts.utils.retry import async_retry

logger = get_logger(__name__)


class KokoroTTS(BaseTTSProvider):
    """Kokoro TTS provider.
    
    This provider uses the Kokoro TTS API to synthesize speech from text.
    
    Attributes:
        api_url: Kokoro API base URL
        api_key: Optional API key for authentication
    
    Requirements:
        - 5.2: Use Kokoro TTS API
        - 5.4: Retry on errors
        - 5.5: Save audio locally
    
    Example:
        >>> tts = KokoroTTS(
        ...     api_url="http://localhost:8000/api/v1/media/audio-tools/tts/kokoro"
        ... )
        >>> audio_path = await tts.synthesize(
        ...     text="Hello world",
        ...     output_path=Path("output/audio.mp3"),
        ...     voice="af_bella",
        ...     speed=1.0
        ... )
    """
    
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None
    ):
        """Initialize Kokoro TTS provider.
        
        Args:
            api_url: Kokoro API endpoint URL
            api_key: Optional API key for authentication
        """
        self.api_url = api_url
        self.api_key = api_key
        logger.info(f"Kokoro TTS initialized with URL: {api_url}")
    
    @async_retry(max_attempts=5, delay=2.0, backoff=2.0)
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "af_bella",
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize speech using Kokoro TTS.
        
        Args:
            text: Text to synthesize
            output_path: Path where to save the audio file
            voice: Voice name (e.g., "af_bella", "am_adam")
            speed: Speech speed multiplier
            **kwargs: Additional parameters
        
        Returns:
            Path to the saved audio file
        
        Raises:
            APIError: If synthesis fails
            RateLimitError: If rate limit is hit
        
        Requirements:
            - 5.2: Synthesize with Kokoro
            - 5.4: Retry on errors
            - 5.5: Save audio locally
        """
        logger.info(f"Synthesizing speech with Kokoro (voice={voice}, speed={speed})")
        logger.debug(f"Text: {text[:100]}...")
        
        # Prepare request data
        data = aiohttp.FormData()
        data.add_field('text', text)
        data.add_field('voice', voice)
        data.add_field('speed', str(speed))
        
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
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    # Check for rate limit
                    if response.status == 429:
                        raise RateLimitError("Kokoro TTS rate limit exceeded")
                    
                    # Check for errors
                    if response.status >= 400:
                        error_text = await response.text()
                        raise APIError(
                            f"Kokoro TTS error {response.status}: {error_text}"
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
            logger.error(f"Error synthesizing with Kokoro: {e}")
            raise APIError(f"Kokoro TTS synthesis failed: {e}") from e
    
    async def get_available_voices(self) -> list[str]:
        """Get list of available voices.
        
        Returns:
            List of voice names
        
        Example:
            >>> tts = KokoroTTS(api_url="...")
            >>> voices = await tts.get_available_voices()
            >>> print(voices)
            ['af_bella', 'am_adam', 'bf_emma', ...]
        """
        voices_url = self.api_url.replace('/tts/kokoro', '/tts/kokoro/voices')
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {}
                if self.api_key:
                    headers['Authorization'] = f'Bearer {self.api_key}'
                
                async with session.get(
                    voices_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        voices = data.get('voices', [])
                        logger.info(f"Retrieved {len(voices)} Kokoro voices")
                        return voices
                    else:
                        logger.warning(f"Failed to get Kokoro voices: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Error getting Kokoro voices: {e}")
            return []
