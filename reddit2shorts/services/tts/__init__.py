"""TTS (Text-to-Speech) service package.

This package provides TTS capabilities through multiple providers:
- Kokoro TTS
- Chatterbox TTS

Supports voice cloning, speed adjustment, and other TTS parameters.
"""

from reddit2shorts.services.tts.base import BaseTTSProvider
from reddit2shorts.services.tts.service import TTSService

__all__ = [
    'BaseTTSProvider',
    'TTSService',
]
