"""
Configuration management using Pydantic settings.

This module defines all configuration models for the Reddit2Shorts application.
Settings can be loaded from environment variables, .env files, or YAML config files.

Environment variables use double underscore (__) as nested delimiter.
Example: REDDIT__CLIENT_ID=xxx sets reddit.client_id
"""

from typing import List, Optional
from functools import lru_cache
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedditConfig(BaseModel):
    """Reddit API configuration."""
    
    # API mode selection
    use_public_api: bool = Field(
        default=False, 
        description="If True, use public JSON API (как n8n). If False, use PRAW with credentials"
    )
    
    # PRAW credentials (required if use_public_api=False)
    client_id: Optional[str] = Field(default=None, description="Reddit API client ID (required for PRAW)")
    client_secret: Optional[str] = Field(default=None, description="Reddit API client secret (required for PRAW)")
    user_agent: str = Field(default="reddit2shorts/1.0", description="Reddit API user agent")
    
    # Subreddit and fetching parameters
    subreddit: str = Field(default="selfimprovement", description="Target subreddit")
    post_limit: int = Field(default=10, ge=1, le=100, description="Maximum posts to fetch")
    sort: str = Field(default="top", description="Sort method: hot, new, top, rising")
    time_filter: str = Field(default="month", description="Time filter for top sort: hour, day, week, month, year, all")
    
    # Quality filters
    min_score: int = Field(default=100, ge=0, description="Minimum post score")
    min_length: int = Field(default=200, ge=0, description="Minimum text length")
    
    @field_validator('user_agent')
    @classmethod
    def validate_user_agent(cls, v: str) -> str:
        """Validate user agent is not empty."""
        if not v or not v.strip():
            raise ValueError("user_agent cannot be empty")
        return v.strip()
    
    def model_post_init(self, __context) -> None:
        """Validate credentials are provided when using PRAW mode."""
        if not self.use_public_api:
            if not self.client_id or not self.client_secret:
                raise ValueError("client_id and client_secret required when use_public_api=False")


class LLMProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""
    
    name: str = Field(..., description="Provider name (cerebras, openrouter, openai, anthropic, groq)")
    api_keys: List[str] = Field(..., min_length=1, description="List of API keys for rotation")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    model: str = Field(..., description="Model identifier")
    max_tokens: int = Field(default=2000, ge=100, le=100000, description="Maximum tokens in response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    
    @field_validator('api_keys')
    @classmethod
    def validate_api_keys(cls, v: List[str]) -> List[str]:
        """Validate all API keys are non-empty."""
        if not v:
            raise ValueError("At least one API key is required")
        for key in v:
            if not key or not key.strip():
                raise ValueError("API keys cannot be empty")
        return [key.strip() for key in v]
    
    @field_validator('name')
    @classmethod
    def validate_provider_name(cls, v: str) -> str:
        """Validate provider name is supported."""
        valid_providers = {'cerebras', 'openrouter', 'openai', 'anthropic', 'groq', 'gemini'}
        if v.lower() not in valid_providers:
            raise ValueError(f"Provider must be one of: {', '.join(valid_providers)}")
        return v.lower()


class LLMConfig(BaseModel):
    """LLM service configuration."""
    
    providers: List[LLMProviderConfig] = Field(..., min_length=1, description="List of LLM providers")
    max_retries: int = Field(default=15, ge=1, le=50, description="Maximum retry attempts")
    retry_delay: float = Field(default=2.0, ge=0.1, le=60.0, description="Delay between retries in seconds")
    
    @field_validator('providers')
    @classmethod
    def validate_providers(cls, v: List[LLMProviderConfig]) -> List[LLMProviderConfig]:
        """Validate at least one provider is configured."""
        if not v:
            raise ValueError("At least one LLM provider must be configured")
        return v


class ImageConfig(BaseModel):
    """Image generation configuration."""
    
    # Provider selection
    provider: str = Field(default="pollinations", description="Image provider (pollinations, gemini, placeholder)")
    
    # Pollinations.ai settings
    pollinations_api_key: Optional[str] = Field(default=None, description="Pollinations.ai API key")
    pollinations_url: str = Field(default="https://gen.pollinations.ai/image", description="Pollinations.ai API endpoint")
    
    # Gemini settings (optional, for backward compatibility)
    gemini_api_keys: Optional[List[str]] = Field(default=None, description="List of Gemini API keys")
    gemini_model: Optional[str] = Field(default=None, description="Gemini model identifier")
    
    # Common settings
    model: str = Field(default="flux", description="Model identifier (flux, zimage, kontext, nanobanana, etc.)")
    size: str = Field(default="1024x1024", description="Image size (WxH)")
    quality: str = Field(default="standard", description="Image quality (standard, hd)")
    max_retries: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    placeholder_image_path: Optional[str] = Field(default=None, description="Path to placeholder image")
    
    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate image provider."""
        valid_providers = {'pollinations', 'gemini', 'placeholder'}
        if v.lower() not in valid_providers:
            raise ValueError(f"Provider must be one of: {', '.join(valid_providers)}")
        return v.lower()
    
    @field_validator('size')
    @classmethod
    def validate_size(cls, v: str) -> str:
        """Validate image size format."""
        if 'x' not in v.lower():
            raise ValueError("Size must be in format WIDTHxHEIGHT (e.g., 1024x1024)")
        parts = v.lower().split('x')
        if len(parts) != 2:
            raise ValueError("Size must be in format WIDTHxHEIGHT (e.g., 1024x1024)")
        try:
            width, height = int(parts[0]), int(parts[1])
            if width <= 0 or height <= 0:
                raise ValueError("Width and height must be positive")
        except ValueError as e:
            raise ValueError(f"Invalid size format: {e}")
        return v
    
    @field_validator('quality')
    @classmethod
    def validate_quality(cls, v: str) -> str:
        """Validate quality setting."""
        valid_qualities = {'standard', 'hd'}
        if v.lower() not in valid_qualities:
            raise ValueError(f"Quality must be one of: {', '.join(valid_qualities)}")
        return v.lower()
    
    def model_post_init(self, __context) -> None:
        """Validate provider-specific configuration after initialization."""
        if self.provider == 'pollinations' and not self.pollinations_api_key:
            raise ValueError("pollinations_api_key is required when provider is 'pollinations'")
        if self.provider == 'gemini' and not self.gemini_api_keys:
            raise ValueError("gemini_api_keys is required when provider is 'gemini'")


class TTSConfig(BaseModel):
    """Text-to-speech configuration."""
    
    provider: str = Field(default="local", description="TTS provider (local, kokoro, chatterbox, pollinations)")
    
    # Local server settings (как в n8n)
    local_url: Optional[str] = Field(default=None, description="Local AI Agents No-Code Tools server URL")
    tts_engine: str = Field(default="kokoro", description="TTS engine for local server (kokoro, chatterbox)")
    
    # Kokoro settings
    kokoro_api_key: Optional[str] = Field(default=None, description="Kokoro TTS API key")
    kokoro_api_url: Optional[str] = Field(default=None, description="Kokoro TTS API URL")
    kokoro_voice: str = Field(default="af", description="Kokoro voice (default: af = American Female)")
    kokoro_speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Kokoro speed")
    
    # Chatterbox settings
    chatterbox_api_key: Optional[str] = Field(default=None, description="Chatterbox TTS API key")
    chatterbox_api_url: Optional[str] = Field(default=None, description="Chatterbox TTS API URL")
    chatterbox_clone_voice_id: Optional[str] = Field(default=None, description="Chatterbox voice sample ID")
    chatterbox_exaggeration: float = Field(default=1.0, description="Chatterbox exaggeration")
    chatterbox_cfg_weight: float = Field(default=1.0, description="Chatterbox CFG weight")
    chatterbox_temperature: float = Field(default=1.0, description="Chatterbox temperature")
    
    # Pollinations settings
    pollinations_api_keys: Optional[List[str]] = Field(default=None, description="List of Pollinations API keys for rotation")
    pollinations_voice: str = Field(default="rachel", description="Pollinations voice (rachel, bella, adam, etc.)")
    pollinations_speed: float = Field(default=1.0, ge=0.25, le=4.0, description="Pollinations speed (0.25-4.0)")
    pollinations_model: str = Field(default="tts-1", description="Pollinations TTS model (tts-1, elevenlabs)")
    pollinations_response_format: str = Field(default="mp3", description="Audio format (mp3, opus, aac, flac, wav, pcm)")
    
    voice: str = Field(default="default", description="Voice identifier")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    
    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate TTS provider."""
        valid_providers = {'local', 'kokoro', 'chatterbox', 'pollinations'}
        if v.lower() not in valid_providers:
            raise ValueError(f"TTS provider must be one of: {', '.join(valid_providers)}")
        return v.lower()
    
    def model_post_init(self, __context) -> None:
        """Validate provider-specific configuration after initialization."""
        if self.provider == 'local' and not self.local_url:
            raise ValueError("local_url is required when provider is 'local'")
        # Kokoro ONNX не требует API ключей - это Python библиотека
        # if self.provider == 'kokoro' and not self.kokoro_api_key:
        #     raise ValueError("kokoro_api_key is required when provider is 'kokoro'")
        if self.provider == 'chatterbox' and not self.chatterbox_api_key:
            raise ValueError("chatterbox_api_key is required when provider is 'chatterbox'")
        # Pollinations ключи могут быть в tts секции или в общей pollinations секции
        # Валидация происходит в TTSService при инициализации
        # if self.provider == 'pollinations' and not self.pollinations_api_keys:
        #     raise ValueError("pollinations_api_keys is required when provider is 'pollinations'")


class VideoConfig(BaseModel):
    """Video creation configuration."""
    
    provider: str = Field(default="moviepy", description="Video provider (moviepy, local, api)")
    
    # Local server settings (для local provider)
    local_url: Optional[str] = Field(default=None, description="Local AI Agents No-Code Tools server URL")
    
    # API settings (для api provider)
    api_url: Optional[str] = Field(default=None, description="Video creation API URL")
    api_key: Optional[str] = Field(default=None, description="Video creation API key")
    
    subtitle_font: str = Field(default="Arial", description="Subtitle font family")
    subtitle_size: int = Field(default=48, ge=12, le=200, description="Subtitle font size")
    subtitle_color: str = Field(default="#FFFFFF", description="Subtitle color (hex format)")
    background_music_volume: float = Field(
        default=0.2, 
        ge=0.0, 
        le=1.0, 
        description="Background music volume (0.0-1.0)"
    )
    polling_interval: int = Field(
        default=10, 
        ge=1, 
        le=60, 
        description="Status polling interval in seconds"
    )
    timeout: int = Field(
        default=600, 
        ge=60, 
        le=3600, 
        description="Video creation timeout in seconds"
    )
    
    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate video provider."""
        valid_providers = {'moviepy', 'local', 'api'}
        if v.lower() not in valid_providers:
            raise ValueError(f"Video provider must be one of: {', '.join(valid_providers)}")
        return v.lower()
    
    @field_validator('subtitle_color')
    @classmethod
    def validate_color(cls, v: str) -> str:
        """Validate hex color format."""
        if not v.startswith('#'):
            raise ValueError("Color must start with # (hex format)")
        hex_part = v[1:]
        if len(hex_part) not in (3, 6):
            raise ValueError("Color must be in format #RGB or #RRGGBB")
        try:
            int(hex_part, 16)
        except ValueError:
            raise ValueError("Invalid hex color format")
        return v.upper()
    
    def model_post_init(self, __context) -> None:
        """Validate provider-specific configuration after initialization."""
        if self.provider == 'local' and not self.local_url:
            raise ValueError("local_url is required when provider is 'local'")
        if self.provider == 'api' and (not self.api_url or not self.api_key):
            raise ValueError("api_url and api_key are required when provider is 'api'")


class YouTubeConfig(BaseModel):
    """YouTube upload configuration."""
    
    client_secrets_file: str = Field(..., description="Path to OAuth2 client secrets JSON file")
    token_file: str = Field(
        default="credentials/youtube_token.pkl", 
        description="Path to store OAuth2 token (should be flow-specific in config)"
    )
    default_privacy: str = Field(
        default="unlisted", 
        description="Default video privacy (public, unlisted, private)"
    )
    default_category: str = Field(
        default="24", 
        description="Default YouTube category ID (22 = People & Blogs)"
    )
    proxy: Optional[str] = Field(
        default=None,
        description="Proxy URL for YouTube API access (e.g., 'http://user:pass@host:port' or 'socks5://host:port')"
    )
    scheduled_publishing: Optional[dict] = Field(
        default=None,
        description="Scheduled publishing configuration for daily batch mode"
    )
    
    @field_validator('default_privacy')
    @classmethod
    def validate_privacy(cls, v: str) -> str:
        """Validate privacy setting."""
        valid_privacy = {'public', 'unlisted', 'private'}
        if v.lower() not in valid_privacy:
            raise ValueError(f"Privacy must be one of: {', '.join(valid_privacy)}")
        return v.lower()
    
    @field_validator('proxy')
    @classmethod
    def validate_proxy(cls, v: Optional[str]) -> Optional[str]:
        """Validate proxy URL format."""
        if v is None:
            return v
        
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(v)
            if not parsed.scheme:
                raise ValueError("Proxy URL must include scheme (http://, https://, or socks5://)")
            if parsed.scheme not in ('http', 'https', 'socks5'):
                raise ValueError("Proxy scheme must be http, https, or socks5")
            if not parsed.hostname:
                raise ValueError("Proxy URL must include hostname")
            return v
        except Exception as e:
            raise ValueError(f"Invalid proxy URL format: {e}")


class GoogleSheetsConfig(BaseModel):
    """Google Sheets configuration."""
    
    credentials_file: str = Field(..., description="Path to service account credentials JSON file")
    spreadsheet_id: str = Field(..., description="Google Sheets spreadsheet ID")
    worksheet_name: str = Field(default="Stories", description="Worksheet name")
    
    @field_validator('spreadsheet_id')
    @classmethod
    def validate_spreadsheet_id(cls, v: str) -> str:
        """Validate spreadsheet ID is not empty."""
        if not v or not v.strip():
            raise ValueError("spreadsheet_id cannot be empty")
        return v.strip()


class Settings(BaseSettings):
    """Main application settings.
    
    Settings are loaded from:
    1. Environment variables (highest priority)
    2. .env file
    3. Default values (lowest priority)
    
    Nested settings use double underscore (__) as delimiter in environment variables.
    Example: REDDIT__CLIENT_ID=xxx sets reddit.client_id
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Service configurations
    reddit: RedditConfig
    llm: Optional[LLMConfig] = None  # Опционально, может быть создан из gemini секции
    image: ImageConfig
    tts: TTSConfig
    video: VideoConfig
    youtube: YouTubeConfig
    google_sheets: GoogleSheetsConfig
    
    # Application settings
    log_level: str = Field(
        default="INFO", 
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    log_file: str = Field(
        default="reddit2shorts.log", 
        description="Log file path"
    )
    output_dir: str = Field(
        default="./output", 
        description="Output directory for final videos"
    )
    temp_dir: str = Field(
        default="./temp", 
        description="Temporary directory for intermediate files"
    )
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v_upper


def load_settings() -> Settings:
    """Load settings from YAML config file, environment variables and .env file.
    
    Priority (highest to lowest):
    1. Environment variables
    2. .env file
    3. config.yaml file
    
    Returns:
        Settings: Validated application settings
        
    Raises:
        ValidationError: If configuration is invalid
    """
    import yaml
    from pathlib import Path
    
    # Load YAML config if exists
    config_path = Path("config.yaml")
    yaml_config = {}
    if config_path.exists():
        with open(config_path, encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f) or {}
    
    # ВАЖНО: Подставляем ключи из общей секции pollinations в tts, если их там нет
    if 'pollinations' in yaml_config and 'tts' in yaml_config:
        tts_config = yaml_config['tts']
        pollinations_config = yaml_config['pollinations']
        
        print(f"DEBUG load_settings: tts_config keys = {list(tts_config.keys())}")
        print(f"DEBUG load_settings: pollinations_voice = {tts_config.get('pollinations_voice')}")
        
        # Если TTS использует pollinations, но нет ключей - берем из общей секции
        if tts_config.get('provider') == 'pollinations':
            if not tts_config.get('pollinations_api_keys') and pollinations_config.get('api_keys'):
                tts_config['pollinations_api_keys'] = pollinations_config['api_keys']
    
    # ВАЖНО: Создаем llm секцию из gemini если её нет
    if 'llm' not in yaml_config and 'gemini' in yaml_config:
        gemini_config = yaml_config['gemini']
        yaml_config['llm'] = {
            "max_retries": 15,
            "providers": [{
                "name": "gemini",
                "enabled": True,
                "api_keys": gemini_config.get("api_keys", []),
                "model": gemini_config.get("model", "gemini-2.5-flash"),
                "temperature": gemini_config.get("temperature", 0.7),
                "max_tokens": gemini_config.get("max_tokens", 8000)
            }]
        }
    
    # Create Settings with YAML config as base
    # Environment variables and .env will override YAML values
    return Settings(**yaml_config)
