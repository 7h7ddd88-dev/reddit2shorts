"""Pollinations TTS provider with API key rotation.

This module provides TTS using Pollinations.ai API with automatic key rotation
for reliability and rate limit handling.

Features:
- ElevenLabs voices (35+ voices)
- Automatic API key rotation
- Retry logic with exponential backoff
- Multiple audio formats support
"""

from pathlib import Path
from typing import Optional, List
import urllib.parse
import asyncio

import aiohttp

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class PollinationsTTS(BaseTTSProvider):
    """Pollinations TTS provider with key rotation.
    
    This provider uses Pollinations.ai TTS API with automatic API key rotation
    to handle rate limits and ensure reliability.
    
    Attributes:
        api_keys: List of Pollinations API keys for rotation
        current_key_index: Current key index for rotation
        base_url: Pollinations API base URL
    
    Example:
        >>> tts = PollinationsTTS(
        ...     api_keys=["key1", "key2", "key3"]
        ... )
        >>> audio_path = await tts.synthesize(
        ...     text="Hello world",
        ...     output_path=Path("output/audio.mp3"),
        ...     voice="rachel",
        ...     speed=1.0
        ... )
    """
    
    def __init__(
        self,
        api_url: Optional[str] = None,  # For compatibility with base class
        api_key: Optional[str] = None,  # For compatibility with base class
        api_keys: Optional[List[str]] = None,
        proxy: Optional[str] = None
    ):
        """Initialize Pollinations TTS provider.
        
        Args:
            api_url: Not used (for compatibility)
            api_key: Single API key (for compatibility)
            api_keys: List of API keys for rotation
            proxy: Proxy URL (e.g., "http://user:pass@host:port") or None
        """
        # Handle both single key and multiple keys
        if api_keys:
            self.api_keys = api_keys
        elif api_key:
            self.api_keys = [api_key]
        else:
            raise ValueError("At least one API key is required")
        
        self.current_key_index = 0
        self.base_url = "https://gen.pollinations.ai/audio"
        
        # Proxy configuration
        self.proxy = proxy
        if self.proxy:
            from reddit2shorts.utils.proxy import mask_proxy_url
            logger.info(f"Pollinations TTS proxy configured: {mask_proxy_url(self.proxy)}")
        
        logger.info(f"Pollinations TTS initialized with {len(self.api_keys)} API keys")
    
    def _get_next_key(self) -> str:
        """Get next API key with rotation.
        
        Returns:
            API key
        """
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key
    
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize speech using Pollinations TTS with key rotation.
        
        Automatically splits long text into chunks if needed (max 4096 chars per request).
        
        Args:
            text: Text to synthesize
            output_path: Path where to save the audio file
            voice: Voice name (rachel, bella, adam, etc.)
            speed: Speech speed multiplier (0.25-4.0)
            **kwargs: Additional parameters:
                - response_format: Audio format (mp3, opus, aac, flac, wav, pcm)
                - model: TTS model (tts-1, elevenlabs)
        
        Returns:
            Path to the saved audio file, or None on failure
        
        Raises:
            APIError: If synthesis fails after all retries
        """
        logger.info(f"Synthesizing speech with Pollinations (voice={voice}, speed={speed})")
        
        # Check text length and split if needed (Pollinations max: 4096 chars)
        MAX_CHARS = 4000  # Use 4000 to be safe
        
        if len(text) > MAX_CHARS:
            logger.warning(f"Text too long ({len(text)} chars), splitting into chunks (max {MAX_CHARS} chars)")
            return await self._synthesize_long_text(text, output_path, voice, speed, **kwargs)
        
        logger.debug(f"Text: {text[:100]}...")
        
        # Get parameters from kwargs (passed from config)
        response_format = kwargs.get('response_format', 'mp3')
        model = kwargs.get('model')  # Must be provided from config
        
        # Try all keys with rotation
        for attempt in range(len(self.api_keys)):
            try:
                api_key = self._get_next_key()
                
                # Use simple GET endpoint (more reliable than POST)
                encoded_text = urllib.parse.quote(text)
                url = f"{self.base_url}/{encoded_text}"
                
                params = {
                    "voice": voice,
                    "key": api_key,
                    "response_format": response_format,
                    "speed": str(speed)
                }
                
                # Add model if specified
                if model:
                    params["model"] = model
                
                logger.debug(f"Attempt {attempt + 1}/{len(self.api_keys)} with key {self.current_key_index}")
                
                # Create aiohttp session with proxy support
                from reddit2shorts.utils.proxy import create_aiohttp_connector
                
                connector = create_aiohttp_connector(self.proxy)
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    # For HTTP/HTTPS proxies, pass proxy parameter to request
                    request_kwargs = {
                        "params": params,
                        "timeout": aiohttp.ClientTimeout(total=120)
                    }
                    
                    if self.proxy and not connector:  # HTTP/HTTPS proxy (not SOCKS5)
                        request_kwargs["proxy"] = self.proxy
                    
                    async with session.get(url, **request_kwargs) as response:
                        
                        # Check for rate limit
                        if response.status == 429:
                            logger.warning(f"Rate limit hit with key {self.current_key_index}, rotating...")
                            continue
                        
                        # Check for errors
                        if response.status == 403:
                            error_text = await response.text()
                            logger.warning(f"Key {self.current_key_index} blocked (403): {error_text[:200]}")
                            continue
                        
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.warning(f"Key {self.current_key_index} failed: {response.status} - {error_text[:200]}")
                            
                            # Try next key
                            if attempt < len(self.api_keys) - 1:
                                continue
                            else:
                                raise APIError(f"All Pollinations keys failed. Last error: {error_text[:200]}")
                        
                        # Check content type
                        content_type = response.headers.get('Content-Type', '')
                        
                        if 'audio' not in content_type and 'octet-stream' not in content_type:
                            logger.warning(f"Unexpected content type: {content_type}")
                            
                            # Try next key
                            if attempt < len(self.api_keys) - 1:
                                continue
                            else:
                                raise APIError(f"Unexpected content type: {content_type}")
                        
                        # Read audio data
                        audio_data = await response.read()
                        
                        # Validate audio size
                        if len(audio_data) < 1000:  # Less than 1KB
                            logger.warning(f"Audio too small: {len(audio_data)} bytes")
                            
                            # Try next key
                            if attempt < len(self.api_keys) - 1:
                                continue
                            else:
                                raise APIError(f"Audio too small: {len(audio_data)} bytes")
                        
                        # Save to file
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(audio_data)
                        
                        logger.info(f"✅ Audio synthesized and saved to: {output_path}")
                        logger.info(f"Size: {len(audio_data):,} bytes ({len(audio_data)/1024:.1f} KB)")
                        
                        return output_path
                        
            except asyncio.TimeoutError:
                logger.warning(f"Timeout with key {self.current_key_index}")
                
                # Try next key
                if attempt < len(self.api_keys) - 1:
                    continue
                else:
                    raise APIError("All Pollinations keys timed out")
            
            except APIError:
                raise
            
            except Exception as e:
                logger.warning(f"Error with key {self.current_key_index}: {e}")
                
                # Try next key
                if attempt < len(self.api_keys) - 1:
                    continue
                else:
                    raise APIError(f"All Pollinations keys failed: {e}")
        
        raise APIError("Failed to synthesize speech with Pollinations")
    
    async def get_available_voices(self) -> List[str]:
        """Get list of available voices.
        
        Returns:
            List of voice names
        """
        # All ElevenLabs voices available in Pollinations
        return [
            # Default OpenAI-style voices
            "alloy", "echo", "fable", "onyx", "nova", "shimmer",
            
            # ElevenLabs premium voices
            "ash", "ballad", "coral", "sage", "verse",
            
            # ElevenLabs character voices (female)
            "rachel", "domi", "bella", "elli", "charlotte",
            "dorothy", "sarah", "emily", "lily", "matilda",
            
            # Male voices
            "adam", "antoni", "arnold", "josh", "sam",
            "daniel", "charlie", "james", "fin", "callum",
            "liam", "george", "brian", "bill"
        ]
    
    def _split_text(self, text: str, max_chars: int = 4000) -> List[str]:
        """Split text into chunks at sentence boundaries.
        
        Args:
            text: Text to split
            max_chars: Maximum characters per chunk
        
        Returns:
            List of text chunks
        """
        # Split by sentences
        sentences = text.replace('! ', '!|').replace('? ', '?|').replace('. ', '.|').split('|')
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # If adding this sentence exceeds limit, save current chunk
            if len(current_chunk) + len(sentence) + 1 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # Single sentence is too long, force split
                    chunks.append(sentence[:max_chars])
                    current_chunk = sentence[max_chars:]
            else:
                current_chunk += " " + sentence if current_chunk else sentence
        
        # Add last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    async def _synthesize_long_text(
        self,
        text: str,
        output_path: Path,
        voice: str,
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize long text by splitting into chunks and concatenating.
        
        Uses moviepy for concatenation (compatible with Python 3.14+).
        
        Args:
            text: Long text to synthesize
            output_path: Path where to save the final audio file
            voice: Voice name
            speed: Speech speed
            **kwargs: Additional parameters
        
        Returns:
            Path to the concatenated audio file
        """
        import shutil
        from moviepy import AudioFileClip, concatenate_audioclips
        
        logger.info(f"Splitting text into chunks (total: {len(text)} chars)")
        
        # Split text into chunks
        chunks = self._split_text(text, max_chars=4000)
        logger.info(f"Split into {len(chunks)} chunks")
        
        # Synthesize each chunk
        chunk_paths = []
        temp_dir = output_path.parent / "temp_chunks"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            for i, chunk in enumerate(chunks):
                logger.info(f"Synthesizing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
                
                chunk_path = temp_dir / f"chunk_{i}.mp3"
                
                # Synthesize chunk (will not trigger recursion since chunks are < 4000 chars)
                result = await self.synthesize(
                    text=chunk,
                    output_path=chunk_path,
                    voice=voice,
                    speed=speed,
                    **kwargs
                )
                
                if result:
                    chunk_paths.append(result)
                else:
                    raise APIError(f"Failed to synthesize chunk {i+1}")
            
            # Concatenate all chunks using moviepy
            logger.info(f"Concatenating {len(chunk_paths)} audio chunks with moviepy")
            
            # Load all audio clips
            audio_clips = []
            for chunk_path in chunk_paths:
                clip = AudioFileClip(str(chunk_path))
                audio_clips.append(clip)
            
            # Concatenate
            final_audio = concatenate_audioclips(audio_clips)
            
            # Export
            output_path.parent.mkdir(parents=True, exist_ok=True)
            final_audio.write_audiofile(
                str(output_path),
                codec='libmp3lame',
                bitrate='192k',
                logger=None  # Disable moviepy logging
            )
            
            # Close clips
            for clip in audio_clips:
                clip.close()
            final_audio.close()
            
            logger.info(f"✅ Long audio synthesized and saved to: {output_path}")
            logger.info(f"Total duration: {final_audio.duration:.1f}s")
            
            return output_path
            
        finally:
            # Cleanup temp chunks
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temp chunks directory")
