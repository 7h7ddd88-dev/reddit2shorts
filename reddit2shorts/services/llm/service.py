"""LLM Service orchestrator with provider rotation.

This module provides the main LLM service that manages multiple providers
with automatic failover and API key rotation.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

import asyncio
from typing import Any, Dict, Optional, TYPE_CHECKING

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.services.llm.base import BaseLLMProvider, GeneratedScript
from reddit2shorts.services.llm.gemini_provider import GeminiProvider
from reddit2shorts.utils.api_rotator import APIKeyRotator
from reddit2shorts.utils.logger import get_logger

# Lazy import для OpenAI провайдеров (только если используются)
if TYPE_CHECKING:
    from reddit2shorts.services.llm.openai_provider import (
        CerebrasProvider,
        GroqProvider,
        OpenAIProvider,
        OpenRouterProvider,
    )

logger = get_logger(__name__)


class LLMService:
    """LLM service with automatic provider rotation.
    
    This service manages multiple LLM providers and automatically rotates
    between them when rate limits are hit or errors occur.
    
    Attributes:
        rotator: APIKeyRotator for managing provider keys
        config: Configuration dictionary
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        content_type: Type of content to generate
        art_style: Art style for image prompts
    
    Requirements:
        - 3.1: Generate scripts from stories
        - 3.2: Rotate keys on rate limit
        - 3.3: Switch providers when keys exhausted
        - 3.4: Retry up to max_retries times
    
    Example:
        >>> config = {
        ...     "providers": [
        ...         {
        ...             "name": "cerebras",
        ...             "api_keys": ["key1", "key2"],
        ...             "model": "gpt-oss-120b",
        ...             "base_url": "https://api.cerebras.ai/v1"
        ...         }
        ...     ],
        ...     "max_retries": 15,
        ...     "retry_delay": 2.0
        ... }
        >>> service = LLMService(config)
        >>> script = await service.generate_script("Title", "Story text")
    """
    
    @staticmethod
    def _get_provider_class(provider_name: str):
        """Get provider class with lazy import.
        
        Args:
            provider_name: Name of provider (cerebras, openrouter, openai, groq, gemini)
            
        Returns:
            Provider class
        """
        if provider_name == "gemini":
            return GeminiProvider
        else:
            # Lazy import для OpenAI-based провайдеров
            from reddit2shorts.services.llm.openai_provider import (
                CerebrasProvider,
                GroqProvider,
                OpenAIProvider,
                OpenRouterProvider,
            )
            
            provider_classes = {
                "cerebras": CerebrasProvider,
                "openrouter": OpenRouterProvider,
                "openai": OpenAIProvider,
                "groq": GroqProvider,
            }
            
            return provider_classes.get(provider_name)
    
    def __init__(
        self,
        config: Dict[str, Any],
        content_type: str = "motivational speech",
        art_style: str = ""
    ):
        """Initialize LLM service.
        
        Args:
            config: Configuration dictionary with providers and settings
            content_type: Type of content to generate
            art_style: Art style description for images
        """
        self.config = config
        self.max_retries = config.get("max_retries", 15)
        self.retry_delay = config.get("retry_delay", 5.0)
        self.content_type = content_type
        self.art_style = art_style
        
        # Initialize API key rotator
        providers_config = []
        for provider in config.get("providers", []):
            if provider.get("enabled", True):
                providers_config.append({
                    "name": provider["name"],
                    "api_keys": provider["api_keys"]
                })
        
        self.rotator = APIKeyRotator(providers_config)
        logger.info(
            f"LLM service initialized with {len(providers_config)} providers, "
            f"max_retries={self.max_retries}"
        )
    
    async def generate_script(
        self,
        story_title: str,
        story_text: str,
        max_tokens: int = 2000,
        temperature: float = 0.7
    ) -> GeneratedScript:
        """Generate a video script with automatic provider rotation.
        
        This method attempts to generate a script using available providers,
        automatically rotating keys and switching providers on failures.
        
        Args:
            story_title: Title of the Reddit story
            story_text: Full text of the story
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        
        Returns:
            GeneratedScript with segments and timing
        
        Raises:
            APIError: If all providers and keys are exhausted
        
        Requirements:
            - 3.1: Generate script from story
            - 3.2: Rotate keys on rate limit
            - 3.3: Switch providers when exhausted
            - 3.4: Retry up to max_retries times
        
        Example:
            >>> service = LLMService(config)
            >>> script = await service.generate_script(
            ...     story_title="My Journey",
            ...     story_text="This is my story..."
            ... )
            >>> print(f"Generated {len(script.segments)} segments")
        """
        logger.info(f"Starting script generation for story: {story_title}")
        
        attempts = 0
        last_error = None
        
        while attempts < self.max_retries:
            # Get next available key
            key_info = self.rotator.get_next_key()
            if not key_info:
                logger.error("No available API keys")
                raise APIError(
                    f"All API keys exhausted after {attempts} attempts. "
                    f"Last error: {last_error}"
                )
            
            provider_name, api_key = key_info
            attempts += 1
            
            logger.info(
                f"Attempt {attempts}/{self.max_retries}: Using provider {provider_name}"
            )
            
            try:
                # Create provider instance
                provider = self._create_provider(provider_name, api_key)
                
                # Generate script
                script = await provider.generate_script(
                    story_title=story_title,
                    story_text=story_text,
                    content_type=self.content_type,
                    art_style=self.art_style,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                logger.info(
                    f"✅ Script generated successfully with {provider_name} "
                    f"(attempt {attempts})"
                )
                return script
                
            except RateLimitError as e:
                logger.warning(
                    f"⚠️ Rate limit hit for {provider_name}: {e}"
                )
                self.rotator.handle_rate_limit(provider_name, api_key)
                last_error = e
                
            except APIError as e:
                logger.error(
                    f"❌ API error with {provider_name}: {e}"
                )
                self.rotator.handle_error(provider_name, api_key)
                last_error = e
                
            except Exception as e:
                logger.error(
                    f"❌ Unexpected error with {provider_name}: {e}"
                )
                self.rotator.handle_error(provider_name, api_key)
                last_error = e
            
            # Wait before retry
            if attempts < self.max_retries:
                logger.debug(f"Waiting {self.retry_delay}s before retry...")
                await asyncio.sleep(self.retry_delay)
        
        # All retries exhausted
        logger.error(
            f"Failed to generate script after {self.max_retries} attempts"
        )
        raise APIError(
            f"Failed to generate script after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        )
    
    async def generate_with_schema(
        self,
        prompt: str,
        schema: dict,
        max_tokens: int = None,
        temperature: float = 0.7
    ) -> dict:
        """
        Generate content with structured output using automatic provider rotation.
        
        This is a simplified method that accepts any prompt and schema,
        with automatic failover between providers.
        
        Args:
            prompt: The prompt text to send to LLM
            schema: JSON schema for structured output
            max_tokens: Maximum tokens to generate (if None, uses provider config)
            temperature: Sampling temperature
            
        Returns:
            Parsed JSON response from LLM
            
        Raises:
            APIError: If all providers and keys are exhausted
        """
        logger.info(f"Starting content generation with schema")
        
        attempts = 0
        last_error = None
        
        while attempts < self.max_retries:
            # Get next available key
            key_info = self.rotator.get_next_key()
            if not key_info:
                logger.error("No available API keys")
                raise APIError(
                    f"All API keys exhausted after {attempts} attempts. "
                    f"Last error: {last_error}"
                )
            
            provider_name, api_key = key_info
            attempts += 1
            
            logger.info(
                f"Attempt {attempts}/{self.max_retries}: Using provider {provider_name}"
            )
            
            try:
                # Create provider instance
                provider = self._create_provider(provider_name, api_key)
                
                # Check if provider supports generate_with_schema
                if not hasattr(provider, 'generate_with_schema'):
                    raise APIError(
                        f"Provider {provider_name} does not support generate_with_schema"
                    )
                
                # Get max_tokens from provider config if not specified
                if max_tokens is None:
                    provider_config = next(
                        (p for p in self.config.get("providers", []) if p["name"] == provider_name),
                        {}
                    )
                    max_tokens = provider_config.get("max_tokens", 4000)
                
                # Generate content
                result = await provider.generate_with_schema(
                    prompt=prompt,
                    schema=schema,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                logger.info(
                    f"✅ Content generated successfully with {provider_name} "
                    f"(attempt {attempts})"
                )
                return result
                
            except RateLimitError as e:
                logger.warning(
                    f"⚠️ Rate limit hit for {provider_name}: {e}"
                )
                self.rotator.handle_rate_limit(provider_name, api_key)
                last_error = e
                
            except APIError as e:
                logger.error(
                    f"❌ API error with {provider_name}: {e}"
                )
                self.rotator.handle_error(provider_name, api_key)
                last_error = e
                
            except Exception as e:
                logger.error(
                    f"❌ Unexpected error with {provider_name}: {e}"
                )
                self.rotator.handle_error(provider_name, api_key)
                last_error = e
            
            # Wait before retry
            if attempts < self.max_retries:
                logger.debug(f"Waiting {self.retry_delay}s before retry...")
                await asyncio.sleep(self.retry_delay)
        
        # All retries exhausted
        logger.error(
            f"Failed to generate content after {self.max_retries} attempts"
        )
        raise APIError(
            f"Failed to generate content after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        )
    
    def _create_provider(
        self,
        provider_name: str,
        api_key: str
    ) -> BaseLLMProvider:
        """Create a provider instance.
        
        Args:
            provider_name: Name of the provider (e.g., "openai", "anthropic")
            api_key: API key for the provider
        
        Returns:
            BaseLLMProvider instance
        
        Raises:
            ValueError: If provider name is not recognized
        """
        # Find provider config
        provider_config = None
        for config in self.config.get("providers", []):
            if config["name"] == provider_name:
                provider_config = config
                break
        
        if not provider_config:
            raise ValueError(f"Provider config not found: {provider_name}")
        
        # Get provider class (lazy import)
        provider_class = self._get_provider_class(provider_name)
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider_name}")
        
        # Create provider instance
        model = provider_config.get("model")
        base_url = provider_config.get("base_url")
        proxy = provider_config.get("proxy")  # Get proxy from provider config
        
        # Gemini provider supports proxy parameter
        if provider_name == "gemini":
            if base_url:
                provider = provider_class(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    proxy=proxy
                )
            else:
                provider = provider_class(
                    api_key=api_key,
                    model=model,
                    proxy=proxy
                )
        else:
            # Other providers (OpenAI-based) don't support proxy yet
            if base_url:
                provider = provider_class(
                    api_key=api_key,
                    model=model,
                    base_url=base_url
                )
            else:
                provider = provider_class(
                    api_key=api_key,
                    model=model
                )
        
        logger.debug(
            f"Created {provider_name} provider with model {model}"
        )
        return provider
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all providers and keys.
        
        Returns:
            Dictionary with provider status information
        
        Example:
            >>> service = LLMService(config)
            >>> status = service.get_status()
            >>> print(status)
            {
                'cerebras': {
                    'total_keys': 4,
                    'active_keys': 3,
                    'rate_limited': 1,
                    'error_keys': 0
                },
                ...
            }
        """
        return self.rotator.get_status()
    
    def reset_keys(self):
        """Reset all keys to active status.
        
        This can be useful for testing or after a cooldown period.
        """
        for pool in self.rotator.pools.values():
            for key in pool.keys:
                from reddit2shorts.utils.api_rotator import KeyStatus
                key.status = KeyStatus.ACTIVE
                key.cooldown_until = None
                key.error_count = 0
        
        logger.info("All API keys reset to active status")
