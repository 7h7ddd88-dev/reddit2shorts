"""LLM service package for script generation.

This package provides LLM providers for generating video scripts from Reddit stories.
Supports multiple providers with automatic failover and API key rotation.

Providers:
- OpenAI (GPT-4, GPT-3.5)
- Cerebras (gpt-oss-120b)
- OpenRouter (DeepSeek, various models)
- Anthropic (Claude)
- Groq (Llama, Mixtral)
"""

from reddit2shorts.services.llm.base import (
    BaseLLMProvider,
    GeneratedScript,
    ScriptSegment,
)
from reddit2shorts.services.llm.service import LLMService

__all__ = [
    'BaseLLMProvider',
    'GeneratedScript',
    'ScriptSegment',
    'LLMService',
]
