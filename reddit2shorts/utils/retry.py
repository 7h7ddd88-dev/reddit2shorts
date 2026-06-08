"""
Retry decorator with exponential backoff for async functions.

This module provides a decorator for retrying async functions with configurable
max attempts, delay, and exponential backoff.

Requirements:
- 1.5: Reddit API retry logic
- 2.4: Google Sheets retry logic
- 5.4: TTS API retry logic
"""

import asyncio
from functools import wraps
from typing import Callable, Any, TypeVar

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Async retry decorator with exponential backoff.
    
    Retries an async function up to max_attempts times with exponential backoff
    between attempts. The delay between retries increases by the backoff factor
    after each failed attempt.
    
    Args:
        max_attempts: Maximum number of attempts (default: 3)
        delay: Initial delay in seconds between retries (default: 1.0)
        backoff: Multiplier for delay after each retry (default: 2.0)
    
    Returns:
        Decorated function that retries on exception
    
    Example:
        @async_retry(max_attempts=3, delay=1.0, backoff=2.0)
        async def api_call():
            # Retries with delays: 1s, 2s, 4s
            response = await make_request()
            return response
    
    Raises:
        The last exception raised if all retry attempts fail
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )
                    
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            # This should never be reached, but just in case
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator
