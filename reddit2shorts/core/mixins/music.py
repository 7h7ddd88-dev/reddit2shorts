"""
Music Mixin

Функциональность для работы с фоновой музыкой.
"""

import random
from pathlib import Path
from typing import Optional, List

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class MusicMixin:
    """
    Миксин для работы с фоновой музыкой.
    
    Provides:
    - Добавление фоновой музыки к видео
    - Получение пути к музыке из конфигурации
    - Выбор случайной музыки из списка файлов
    """
    
    async def _add_background_music(
        self,
        video_path: Path,
        output_path: Path,
        music_volume: float = 0.1
    ) -> Optional[Path]:
        """
        Добавление фоновой музыки к видео.
        
        Args:
            video_path: Путь к видео без музыки
            output_path: Путь для сохранения видео с музыкой
            music_volume: Громкость музыки (0.0-1.0)
            
        Returns:
            Путь к видео с музыкой или None если музыка не найдена
        """
        music_path = self._get_music_path()
        
        if not music_path or not music_path.exists():
            self.logger.warning("Background music not found, using video without music")
            return video_path
        
        self.logger.info(f"Adding background music: {music_path}")
        
        result = await self.video_service.add_background_music(
            video_path=video_path,
            music_path=music_path,
            output_path=output_path,
            music_volume=music_volume
        )
        
        return result
    
    def _get_music_path(self) -> Optional[Path]:
        """
        Получение пути к фоновой музыке из конфигурации.
        
        Поддерживает два формата:
        1. Строка: background_music_path: "music/track.mp3" → возвращает этот файл
        2. Список: background_music_path: ["music/1.wav", "music/2.wav"] → случайный выбор
        
        Returns:
            Путь к музыке или None
        """
        # Пробуем получить из flow-specific конфигурации
        flow_config = self.config.get(self.flow_name, {})
        music_path_config = flow_config.get("background_music_path")
        
        # Если нет, пробуем из общей конфигурации
        if not music_path_config:
            music_path_config = self.config.get("background_music_path")
        
        if not music_path_config:
            return None
        
        # Проверяем тип: строка или список
        if isinstance(music_path_config, str):
            # Один файл
            return Path(music_path_config)
        elif isinstance(music_path_config, list):
            # Список файлов - выбираем случайный
            if not music_path_config:
                return None
            
            # Фильтруем только существующие файлы
            available_files = [Path(f) for f in music_path_config if Path(f).exists()]
            
            if not available_files:
                self.logger.warning(f"No music files found from list: {music_path_config}")
                return None
            
            # Случайный выбор
            selected = random.choice(available_files)
            self.logger.info(f"Selected random music: {selected.name} (from {len(available_files)} available)")
            return selected
        else:
            self.logger.warning(f"Invalid background_music_path type: {type(music_path_config)}")
            return None
    
    def _select_random_music_from_list(
        self,
        music_dir: Path,
        music_files: List[str]
    ) -> Optional[Path]:
        """
        Выбор случайного музыкального файла из списка.
        
        Args:
            music_dir: Директория с музыкой
            music_files: Список имен файлов (например: ["1.wav", "2.wav", "3.wav"])
            
        Returns:
            Path к выбранному файлу или None если ни один не найден
        """
        # Проверяем какие файлы существуют
        available_music = []
        for music_file in music_files:
            music_path = music_dir / music_file
            if music_path.exists():
                available_music.append(music_path)
        
        if not available_music:
            self.logger.warning(f"No music files found in {music_dir} (looking for: {', '.join(music_files)})")
            return None
        
        # Случайный выбор
        selected_music = random.choice(available_music)
        self.logger.info(f"Selected random music: {selected_music.name} (from {len(available_music)} available)")
        
        return selected_music
