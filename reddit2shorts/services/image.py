"""Image generation service using Pollinations.ai API.

This module provides image generation capabilities using Pollinations.ai API
with automatic fallback to placeholder images and rate limit tracking.

Requirements: 4.1, 4.3, 4.4, 4.5
"""

import asyncio
import io
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from reddit2shorts.core.exceptions import APIError, RateLimitError
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class PollinationsKeyStatus(Enum):
    """Status of a Pollinations API key"""
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    PAYMENT_REQUIRED = "payment_required"  # 402 error
    ERROR = "error"


@dataclass
class PollinationsKey:
    """Represents a Pollinations API key with status tracking"""
    key: str
    status: PollinationsKeyStatus = PollinationsKeyStatus.ACTIVE
    last_used: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    error_count: int = 0
    
    def is_available(self) -> bool:
        """Check if key is available for use"""
        if self.status == PollinationsKeyStatus.ACTIVE:
            return True
        elif self.status in [PollinationsKeyStatus.RATE_LIMITED, PollinationsKeyStatus.PAYMENT_REQUIRED]:
            if self.cooldown_until and datetime.now() > self.cooldown_until:
                self.status = PollinationsKeyStatus.ACTIVE
                logger.info(f"Pollinations key cooldown expired, reactivating")
                return True
        return False


class ImageGenerator:
    """Image generator using Pollinations.ai API.
    
    This service generates images from text prompts using Pollinations.ai API.
    Includes placeholder fallback on failure and rate limit tracking.
    
    Attributes:
        pollinations_url: Pollinations API endpoint
        pollinations_api_key: API key for Pollinations
        model: Model name (flux, kontext, nanobanana, etc.)
        size: Image size (e.g., "1024x1024")
        max_retries: Maximum retry attempts
        _rate_limited_keys: Dict tracking rate limited keys with cooldown times
    
    Requirements:
        - 4.1: Generate images from prompts
        - 4.3: Save images locally
        - 4.4: Use placeholder on failure
        - 4.5: Support generation parameters
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize image generator.
        
        Args:
            config: Configuration dictionary with Pollinations settings
        """
        # DEBUG: Print config
        logger.info(f"ImageGenerator config: {config}")
        
        self.pollinations_url = config.get("pollinations_url", "https://gen.pollinations.ai/image")
        
        # Используем общие ключи из секции pollinations (с ротацией)
        pollinations_config = config.get("pollinations", {})
        api_keys = pollinations_config.get("api_keys", [])
        
        # Initialize keys with status tracking
        self.keys: List[PollinationsKey] = [
            PollinationsKey(key=key) for key in api_keys
        ]
        self.current_key_index = 0
        
        # Модель для изображений - берем из image config или из pollinations.default_image_model
        self.model = config.get("model", pollinations_config.get("default_image_model", "gptimage"))
        self.size = config.get("size", "1024x1024")
        self.max_retries = config.get("max_retries", 3)
        
        # Proxy configuration
        self.proxy = config.get("proxy", None)
        if self.proxy:
            from reddit2shorts.utils.proxy import mask_proxy_url
            logger.info(f"Pollinations Image proxy configured: {mask_proxy_url(self.proxy)}")
        
        logger.info(
            f"Image generator initialized with Pollinations.ai, "
            f"model: {self.model}, size: {self.size}, keys: {len(self.keys)}"
        )
    
    def _get_next_available_key(self) -> Optional[int]:
        """Get next available (not rate limited) key index.
        
        Returns:
            Key index if available, None if all keys are rate limited
        """
        # Try all keys starting from current index
        for i in range(len(self.keys)):
            key_index = (self.current_key_index + i) % len(self.keys)
            key = self.keys[key_index]
            
            if key.is_available():
                return key_index
        
        # All keys are rate limited or disabled
        return None
    
    def _mark_key_rate_limited(self, key_index: int, cooldown_minutes: int = 60):
        """Mark a key as rate limited with cooldown.
        
        Args:
            key_index: Index of the key to mark
            cooldown_minutes: Cooldown duration in minutes (60 for 429, 1440 for 402)
        """
        key = self.keys[key_index]
        key.status = PollinationsKeyStatus.RATE_LIMITED
        key.cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
        key.last_used = datetime.now()
        
        logger.warning(
            f"Key {key_index + 1}/{len(self.keys)} marked as rate limited, "
            f"cooldown until {key.cooldown_until.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def _mark_key_payment_required(self, key_index: int):
        """Mark a key as payment required (402 error) with 24 hour cooldown.
        
        Args:
            key_index: Index of the key to mark
        """
        key = self.keys[key_index]
        key.status = PollinationsKeyStatus.PAYMENT_REQUIRED
        key.cooldown_until = datetime.now() + timedelta(hours=24)
        key.last_used = datetime.now()
        
        logger.warning(
            f"Key {key_index + 1}/{len(self.keys)} marked as payment required (402), "
            f"cooldown until {key.cooldown_until.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def _mark_key_error(self, key_index: int):
        """Mark a key as having an error. After 3 errors, permanently disable.
        
        Args:
            key_index: Index of the key to mark
        """
        key = self.keys[key_index]
        key.error_count += 1
        key.last_used = datetime.now()
        
        if key.error_count >= 3:
            key.status = PollinationsKeyStatus.ERROR
            logger.error(
                f"Key {key_index + 1}/{len(self.keys)} permanently disabled after {key.error_count} errors"
            )
        else:
            logger.warning(
                f"Key {key_index + 1}/{len(self.keys)} error count: {key.error_count}/3"
            )
    
    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        retry_count: int = 0
    ) -> Optional[Path]:
        """Generate an image from a text prompt.
        
        Attempts to generate an image using Pollinations.ai API.
        Falls back to placeholder on failure.
        
        Args:
            prompt: Text prompt for image generation
            output_path: Path where to save the generated image
            retry_count: Current retry attempt (internal use)
        
        Returns:
            Path to the saved image, or None on failure
        """
        logger.info(f"Generating image (attempt {retry_count + 1}/{self.max_retries})")
        logger.debug(f"Prompt: {prompt[:100]}...")
        
        if retry_count >= self.max_retries:
            logger.warning(
                f"Max retries ({self.max_retries}) reached, using placeholder"
            )
            return self._create_placeholder(output_path, prompt)
        
        try:
            # Use Pollinations.ai
            image_data = await self._call_pollinations_api(prompt)
            
            # Save image
            image = Image.open(io.BytesIO(image_data))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)
            
            logger.info(f"✅ Image generated and saved to: {output_path}")
            return output_path
            
        except RateLimitError as e:
            logger.warning(f"⚠️ Rate limit hit: {e}")
            await asyncio.sleep(2.0)
            return await self.generate_image(prompt, output_path, retry_count + 1)
            
        except APIError as e:
            logger.error(f"❌ API error: {e}")
            await asyncio.sleep(2.0)
            return await self.generate_image(prompt, output_path, retry_count + 1)
            
        except Exception as e:
            logger.error(f"❌ Unexpected error generating image: {e}")
            await asyncio.sleep(2.0)
            return await self.generate_image(prompt, output_path, retry_count + 1)
    
    async def _call_pollinations_api(self, prompt: str) -> bytes:
        """Call Pollinations.ai API to generate image with key rotation and rate limit tracking.
        
        Args:
            prompt: Text prompt
        
        Returns:
            Image data as bytes
        
        Raises:
            RateLimitError: If all keys are rate limited
            APIError: If API call fails
        """
        # Parse size
        try:
            width, height = map(int, self.size.split('x'))
        except:
            width, height = 1024, 1024
        
        # Pollinations.ai endpoint: /image/{prompt}?key=API_KEY
        import urllib.parse
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"{self.pollinations_url}/{encoded_prompt}"
        
        # Пробуем все доступные ключи
        attempts = 0
        max_attempts = len(self.keys)
        
        while attempts < max_attempts:
            # Получить следующий доступный ключ
            key_index = self._get_next_available_key()
            
            if key_index is None:
                # Все ключи rate limited или disabled
                logger.error("All Pollinations keys are unavailable (rate limited or disabled)")
                raise RateLimitError("All Pollinations keys unavailable, please wait")
            
            key = self.keys[key_index]
            
            try:
                params = {
                    "key": key.key,
                    "width": str(width),
                    "height": str(height),
                    "model": self.model,
                    "nologo": "true"
                }
                
                logger.debug(f"Attempt {attempts + 1}/{max_attempts} with key {key_index + 1}/{len(self.keys)}")
                
                # Create aiohttp session with proxy support
                from reddit2shorts.utils.proxy import create_aiohttp_connector
                
                connector = create_aiohttp_connector(self.proxy)
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    # For HTTP/HTTPS proxies, pass proxy parameter to request
                    request_kwargs = {
                        "params": params,
                        "timeout": aiohttp.ClientTimeout(total=90)
                    }
                    
                    if self.proxy and not connector:  # HTTP/HTTPS proxy (not SOCKS5)
                        request_kwargs["proxy"] = self.proxy
                    
                    async with session.get(url, **request_kwargs) as response:
                        # Handle 402 Payment Required - 24 hour cooldown
                        if response.status == 402:
                            logger.warning(f"Key {key_index + 1} payment required (402)")
                            self._mark_key_payment_required(key_index)
                            
                            # Move to next key
                            self.current_key_index = (key_index + 1) % len(self.keys)
                            attempts += 1
                            
                            if attempts < max_attempts:
                                await asyncio.sleep(0.5)
                                continue
                            else:
                                raise RateLimitError("All Pollinations keys exhausted (payment required)")
                        
                        # Handle 429 Rate Limit - 60 minute cooldown
                        if response.status == 429:
                            logger.warning(f"Key {key_index + 1} rate limited (429)")
                            self._mark_key_rate_limited(key_index, cooldown_minutes=60)
                            
                            # Move to next key
                            self.current_key_index = (key_index + 1) % len(self.keys)
                            attempts += 1
                            
                            if attempts < max_attempts:
                                await asyncio.sleep(0.5)
                                continue
                            else:
                                raise RateLimitError("All Pollinations keys exhausted (rate limited)")
                        
                        # Handle other errors - increment error count
                        if response.status >= 400:
                            error_msg = f"Pollinations.ai error {response.status}"
                            logger.warning(f"Key {key_index + 1} failed: {error_msg}")
                            self._mark_key_error(key_index)
                            
                            # Move to next key
                            self.current_key_index = (key_index + 1) % len(self.keys)
                            attempts += 1
                            
                            if attempts < max_attempts:
                                await asyncio.sleep(0.5)
                                continue
                            else:
                                raise APIError(error_msg)
                        
                        # Успех! Получаем изображение
                        image_bytes = await response.read()
                        logger.debug(f"✅ Downloaded image with key {key_index + 1}/{len(self.keys)}: {len(image_bytes)} bytes")
                        
                        # Update key last used time
                        key.last_used = datetime.now()
                        
                        # Переключаемся на следующий ключ для следующего запроса
                        self.current_key_index = (key_index + 1) % len(self.keys)
                        
                        return image_bytes
                        
            except (RateLimitError, APIError):
                raise
            except Exception as e:
                logger.warning(f"Key {key_index + 1} exception: {e}")
                self._mark_key_error(key_index)
                
                # Move to next key
                self.current_key_index = (key_index + 1) % len(self.keys)
                attempts += 1
                
                if attempts < max_attempts:
                    await asyncio.sleep(0.5)
                    continue
                else:
                    raise APIError(f"All Pollinations keys failed: {e}")
        
        raise APIError("Failed to generate image with Pollinations")
    
    def _create_placeholder(
        self,
        output_path: Path,
        prompt: str = ""
    ) -> Path:
        """Create a placeholder image.
        
        Creates a simple placeholder image with text when generation fails.
        
        Args:
            output_path: Path where to save the placeholder
            prompt: Original prompt (for display on placeholder)
        
        Returns:
            Path to the saved placeholder image
        """
        logger.info(f"Creating placeholder image at: {output_path}")
        
        # Parse size
        try:
            width, height = map(int, self.size.split('x'))
        except:
            width, height = 1024, 1024
        
        # Create image with dark background
        img = Image.new('RGB', (width, height), color='#1a1a1a')
        draw = ImageDraw.Draw(img)
        
        # Add text
        try:
            # Try to use a nice font
            font_size = 40
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw centered text
        text = "Image Placeholder"
        
        # Get text bounding box
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        position = (
            (width - text_width) // 2,
            (height - text_height) // 2
        )
        
        draw.text(position, text, fill='#666666', font=font)
        
        # Add prompt text if provided (smaller)
        if prompt:
            try:
                small_font = ImageFont.truetype("arial.ttf", 20)
            except:
                small_font = ImageFont.load_default()
            
            # Truncate prompt if too long
            prompt_text = prompt[:50] + "..." if len(prompt) > 50 else prompt
            
            bbox = draw.textbbox((0, 0), prompt_text, font=small_font)
            text_width = bbox[2] - bbox[0]
            
            position = (
                (width - text_width) // 2,
                height // 2 + 60
            )
            
            draw.text(position, prompt_text, fill='#444444', font=small_font)
        
        # Save image
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        
        logger.info(f"Placeholder image created: {output_path}")
        return output_path
    
    async def generate_images_batch(
        self,
        prompts: list[tuple[str, Path]]
    ) -> list[Path]:
        """Generate multiple images in batch.
        
        Args:
            prompts: List of (prompt, output_path) tuples
        
        Returns:
            List of paths to generated images
        """
        logger.info(f"Generating {len(prompts)} images in batch")
        
        tasks = [
            self.generate_image(prompt, path)
            for prompt, path in prompts
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and return successful paths
        paths = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to generate image {i}: {result}")
                # Create placeholder for failed image
                _, path = prompts[i]
                paths.append(self._create_placeholder(path))
            else:
                paths.append(result)
        
        logger.info(f"Batch generation complete: {len(paths)} images")
        return paths
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of image generation service.
        
        Returns:
            Dictionary with service status information
        """
        active_keys = sum(1 for k in self.keys if k.status == PollinationsKeyStatus.ACTIVE)
        rate_limited_keys = sum(1 for k in self.keys if k.status == PollinationsKeyStatus.RATE_LIMITED)
        payment_required_keys = sum(1 for k in self.keys if k.status == PollinationsKeyStatus.PAYMENT_REQUIRED)
        error_keys = sum(1 for k in self.keys if k.status == PollinationsKeyStatus.ERROR)
        
        return {
            "provider": "pollinations",
            "status": "active" if active_keys > 0 else "degraded",
            "model": self.model,
            "total_keys": len(self.keys),
            "active_keys": active_keys,
            "rate_limited_keys": rate_limited_keys,
            "payment_required_keys": payment_required_keys,
            "error_keys": error_keys
        }
