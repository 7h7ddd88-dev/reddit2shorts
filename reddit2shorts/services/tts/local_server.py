"""Local AI Agents No-Code Tools TTS provider.

This module provides TTS using the local server (как в n8n).
"""

import aiohttp
from pathlib import Path
from typing import Optional
from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.core.exceptions import APIError
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class LocalServerTTS(BaseTTSProvider):
    """TTS using local AI Agents No-Code Tools server (как в n8n)."""
    
    def __init__(self, api_url: str, api_key: Optional[str] = None):
        """Initialize local server TTS.
        
        Args:
            api_url: URL локального сервера
            api_key: Not used for local server
        """
        self.base_url = api_url
        self.logger = logger
    
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "af",
        speed: float = 1.0,
        **kwargs
    ) -> Optional[Path]:
        """Generate speech using local server.
        
        Args:
            text: Text to synthesize
            output_path: Path to save audio file
            voice: Voice for Kokoro
            speed: Speed for Kokoro
            **kwargs: Additional parameters:
                - tts_engine: "kokoro" or "chatterbox"
                - chatterbox_*: Chatterbox parameters
            
        Returns:
            Path to generated audio file, or None on failure
        """
        tts_engine = kwargs.get('tts_engine', 'kokoro')
        
        try:
            if tts_engine == 'kokoro':
                return await self._synthesize_kokoro(text, output_path, voice, speed)
            elif tts_engine == 'chatterbox':
                return await self._synthesize_chatterbox(text, output_path, **kwargs)
            else:
                self.logger.error(f"Unknown TTS engine: {tts_engine}")
                return None
                
        except Exception as e:
            self.logger.error(f"TTS synthesis failed: {e}")
            raise APIError(f"TTS synthesis failed: {e}") from e
    
    async def _synthesize_kokoro(self, text: str, output_path: Path, voice: str, speed: float) -> Optional[Path]:
        """Synthesize using Kokoro TTS (как в n8n)."""
        url = f"{self.base_url}/api/v1/media/audio-tools/tts/kokoro"
        
        self.logger.info(f"Generating TTS with Kokoro: voice={voice}, speed={speed}")
        
        async with aiohttp.ClientSession() as session:
            # Generate TTS
            data = {
                'text': text,
                'voice': voice,
                'speed': speed
            }
            
            async with session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.logger.error(f"Kokoro TTS failed: {response.status} - {error_text}")
                    return None
                
                result = await response.json()
                file_id = result.get('file_id')
                
                if not file_id:
                    self.logger.error("No file_id in Kokoro response")
                    return None
                
                self.logger.info(f"Kokoro TTS generated: file_id={file_id}")
                
                # Download audio file
                return await self._download_file(file_id, output_path)
    
    async def _synthesize_chatterbox(self, text: str, output_path: Path, **kwargs) -> Optional[Path]:
        """Synthesize using Chatterbox TTS (как в n8n)."""
        url = f"{self.base_url}/api/v1/media/audio-tools/tts/chatterbox"
        
        self.logger.info(f"Generating TTS with Chatterbox")
        
        # Get parameters from kwargs
        clone_voice_id = kwargs.get('chatterbox_clone_voice_id')
        exaggeration = kwargs.get('chatterbox_exaggeration', 1.0)
        cfg_weight = kwargs.get('chatterbox_cfg_weight', 1.0)
        temperature = kwargs.get('chatterbox_temperature', 1.0)
        
        async with aiohttp.ClientSession() as session:
            # Generate TTS
            data = {
                'text': text,
                'exaggeration': exaggeration,
                'cfg_weight': cfg_weight,
                'temperature': temperature
            }
            
            if clone_voice_id:
                data['sample_audio_id'] = clone_voice_id
            
            async with session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.logger.error(f"Chatterbox TTS failed: {response.status} - {error_text}")
                    return None
                
                result = await response.json()
                file_id = result.get('file_id')
                
                if not file_id:
                    self.logger.error("No file_id in Chatterbox response")
                    return None
                
                self.logger.info(f"Chatterbox TTS generated: file_id={file_id}")
                
                # Download audio file
                return await self._download_file(file_id, output_path)
    
    async def _download_file(self, file_id: str, output_path: Path) -> Optional[Path]:
        """Download file from local server storage."""
        download_url = f"{self.base_url}/api/v1/media/storage/{file_id}"
        
        self.logger.info(f"Downloading audio: {download_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.logger.error(f"Download failed: {response.status} - {error_text}")
                    return None
                
                # Save to file
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(await response.read())
                
                self.logger.info(f"Audio saved: {output_path}")
                return output_path
    
    async def get_available_voices(self) -> list:
        """Get list of available Kokoro voices."""
        url = f"{self.base_url}/api/v1/media/audio-tools/tts/kokoro/voices"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get('voices', [])
        except Exception as e:
            self.logger.error(f"Failed to get voices: {e}")
        
        return []
