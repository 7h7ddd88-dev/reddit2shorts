"""
Subtitles Mixin

Функциональность для работы с субтитрами.
"""

import re
from typing import List, Any
from reddit2shorts.services.video import SubtitleSegment
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class SubtitlesMixin:
    """
    Миксин для работы с субтитрами.
    
    Provides:
    - Создание субтитров из сегментов скрипта
    - Фильтрация субтитров для временного диапазона
    - Создание субтитров для longform (разбивка на предложения)
    """
    
    def _create_subtitles(self, segments: List[Any]) -> List[SubtitleSegment]:
        """
        Создание субтитров из сегментов скрипта.
        
        Args:
            segments: Сегменты скрипта
            
        Returns:
            Список субтитров
        """
        subtitles = []
        
        for segment in segments:
            subtitles.append(SubtitleSegment(
                text=segment.text,
                start_time=segment.start_time,
                end_time=segment.end_time
            ))
        
        return subtitles
    
    def _get_segment_subtitles(
        self,
        all_subtitles: List[SubtitleSegment],
        start_time: float,
        end_time: float
    ) -> List[SubtitleSegment]:
        """
        Получение субтитров для конкретного сегмента.
        
        Args:
            all_subtitles: Все субтитры
            start_time: Начало сегмента
            end_time: Конец сегмента
            
        Returns:
            Субтитры для этого сегмента (с adjusted временем)
        """
        segment_subtitles = []
        
        for subtitle in all_subtitles:
            # Проверяем пересечение с сегментом
            if subtitle.end_time <= start_time or subtitle.start_time >= end_time:
                continue
            
            # Создаём новый субтитр с adjusted временем (относительно начала сегмента)
            new_start = max(0, subtitle.start_time - start_time)
            new_end = min(end_time - start_time, subtitle.end_time - start_time)
            
            segment_subtitles.append(SubtitleSegment(
                text=subtitle.text,
                start_time=new_start,
                end_time=new_end
            ))
        
        return segment_subtitles
    
    def _create_longform_subtitles(
        self,
        text: str,
        segment_duration: float
    ) -> List[SubtitleSegment]:
        """
        Создание субтитров для longform видео (разбивка на предложения).
        
        Каждое предложение показывается отдельно (typewriter эффект),
        заменяя предыдущее предложение (не накапливается).
        
        Args:
            text: Текст сегмента для разбивки на предложения
            segment_duration: Длительность сегмента в секундах
            
        Returns:
            Список субтитров (по одному на предложение)
        """
        # Разбиваем текст на предложения по знакам препинания
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Если не удалось разбить, используем весь текст
        if not sentences:
            sentences = [text]
        
        # Делим время равномерно между предложениями
        sentence_duration = segment_duration / len(sentences)
        subtitles = []
        
        for i, sentence in enumerate(sentences):
            subtitles.append(SubtitleSegment(
                text=sentence,
                start_time=i * sentence_duration,
                end_time=(i + 1) * sentence_duration
            ))
        
        return subtitles
