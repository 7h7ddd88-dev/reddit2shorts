"""
Custom exception hierarchy for Reddit2Shorts application.

This module defines all custom exceptions used throughout the application,
providing clear error types for different failure scenarios.

Requirements: 10.3
"""

from typing import Optional, Dict, Any


class Reddit2ShortsError(Exception):
    """
    Base exception class for all Reddit2Shorts errors.
    
    All custom exceptions in the application should inherit from this class
    to allow for centralized error handling and logging.
    
    Attributes:
        message: Human-readable error message
        details: Optional dictionary with additional error context
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize the exception.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message
    
    def __repr__(self) -> str:
        """Return detailed representation of the error."""
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


class ConfigurationError(Reddit2ShortsError):
    """
    Exception raised for configuration-related errors.
    
    This includes:
    - Invalid configuration values
    - Missing required configuration
    - Configuration validation failures
    - Environment variable issues
    
    Requirements: 9.4, 9.5
    
    Example:
        >>> raise ConfigurationError(
        ...     "Missing required API key",
        ...     details={"field": "reddit.client_id"}
        ... )
    """
    pass


class APIError(Reddit2ShortsError):
    """
    Exception raised for API-related errors.
    
    This includes:
    - HTTP errors from external APIs
    - Invalid API responses
    - Authentication failures
    - Network connectivity issues
    
    Requirements: 1.5, 2.4, 3.1, 4.1, 5.4, 6.1, 8.6
    
    Attributes:
        status_code: HTTP status code if applicable
        provider: Name of the API provider
        response_data: Raw response data from the API
    
    Example:
        >>> raise APIError(
        ...     "Reddit API request failed",
        ...     details={
        ...         "status_code": 503,
        ...         "provider": "reddit",
        ...         "endpoint": "/r/selfimprovement/hot"
        ...     }
        ... )
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        provider: Optional[str] = None,
        response_data: Optional[Any] = None
    ):
        """
        Initialize the API error.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
            status_code: HTTP status code if applicable
            provider: Name of the API provider
            response_data: Raw response data from the API
        """
        details = details or {}
        if status_code is not None:
            details['status_code'] = status_code
        if provider is not None:
            details['provider'] = provider
        if response_data is not None:
            details['response_data'] = response_data
        
        super().__init__(message, details)
        self.status_code = status_code
        self.provider = provider
        self.response_data = response_data


class RateLimitError(APIError):
    """
    Exception raised when API rate limits are exceeded.
    
    This is a specialized APIError for rate limiting scenarios,
    allowing for specific handling like key rotation and cooldown periods.
    
    Requirements: 3.2, 4.2, 14.2, 14.5
    
    Attributes:
        retry_after: Seconds to wait before retrying (if provided by API)
        api_key: The API key that hit the rate limit
        cooldown_minutes: Recommended cooldown period in minutes
    
    Example:
        >>> raise RateLimitError(
        ...     "OpenAI API rate limit exceeded",
        ...     details={
        ...         "provider": "openai",
        ...         "api_key": "sk-...xyz",
        ...         "retry_after": 60
        ...     }
        ... )
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 429,
        provider: Optional[str] = None,
        retry_after: Optional[int] = None,
        api_key: Optional[str] = None,
        cooldown_minutes: int = 60
    ):
        """
        Initialize the rate limit error.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
            status_code: HTTP status code (default: 429)
            provider: Name of the API provider
            retry_after: Seconds to wait before retrying
            api_key: The API key that hit the rate limit
            cooldown_minutes: Recommended cooldown period in minutes
        """
        details = details or {}
        if retry_after is not None:
            details['retry_after'] = retry_after
        if api_key is not None:
            # Mask the API key for security (show only last 4 chars)
            masked_key = f"...{api_key[-4:]}" if len(api_key) > 4 else "***"
            details['api_key'] = masked_key
        if cooldown_minutes:
            details['cooldown_minutes'] = cooldown_minutes
        
        super().__init__(message, details, status_code, provider)
        self.retry_after = retry_after
        self.api_key = api_key
        self.cooldown_minutes = cooldown_minutes


class WorkflowError(Reddit2ShortsError):
    """
    Exception raised for workflow execution errors.
    
    This includes:
    - Workflow state management failures
    - Step execution failures
    - Invalid workflow transitions
    - Resume/recovery failures
    
    Requirements: 15.2, 15.3
    
    Attributes:
        workflow_id: Unique identifier of the workflow
        step: Current workflow step where error occurred
        state: Current workflow state
    
    Example:
        >>> raise WorkflowError(
        ...     "Failed to save workflow state",
        ...     details={
        ...         "workflow_id": "wf_123abc",
        ...         "step": "llm_generation",
        ...         "state": "processing"
        ...     }
        ... )
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None,
        step: Optional[str] = None,
        state: Optional[str] = None
    ):
        """
        Initialize the workflow error.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
            workflow_id: Unique identifier of the workflow
            step: Current workflow step where error occurred
            state: Current workflow state
        """
        details = details or {}
        if workflow_id is not None:
            details['workflow_id'] = workflow_id
        if step is not None:
            details['step'] = step
        if state is not None:
            details['state'] = state
        
        super().__init__(message, details)
        self.workflow_id = workflow_id
        self.step = step
        self.state = state


class ResourceError(Reddit2ShortsError):
    """
    Exception raised for resource-related errors.
    
    This includes:
    - File system errors (read/write failures)
    - Disk space issues
    - Missing files or directories
    - Permission errors
    - Resource cleanup failures
    
    Requirements: 15.1, 15.5
    
    Attributes:
        resource_type: Type of resource (file, directory, disk, etc.)
        resource_path: Path to the resource if applicable
        operation: Operation that failed (read, write, delete, etc.)
    
    Example:
        >>> raise ResourceError(
        ...     "Failed to write audio file",
        ...     details={
        ...         "resource_type": "file",
        ...         "resource_path": "/tmp/audio_123.mp3",
        ...         "operation": "write"
        ...     }
        ... )
    """
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        resource_type: Optional[str] = None,
        resource_path: Optional[str] = None,
        operation: Optional[str] = None
    ):
        """
        Initialize the resource error.
        
        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error context
            resource_type: Type of resource (file, directory, disk, etc.)
            resource_path: Path to the resource if applicable
            operation: Operation that failed (read, write, delete, etc.)
        """
        details = details or {}
        if resource_type is not None:
            details['resource_type'] = resource_type
        if resource_path is not None:
            details['resource_path'] = resource_path
        if operation is not None:
            details['operation'] = operation
        
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_path = resource_path
        self.operation = operation
