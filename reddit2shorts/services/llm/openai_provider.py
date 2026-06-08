"""OpenAI LLM provider implementation.

This module provides an OpenAI-compatible LLM provider for script generation.
Works with OpenAI API and any OpenAI-compatible APIs (Cerebras, OpenRouter, etc.).

Requirements: 3.1, 3.5
"""

import json
from typing import Optional

# Conditional import - only import if openai library is available
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.services.llm.base import BaseLLMProvider, GeneratedScript
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI LLM provider.
    
    This provider uses the OpenAI API (or compatible APIs) to generate
    video scripts from Reddit stories.
    
    Attributes:
        client: AsyncOpenAI client instance
        api_key: API key for authentication
        model: Model name (e.g., "gpt-4", "gpt-3.5-turbo")
        base_url: Optional custom base URL
    
    Requirements:
        - 3.1: Generate scripts from stories
        - 3.5: Return structured JSON output
    
    Example:
        >>> provider = OpenAIProvider(
        ...     api_key="sk-...",
        ...     model="gpt-4"
        ... )
        >>> script = await provider.generate_script(
        ...     story_title="My Journey",
        ...     story_text="This is my story..."
        ... )
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        base_url: Optional[str] = None
    ):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Model name to use
            base_url: Optional custom base URL for OpenAI-compatible APIs
        
        Raises:
            ImportError: If openai library is not installed
        """
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai library is not installed. "
                "Install it with: pip install openai"
            )
        
        super().__init__(api_key, model, base_url)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
        logger.info(f"OpenAI provider initialized with model: {model}")
    
    async def generate_script(
        self,
        story_title: str,
        story_text: str,
        content_type: str = "motivational speech",
        art_style: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.7
    ) -> GeneratedScript:
        """Generate a video script using OpenAI API.
        
        Args:
            story_title: Title of the Reddit story
            story_text: Full text of the story
            content_type: Type of content (e.g., "motivational speech")
            art_style: Art style for image prompts
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        
        Returns:
            GeneratedScript with segments and timing
        
        Raises:
            RateLimitError: If rate limit is hit
            APIError: If generation fails
        
        Requirements:
            - 3.1: Generate script from story
            - 3.5: Return structured output
        """
        logger.info(f"Generating script with OpenAI model: {self.model}")
        
        prompt = self._build_prompt(story_title, story_text, content_type, art_style)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional video script writer specializing in creating engaging short-form content."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            logger.debug(f"Received response from OpenAI: {len(content)} characters")
            
            script = self._parse_response(content)
            logger.info(f"Successfully generated script with {len(script.segments)} segments")
            
            return script
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check for rate limit errors
            if "rate" in error_msg or "429" in error_msg or "quota" in error_msg:
                logger.warning(f"Rate limit hit for OpenAI: {e}")
                raise RateLimitError(f"OpenAI rate limit: {e}") from e
            
            # Check for authentication errors
            if "401" in error_msg or "unauthorized" in error_msg:
                logger.error(f"Authentication error with OpenAI: {e}")
                raise APIError(f"OpenAI authentication failed: {e}") from e
            
            # Generic API error
            logger.error(f"Error generating script with OpenAI: {e}")
            raise APIError(f"OpenAI API error: {e}") from e
    
    def _build_prompt(
        self,
        story_title: str,
        story_text: str,
        content_type: str,
        art_style: str
    ) -> str:
        """Build the prompt for OpenAI.
        
        Args:
            story_title: Story title
            story_text: Story text
            content_type: Content type
            art_style: Art style description
        
        Returns:
            Formatted prompt string
        """
        prompt = f"""Create a compelling {content_type} video script from this Reddit story.

**Story Title:** {story_title}

**Story Content:**
{story_text}

**Instructions:**
1. Create a 60-90 second video script that captures the essence of this story
2. Break the script into 5-8 scenes, each 8-15 seconds long
3. Make it engaging, emotional, and suitable for short-form video
4. For each scene, provide:
   - The narration text
   - Duration in seconds
   - An image generation prompt that captures the scene visually

**Art Style for Images:**
{art_style if art_style else "Create cinematic, high-quality images with dramatic lighting and composition"}

**Output Format (JSON):**
{{
  "title": "Engaging video title (max 100 characters)",
  "description": "Video description for YouTube (max 500 characters)",
  "scenes": [
    {{
      "text": "Narration text for this scene",
      "duration": 10.0,
      "image_prompt": "Detailed prompt for image generation"
    }}
  ]
}}

Make sure the total duration is between 60-90 seconds. Return ONLY valid JSON, no additional text."""
        
        return prompt


class CerebrasProvider(OpenAIProvider):
    """Cerebras LLM provider (OpenAI-compatible).
    
    Cerebras uses OpenAI-compatible API, so we inherit from OpenAIProvider
    and just customize the initialization.
    
    Example:
        >>> provider = CerebrasProvider(
        ...     api_key="csk-...",
        ...     model="gpt-oss-120b"
        ... )
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-oss-120b",
        base_url: str = "https://api.cerebras.ai/v1"
    ):
        """Initialize Cerebras provider.
        
        Args:
            api_key: Cerebras API key
            model: Model name (default: gpt-oss-120b)
            base_url: Cerebras API base URL
        """
        super().__init__(api_key, model, base_url)
        logger.info(f"Cerebras provider initialized with model: {model}")


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter LLM provider (OpenAI-compatible).
    
    OpenRouter provides access to multiple models through an OpenAI-compatible API.
    
    Example:
        >>> provider = OpenRouterProvider(
        ...     api_key="sk-or-v1-...",
        ...     model="deepseek/deepseek-chat-v3.1:free"
        ... )
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek/deepseek-chat-v3.1:free",
        base_url: str = "https://openrouter.ai/api/v1"
    ):
        """Initialize OpenRouter provider.
        
        Args:
            api_key: OpenRouter API key
            model: Model name (e.g., "deepseek/deepseek-chat-v3.1:free")
            base_url: OpenRouter API base URL
        """
        super().__init__(api_key, model, base_url)
        logger.info(f"OpenRouter provider initialized with model: {model}")


class GroqProvider(OpenAIProvider):
    """Groq LLM provider (OpenAI-compatible).
    
    Groq provides fast inference for open-source models through an OpenAI-compatible API.
    
    Example:
        >>> provider = GroqProvider(
        ...     api_key="gsk_...",
        ...     model="llama-3.1-70b-versatile"
        ... )
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1"
    ):
        """Initialize Groq provider.
        
        Args:
            api_key: Groq API key
            model: Model name (e.g., "llama-3.1-70b-versatile")
            base_url: Groq API base URL
        """
        super().__init__(api_key, model, base_url)
        logger.info(f"Groq provider initialized with model: {model}")
