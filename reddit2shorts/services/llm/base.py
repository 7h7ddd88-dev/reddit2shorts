"""Base LLM provider interface.

This module defines the abstract base class for all LLM providers and
data models for script generation.

Requirements: 3.1, 3.5, 3.6
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScriptSegment:
    """A segment of the generated script with timing information.
    
    Attributes:
        text: The text content of this segment
        start_time: Start time in seconds
        end_time: End time in seconds
        duration: Duration in seconds
        image_prompt: Optional prompt for image generation for this segment
    
    Requirements:
        - 3.5: Script segments with timing information
    """
    text: str
    start_time: float
    end_time: float
    duration: float
    image_prompt: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert segment to dictionary.
        
        Returns:
            Dictionary representation of the segment
        """
        return {
            'text': self.text,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'image_prompt': self.image_prompt
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScriptSegment':
        """Create segment from dictionary.
        
        Args:
            data: Dictionary with segment data
        
        Returns:
            ScriptSegment instance
        """
        return cls(
            text=data['text'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            duration=data['duration'],
            image_prompt=data.get('image_prompt')
        )


@dataclass
class GeneratedScript:
    """A complete generated script with metadata.
    
    Attributes:
        title: Video title
        description: Video description
        full_text: Complete script text
        segments: List of script segments with timing
        metadata: Additional metadata (model used, generation time, etc.)
        total_duration: Total duration in seconds
    
    Requirements:
        - 3.5: Structured script output with segments
    """
    title: str
    description: str
    full_text: str
    segments: List[ScriptSegment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    total_duration: float = 0.0
    
    def __post_init__(self):
        """Calculate total duration from segments."""
        if self.segments and self.total_duration == 0.0:
            self.total_duration = sum(seg.duration for seg in self.segments)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert script to dictionary.
        
        Returns:
            Dictionary representation of the script
        """
        return {
            'title': self.title,
            'description': self.description,
            'full_text': self.full_text,
            'segments': [seg.to_dict() for seg in self.segments],
            'metadata': self.metadata,
            'total_duration': self.total_duration
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GeneratedScript':
        """Create script from dictionary.
        
        Args:
            data: Dictionary with script data
        
        Returns:
            GeneratedScript instance
        """
        segments = [
            ScriptSegment.from_dict(seg_data)
            for seg_data in data.get('segments', [])
        ]
        
        return cls(
            title=data['title'],
            description=data['description'],
            full_text=data['full_text'],
            segments=segments,
            metadata=data.get('metadata', {}),
            total_duration=data.get('total_duration', 0.0)
        )


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers.
    
    All LLM providers must implement this interface to ensure consistent
    behavior across different providers (OpenAI, Anthropic, Cerebras, etc.).
    
    Attributes:
        api_key: API key for the provider
        model: Model name to use
        base_url: Optional custom base URL for API
    
    Requirements:
        - 3.1: Generate scripts from stories
        - 3.6: Support multiple provider formats
    """
    
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None
    ):
        """Initialize LLM provider.
        
        Args:
            api_key: API key for authentication
            model: Model name to use
            base_url: Optional custom base URL
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
    
    @abstractmethod
    async def generate_script(
        self,
        story_title: str,
        story_text: str,
        content_type: str = "motivational speech",
        art_style: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.7
    ) -> GeneratedScript:
        """Generate a video script from a Reddit story.
        
        This method must be implemented by all providers to generate
        a structured script with segments and timing information.
        
        Args:
            story_title: Title of the Reddit story
            story_text: Full text of the story
            content_type: Type of content to generate (e.g., "motivational speech")
            art_style: Art style description for image prompts
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
        
        Returns:
            GeneratedScript with title, description, segments, and timing
        
        Raises:
            APIError: If generation fails
            RateLimitError: If rate limit is hit
        
        Requirements:
            - 3.1: Generate script from story
            - 3.5: Return structured script with segments
        """
        pass
    
    @abstractmethod
    def _build_prompt(
        self,
        story_title: str,
        story_text: str,
        content_type: str,
        art_style: str
    ) -> str:
        """Build the prompt for script generation.
        
        Each provider may have different prompt requirements, so this
        method allows customization per provider.
        
        Args:
            story_title: Title of the story
            story_text: Full text of the story
            content_type: Type of content to generate
            art_style: Art style description
        
        Returns:
            Formatted prompt string
        """
        pass
    
    def _parse_response(
        self,
        response_text: str
    ) -> GeneratedScript:
        """Parse the LLM response into a GeneratedScript.
        
        This is a common implementation that can be overridden by providers
        if they need custom parsing logic.
        
        Args:
            response_text: Raw response text from LLM
        
        Returns:
            GeneratedScript object
        
        Raises:
            ValueError: If response cannot be parsed
        """
        import json
        
        try:
            # Try to parse as JSON
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # If not JSON, try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                raise ValueError("Could not parse LLM response as JSON")
        
        # Extract title and description
        title = data.get('title', 'Untitled')
        description = data.get('description', '')
        
        # Parse segments
        segments = []
        current_time = 0.0
        
        for seg_data in data.get('scenes', []):
            text = seg_data.get('text', '').strip()
            
            # Basic validation: skip if text is empty or too short
            if not text or len(text) < 5:
                logger.warning(f"Skipping empty or too short segment")
                continue
            
            # Validate: skip if text contains obvious JSON artifacts
            # (should not happen with response_format=json_object, but safety check)
            if text.count('{') > 1 or text.count('}') > 1 or '"scenes"' in text.lower():
                logger.warning(f"Skipping segment with JSON artifacts: {text[:50]}...")
                continue
            
            duration = float(seg_data.get('duration', 3.0))
            segment = ScriptSegment(
                text=text,
                start_time=current_time,
                end_time=current_time + duration,
                duration=duration,
                image_prompt=seg_data.get('image_prompt')
            )
            segments.append(segment)
            current_time += duration
        
        # Validate we got segments
        if not segments:
            raise ValueError("No valid segments in LLM response")
        
        # Build full text from segments
        full_text = ' '.join(seg.text for seg in segments)
        
        return GeneratedScript(
            title=title,
            description=description,
            full_text=full_text,
            segments=segments,
            metadata={
                'model': self.model,
                'provider': self.__class__.__name__
            }
        )
    
    def get_provider_name(self) -> str:
        """Get the name of this provider.
        
        Returns:
            Provider name (e.g., "OpenAI", "Anthropic")
        """
        return self.__class__.__name__.replace('Provider', '')
