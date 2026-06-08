"""
Video Generation Mixin

Функциональность для генерации видео через Pollinations API.
"""

from typing import Optional
from pathlib import Path
from datetime import datetime
import asyncio
import urllib.parse
import aiohttp

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class VideoGenerationMixin:
    """
    Миксин для оркестраторов, генерирующих видео через Pollinations.
    
    Provides:
    - Генерация видео через Pollinations API
    - Ротация API ключей
    - Валидация duration для разных моделей
    """
    
    async def generate_video_with_pollinations(
        self,
        prompt: str,
        duration: int = 6,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Генерация видео через Pollinations API с ротацией ключей.
        
        Args:
            prompt: Промпт для генерации видео
            duration: Длительность видео в секундах
            output_dir: Директория для сохранения (если None, используется temp_dir)
            
        Returns:
            Путь к сгенерированному видео
        """
        # Normalize model name (grok/grok-video -> veo)
        model = self.pollinations_model
        if model in ["grok", "grok-video"]:
            model = "veo"
            self.logger.info(f"Model '{self.pollinations_model}' mapped to 'veo'")
        
        # Валидация duration в зависимости от модели
        if model == "veo":
            # veo поддерживает только 4, 6, 8 секунд
            valid_durations = [4, 6, 8]
            if duration not in valid_durations:
                # Округляем до ближайшего валидного значения
                duration = min(valid_durations, key=lambda x: abs(x - duration))
                self.logger.info(f"Duration adjusted to {duration}s for veo model")
        elif model in ["seedance", "seedance-pro"]:
            # seedance поддерживает 2-10 секунд
            duration = max(2, min(10, duration))
        
        encoded_prompt = urllib.parse.quote(prompt)
        
        # Pollinations endpoint
        url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        
        self.logger.info(f"Generating video with Pollinations (config: {self.pollinations_model}, using: {model})")
        self.logger.info(f"Duration: {duration}s")
        self.logger.info(f"Prompt: {prompt[:100]}...")
        
        # Пробуем все ключи с ротацией
        for attempt in range(len(self.pollinations_api_keys)):
            try:
                api_key = self.pollinations_api_keys[self.current_pollinations_key_index]
                
                params = {
                    "key": api_key,
                    "model": model,
                    "duration": duration,
                    "aspectRatio": "9:16",  # Vertical format for Shorts
                    "enhance": "true"
                }
                
                self.logger.info(f"Attempt {attempt + 1}/{len(self.pollinations_api_keys)} with key {self.current_pollinations_key_index + 1}")
                self.logger.info(f"Request params: model={model}, duration={duration}, aspectRatio=9:16")
                
                # Get default proxy from config
                default_proxy = getattr(self, 'config', {}).get('default_proxy')
                
                # Create aiohttp connector with proxy support
                from reddit2shorts.utils.proxy import create_aiohttp_connector
                connector = create_aiohttp_connector(default_proxy)
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    # Prepare request kwargs
                    request_kwargs = {
                        "params": params,
                        "timeout": aiohttp.ClientTimeout(total=300)  # 5 minutes
                    }
                    
                    # Add proxy for HTTP/HTTPS (not SOCKS5)
                    if default_proxy and not connector:
                        request_kwargs["proxy"] = default_proxy
                    
                    async with session.get(url, **request_kwargs) as response:
                        
                        if response.status != 200:
                            error_text = await response.text()
                            self.logger.warning(f"Key {self.current_pollinations_key_index + 1} failed: {response.status} - {error_text[:200]}")
                            
                            # Переключаемся на следующий ключ
                            self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                            
                            if attempt == len(self.pollinations_api_keys) - 1:
                                raise Exception(f"All Pollinations keys failed. Last error: {error_text[:200]}")
                            
                            continue
                        
                        content_type = response.headers.get('Content-Type', '')
                        
                        if 'video' not in content_type and 'octet-stream' not in content_type:
                            self.logger.warning(f"Unexpected content type: {content_type}")
                            
                            # Переключаемся на следующий ключ
                            self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                            
                            if attempt == len(self.pollinations_api_keys) - 1:
                                raise Exception(f"Unexpected content type: {content_type}")
                            
                            continue
                        
                        video_bytes = await response.read()
                        
                        if len(video_bytes) < 10000:  # Less than 10KB
                            self.logger.warning(f"Video too small: {len(video_bytes)} bytes")
                            
                            # Переключаемся на следующий ключ
                            self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                            
                            if attempt == len(self.pollinations_api_keys) - 1:
                                raise Exception(f"Video too small: {len(video_bytes)} bytes")
                            
                            continue
                        
                        # Успех! Сохраняем видео
                        save_dir = output_dir or self.file_manager.temp_dir
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        video_path = save_dir / f"generated_{timestamp}.mp4"
                        video_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        video_path.write_bytes(video_bytes)
                        
                        self.logger.info(f"✅ Video generated successfully with key {self.current_pollinations_key_index + 1}")
                        self.logger.info(f"Video saved: {video_path}")
                        self.logger.info(f"Size: {len(video_bytes):,} bytes ({len(video_bytes)/1024/1024:.2f} MB)")
                        
                        # Переключаемся на следующий ключ для следующего запроса
                        self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                        
                        return video_path
                        
            except asyncio.TimeoutError:
                self.logger.warning(f"Key {self.current_pollinations_key_index + 1} timeout")
                self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                
                if attempt == len(self.pollinations_api_keys) - 1:
                    raise Exception("All Pollinations keys timed out")
                
                continue
            
            except Exception as e:
                self.logger.warning(f"Key {self.current_pollinations_key_index + 1} exception: {e}")
                self.current_pollinations_key_index = (self.current_pollinations_key_index + 1) % len(self.pollinations_api_keys)
                
                if attempt == len(self.pollinations_api_keys) - 1:
                    raise Exception(f"All Pollinations keys failed: {e}")
                
                continue
        
        raise Exception("Failed to generate video with Pollinations")
