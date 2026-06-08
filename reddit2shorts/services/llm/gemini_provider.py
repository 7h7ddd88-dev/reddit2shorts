"""
Gemini LLM Provider - Simplified HTTP Transport

Pure HTTP transport for Gemini API with no flow-specific logic.
Uses Google Gemini API for generating content with structured output.
"""

import asyncio
import aiohttp
import json
from typing import Optional

from reddit2shorts.services.llm.base import BaseLLMProvider, GeneratedScript, ScriptSegment
from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class GeminiProvider(BaseLLMProvider):
    """
    Gemini API provider for LLM operations.
    
    Simplified HTTP transport with no flow-specific logic.
    Uses Google Gemini models (gemini-2.5-flash, gemini-2.5-pro, etc.)
    for generating content via direct HTTP API.
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: Optional[str] = None,
        proxy: Optional[str] = None
    ):
        """
        Initialize Gemini provider.
        
        Args:
            api_key: Gemini API key
            model: Model name (e.g., "gemini-2.5-flash", "gemini-2.5-pro")
            base_url: Base URL (default: https://generativelanguage.googleapis.com/v1beta)
            proxy: Proxy URL (e.g., "http://user:pass@host:port") or None
        """
        super().__init__(api_key, model, base_url)
        
        # Set base URL
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        
        # Construct API endpoint
        self.api_url = f"{self.base_url}/models/{model}:generateContent"
        
        # Proxy configuration
        self.proxy = proxy
        if self.proxy:
            from reddit2shorts.utils.proxy import mask_proxy_url
            logger.info(f"Gemini proxy configured: {mask_proxy_url(self.proxy)}")
        
        logger.debug(f"Gemini provider initialized with model: {model}")
    
    async def generate_with_schema(
        self,
        prompt: str,
        schema: dict,
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> dict:
        """
        Generate content using Gemini API with structured output.
        
        This is a simplified, generic method that accepts any prompt and schema.
        No flow-specific logic - pure HTTP transport.
        
        Args:
            prompt: The prompt text to send to Gemini
            schema: JSON schema for structured output
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            
        Returns:
            Parsed JSON response from Gemini
            
        Raises:
            RateLimitError: If rate limit is hit
            APIError: If API call fails
        """
        try:
            # Prepare request payload with structured output
            payload = {
                "contents": [{
                    "parts": [{
                        "text": prompt
                    }]
                }],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "topP": 0.95,
                    "topK": 40,
                    "responseMimeType": "application/json",
                    "responseSchema": schema
                }
            }
            
            # Make API request with proxy support
            from reddit2shorts.utils.proxy import create_aiohttp_connector
            from urllib.parse import urlparse
            import aiohttp
            
            connector = create_aiohttp_connector(self.proxy)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # For HTTP/HTTPS proxies, pass proxy parameter to request
                request_kwargs = {
                    "json": payload,
                    "headers": {"Content-Type": "application/json"}
                }
                
                if self.proxy and not connector:  # HTTP/HTTPS proxy (not SOCKS5)
                    # Parse proxy URL to extract auth
                    parsed = urlparse(self.proxy)
                    
                    # Add proxy URL
                    request_kwargs["proxy"] = self.proxy
                    
                    # Add proxy authentication if present
                    if parsed.username and parsed.password:
                        request_kwargs["proxy_auth"] = aiohttp.BasicAuth(
                            parsed.username,
                            parsed.password
                        )
                
                async with session.post(
                    f"{self.api_url}?key={self.api_key}",
                    **request_kwargs
                ) as response:
                    
                    # Check status code
                    if response.status == 429:
                        error_text = await response.text()
                        logger.error(f"Gemini rate limit (20 req/day): ...{self.api_key[-8:]}")
                        raise RateLimitError(f"Gemini rate limit exceeded")
                    
                    if response.status == 400:
                        error_text = await response.text()
                        try:
                            error_data = json.loads(error_text)
                            error_msg = error_data.get("error", {}).get("message", error_text)
                        except:
                            error_msg = error_text
                        logger.error(f"Gemini 400: {error_msg}")
                        raise APIError(f"Gemini bad request: {error_msg}")
                    
                    if response.status == 403:
                        error_text = await response.text()
                        logger.error(f"Gemini 403: API key invalid or revoked (...{self.api_key[-8:]})")
                        raise APIError(f"Gemini forbidden: Check API key")
                    
                    if response.status == 503:
                        error_text = await response.text()
                        logger.warning(f"Gemini 503: Model overloaded (temporary)")
                        raise RateLimitError(f"Gemini overloaded: 503")
                    
                    if response.status == 500:
                        error_text = await response.text()
                        logger.error(f"Gemini 500: Server error (temporary)")
                        raise RateLimitError(f"Gemini server error")
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"Gemini {response.status}: {error_text[:200]}")
                        raise APIError(f"Gemini error {response.status}")
                    
                    # Parse response
                    data = await response.json()
            
            # Extract text from response
            if not data.get("candidates"):
                logger.error(f"Gemini: No candidates (content filtered or invalid request)")
                raise APIError("No candidates in Gemini response")
            
            candidate = data["candidates"][0]
            
            # Check for content filtering
            finish_reason = candidate.get("finishReason", "")
            if finish_reason in ["SAFETY", "RECITATION", "OTHER"]:
                logger.error(f"Gemini: Content filtered ({finish_reason})")
                raise APIError(f"Content filtered: {finish_reason}")
            
            if not candidate.get("content"):
                logger.error(f"Gemini: No content in response")
                raise APIError("No content in Gemini response")
            
            parts = candidate["content"].get("parts", [])
            if not parts:
                logger.error(f"Gemini: No parts in response")
                raise APIError("No parts in Gemini response")
            
            response_text = parts[0].get("text", "")
            if not response_text:
                logger.error(f"Gemini: Empty text in response")
                raise APIError("Empty text in Gemini response")
            
            # Parse JSON response
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.error(f"Gemini: Invalid JSON - {e}")
                logger.error(f"Response: {response_text[:300]}")
                raise APIError(f"Invalid JSON from Gemini: {e}")
            
            logger.info(f"Generated content successfully with Gemini")
            return result
            
        except RateLimitError:
            raise
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise APIError(f"Gemini error: {e}")
    
    async def generate_script(
        self,
        story_title: str,
        story_text: str,
        content_type: str = "motivational story",
        art_style: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.7
    ) -> GeneratedScript:
        """
        DEPRECATED: Use generate_with_schema() instead.
        
        This method is kept for backward compatibility but should not be used.
        All orchestrators should call their own _get_script_schema() and 
        _create_script_prompt() methods, then use generate_with_schema().
        
        Args:
            story_title: Title/theme for the story
            story_text: Prompt or context for story generation
            content_type: Type of content
            art_style: Art style for image prompts
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            GeneratedScript with segments
            
        Raises:
            NotImplementedError: Always - this method is deprecated
        """
        raise NotImplementedError(
            "generate_script() is deprecated. "
            "Use generate_with_schema() instead. "
            "Each orchestrator should define its own _get_script_schema() and "
            "_create_script_prompt() methods."
        )
    
    def _build_prompt(
        self,
        story_title: str,
        story_text: str,
        content_type: str,
        art_style: str
    ) -> str:
        """
        DEPRECATED: Use orchestrator's _create_script_prompt() instead.
        
        This method is kept for backward compatibility but should not be used.
        
        Raises:
            NotImplementedError: Always - this method is deprecated
        """
        raise NotImplementedError(
            "_build_prompt() is deprecated. "
            "Each orchestrator should define its own _create_script_prompt() method."
        )
