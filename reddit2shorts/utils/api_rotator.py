"""
API Key Rotation System

This module provides a robust API key rotation system for handling rate limits
and errors across multiple API providers. It tracks key status, implements
cooldown periods, and automatically switches between providers when needed.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


class KeyStatus(Enum):
    """Status of an API key"""
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    COOLDOWN = "cooldown"


@dataclass
class APIKey:
    """Represents an API key with its status and metadata"""
    key: str
    status: KeyStatus = KeyStatus.ACTIVE
    last_used: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    error_count: int = 0


@dataclass
class ProviderPool:
    """Pool of API keys for a single provider"""
    name: str
    keys: List[APIKey] = field(default_factory=list)
    current_index: int = 0
    
    def get_next_key(self) -> Optional[APIKey]:
        """
        Get next available key from the pool.
        
        Cycles through all keys looking for one that is either ACTIVE
        or has completed its cooldown period.
        
        Returns:
            APIKey if available, None if all keys are unavailable
        """
        for _ in range(len(self.keys)):
            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
            
            if key.status == KeyStatus.ACTIVE:
                return key
            elif key.status == KeyStatus.COOLDOWN:
                if key.cooldown_until and datetime.now() > key.cooldown_until:
                    key.status = KeyStatus.ACTIVE
                    logger.info(f"Key cooldown expired for {self.name}, reactivating")
                    return key
        
        return None
    
    def mark_rate_limited(self, key: APIKey, cooldown_minutes: int = 60):
        """
        Mark a key as rate limited and set cooldown period.
        
        Args:
            key: The API key to mark as rate limited
            cooldown_minutes: Duration of cooldown period in minutes
        """
        key.status = KeyStatus.COOLDOWN
        key.cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
        logger.warning(
            f"Key marked as rate limited for {self.name}, "
            f"cooldown until {key.cooldown_until.isoformat()}"
        )
    
    def mark_error(self, key: APIKey):
        """
        Mark a key as having an error.
        
        After 3 errors, the key is marked as ERROR status and won't be used.
        
        Args:
            key: The API key to mark as having an error
        """
        key.error_count += 1
        logger.warning(
            f"Key error count increased to {key.error_count} for {self.name}"
        )
        
        if key.error_count >= 3:
            key.status = KeyStatus.ERROR
            logger.error(
                f"Key marked as ERROR for {self.name} after {key.error_count} errors"
            )


class APIKeyRotator:
    """
    Manages API key rotation across multiple providers.
    
    This class coordinates key rotation within providers and across providers,
    implementing a fallback chain when keys are exhausted.
    
    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
    """
    
    def __init__(self, providers: List[Dict[str, Any]]):
        """
        Initialize the API key rotator.
        
        Args:
            providers: List of provider configurations, each containing:
                - name: Provider name (e.g., "cerebras", "openai")
                - api_keys: List of API key strings
        """
        self.pools: Dict[str, ProviderPool] = {}
        self.provider_order: List[str] = []
        
        for provider in providers:
            name = provider["name"]
            keys = [APIKey(key=k) for k in provider["api_keys"]]
            self.pools[name] = ProviderPool(name=name, keys=keys)
            self.provider_order.append(name)
            logger.info(f"Initialized provider pool '{name}' with {len(keys)} keys")
        
        self.current_provider_index = 0
        logger.info(
            f"API Key Rotator initialized with {len(self.provider_order)} providers: "
            f"{', '.join(self.provider_order)}"
        )
    
    def get_next_key(self) -> Optional[tuple[str, str]]:
        """
        Get next available key from any provider.
        
        Tries to get a key from the current provider first. If no keys are
        available, moves to the next provider in the rotation order.
        
        Returns:
            Tuple of (provider_name, api_key) if available, None if all keys exhausted
        """
        for _ in range(len(self.provider_order)):
            provider_name = self.provider_order[self.current_provider_index]
            pool = self.pools[provider_name]
            
            key = pool.get_next_key()
            if key:
                key.last_used = datetime.now()
                logger.info(f"Using key from provider '{provider_name}'")
                return (provider_name, key.key)
            
            # Move to next provider if current has no available keys
            logger.warning(
                f"No available keys for provider '{provider_name}', "
                f"switching to next provider"
            )
            self.current_provider_index = (
                (self.current_provider_index + 1) % len(self.provider_order)
            )
        
        logger.error("All API keys exhausted across all providers")
        return None
    
    def handle_rate_limit(self, provider_name: str, api_key: str, cooldown_minutes: int = 60):
        """
        Handle rate limit for a specific key.
        
        Marks the key as rate limited and sets a cooldown period.
        
        Args:
            provider_name: Name of the provider
            api_key: The API key that hit rate limit
            cooldown_minutes: Duration of cooldown period in minutes
        """
        pool = self.pools.get(provider_name)
        if pool:
            for key in pool.keys:
                if key.key == api_key:
                    pool.mark_rate_limited(key, cooldown_minutes)
                    logger.info(
                        f"Rate limit handled for {provider_name}, "
                        f"key will be available after {cooldown_minutes} minutes"
                    )
                    break
        else:
            logger.warning(f"Unknown provider '{provider_name}' in handle_rate_limit")
    
    def handle_error(self, provider_name: str, api_key: str):
        """
        Handle error for a specific key.
        
        Increments error count and marks key as ERROR after 3 errors.
        
        Args:
            provider_name: Name of the provider
            api_key: The API key that encountered an error
        """
        pool = self.pools.get(provider_name)
        if pool:
            for key in pool.keys:
                if key.key == api_key:
                    pool.mark_error(key)
                    logger.info(f"Error handled for {provider_name}")
                    break
        else:
            logger.warning(f"Unknown provider '{provider_name}' in handle_error")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get status of all keys across all providers.
        
        Returns:
            Dictionary mapping provider names to their status information:
                - total_keys: Total number of keys
                - active_keys: Number of active keys
                - rate_limited: Number of rate limited keys
                - error_keys: Number of keys with errors
        """
        status = {}
        for name, pool in self.pools.items():
            status[name] = {
                "total_keys": len(pool.keys),
                "active_keys": sum(1 for k in pool.keys if k.status == KeyStatus.ACTIVE),
                "rate_limited": sum(1 for k in pool.keys if k.status == KeyStatus.COOLDOWN),
                "error_keys": sum(1 for k in pool.keys if k.status == KeyStatus.ERROR)
            }
        return status
