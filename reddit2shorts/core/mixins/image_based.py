"""
Image-Based Mixin

Функциональность для работы с готовыми изображениями (Knights, DarkMotiv).
"""

from typing import List
from pathlib import Path
import random

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class ImageBasedMixin:
    """
    Миксин для оркестраторов, работающих с готовыми изображениями.
    
    Provides:
    - Выбор случайных изображений из папки
    - Валидация изображений
    """
    
    def _select_random_images(self, count: int, images_dir: Path) -> List[Path]:
        """
        Выбор случайных изображений из папки.
        
        Args:
            count: Количество изображений
            images_dir: Папка с изображениями
            
        Returns:
            Список путей к изображениям
        """
        # Получаем все изображения
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        all_images = [
            img for img in images_dir.iterdir()
            if img.is_file() and img.suffix.lower() in image_extensions
        ]
        
        if not all_images:
            raise Exception(f"No images found in {images_dir}")
        
        # Выбираем случайные
        if len(all_images) < count:
            self.logger.warning(f"Only {len(all_images)} images available, using all")
            return all_images
        
        selected = random.sample(all_images, count)
        self.logger.info(f"Selected images: {[img.name for img in selected]}")
        
        return selected
