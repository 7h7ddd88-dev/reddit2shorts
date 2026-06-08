"""Kokoro TTS provider using official kokoro Python library.

This module provides TTS using the official kokoro library from hexgrad (NO external server needed).
Official repo: https://github.com/hexgrad/kokoro
"""

from pathlib import Path
from typing import Optional
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.core.exceptions import APIError
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class KokoroOnnxTTS(BaseTTSProvider):
    """TTS using official kokoro Python library (полностью локально, без сервера)."""
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize Kokoro TTS.
        
        Args:
            api_url: Not used (для совместимости)
            api_key: Not used (для совместимости)
        """
        self.logger = logger
        self.pipeline = None
        
    def _load_model(self):
        """Load Kokoro model (lazy loading)."""
        if self.pipeline is None:
            try:
                from kokoro import KPipeline
                self.logger.info("Loading Kokoro model...")
                # lang_code='a' для английского (American)
                self.pipeline = KPipeline(lang_code='a')
                self.logger.info("Kokoro model loaded successfully")
            except ImportError:
                raise APIError(
                    "kokoro library not installed. "
                    "Install it with: pip install kokoro>=0.9.2 soundfile\n"
                    "Also install espeak-ng: apt-get install espeak-ng (Linux) or choco install espeak-ng (Windows)"
                )
            except Exception as e:
                raise APIError(f"Failed to load Kokoro model: {e}")
    
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "af_heart",
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Generate speech using Kokoro.
        
        Args:
            text: Text to synthesize
            output_path: Path to save audio file
            voice: Voice ID (af_heart, af_bella, af_nicole, af_sarah, af_sky, am_adam, am_michael, bf_emma, bf_isabella, bm_george, bm_lewis)
            speed: Speech speed (0.5-2.0)
            **kwargs: Additional parameters (ignored)
            
        Returns:
            Path to generated audio file, or None on failure
        """
        try:
            # Load model if not loaded
            self._load_model()
            
            self.logger.info(f"Generating TTS with Kokoro: voice={voice}, speed={speed}")
            
            # Generate audio using pipeline
            # pipeline() returns a generator that yields (graphemes, phonemes, audio)
            generator = self.pipeline(text, voice=voice, speed=speed)
            
            # Collect all audio chunks
            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(generator):
                self.logger.debug(f"Generated chunk {i}: {len(audio)} samples")
                audio_chunks.append(audio)
            
            if not audio_chunks:
                raise Exception("No audio generated")
            
            # Concatenate all chunks
            import numpy as np
            full_audio = np.concatenate(audio_chunks)
            
            # Save to file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save as WAV file using soundfile
            import soundfile as sf
            sf.write(str(output_path), full_audio, 24000)  # Kokoro uses 24kHz
            
            self.logger.info(f"Audio saved: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"TTS synthesis failed: {e}")
            return None
    
    async def get_available_voices(self) -> list:
        """Get list of available Kokoro voices.
        
        Returns:
            List of voice IDs
        """
        # Официальный список голосов из документации Kokoro v1.0
        # https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
        return [
            "af_heart",  # American Female (default)
            "af_bella",
            "af_nicole",
            "af_sarah",
            "af_sky",
            "am_adam",
            "am_michael",
            "bf_emma",
            "bf_isabella",
            "bm_george",
            "bm_lewis"
        ]
