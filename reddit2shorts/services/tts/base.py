"""Base TTS provider interface.

This module defines the abstract base class for all TTS providers.

Requirements: 5.1, 5.6
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers.
    
    All TTS providers must implement this interface to ensure consistent
    behavior across different providers (Kokoro, Chatterbox, etc.).
    
    Requirements:
        - 5.1: Synthesize speech from text
        - 5.6: Support voice and speed parameters
    """
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "default",
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Synthesize speech from text.
        
        This method must be implemented by all providers to generate
        audio from text input.
        
        Args:
            text: Text to synthesize
            output_path: Path where to save the audio file
            voice: Voice identifier or name
            speed: Speech speed multiplier (1.0 = normal)
            **kwargs: Additional provider-specific parameters
        
        Returns:
            Path to the saved audio file, or None on failure
        
        Raises:
            APIError: If synthesis fails
            RateLimitError: If rate limit is hit
        
        Requirements:
            - 5.1: Synthesize speech from text
            - 5.5: Save audio locally
            - 5.6: Support voice and speed parameters
        
        Example:
            >>> provider = KokoroTTS(api_key="...")
            >>> audio_path = await provider.synthesize(
            ...     text="Hello world",
            ...     output_path=Path("output/audio.mp3"),
            ...     voice="en-US-male",
            ...     speed=1.2
            ... )
        """
        pass
    
    def get_provider_name(self) -> str:
        """Get the name of this provider.
        
        Returns:
            Provider name (e.g., "Kokoro", "Chatterbox")
        """
        return self.__class__.__name__.replace('TTS', '')
