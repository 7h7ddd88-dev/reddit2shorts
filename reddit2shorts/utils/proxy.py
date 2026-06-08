"""
Proxy utilities for HTTP clients.

This module provides utilities for creating HTTP clients with proxy support.
"""

import httplib2
import socks
import aiohttp
import os
from typing import Optional
from urllib.parse import urlparse

from reddit2shorts.utils.logger import get_logger

logger = get_logger(__name__)


def setup_proxy_env(proxy_url: str):
    """
    Setup environment variables for proxy.
    
    This is a fallback for libraries that don't support ProxyInfo directly.
    Sets HTTP_PROXY, HTTPS_PROXY, http_proxy, https_proxy environment variables.
    
    Args:
        proxy_url: Proxy URL in format "http://user:pass@host:port"
    """
    if not proxy_url:
        return
    
    # Set both uppercase and lowercase (some libraries check different variants)
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
    os.environ['http_proxy'] = proxy_url
    os.environ['https_proxy'] = proxy_url
    
    logger.debug(f"Set proxy environment variables: {mask_proxy_url(proxy_url)}")


def create_httplib2_with_proxy(proxy_url: Optional[str] = None) -> httplib2.Http:
    """
    Create httplib2.Http client with proxy support.
    
    This is used for Google API clients (YouTube, etc.) that use httplib2.
    
    Args:
        proxy_url: Proxy URL in format:
                  - http://username:password@host:port
                  - https://username:password@host:port
                  - socks5://username:password@host:port
                  - None for no proxy
    
    Returns:
        httplib2.Http client configured with proxy (if provided)
    
    Example:
        >>> http = create_httplib2_with_proxy("http://user:pass@proxy.com:8080")
        >>> # Use with Google API
        >>> from google_auth_httplib2 import AuthorizedHttp
        >>> authorized_http = AuthorizedHttp(credentials, http=http)
        >>> youtube = build('youtube', 'v3', http=authorized_http)
    """
    if not proxy_url:
        logger.debug("Creating httplib2.Http without proxy")
        return httplib2.Http()
    
    # Parse proxy URL
    parsed = urlparse(proxy_url)
    
    # For SOCKS5 proxies, use ProxyInfo
    if parsed.scheme == 'socks5':
        proxy_type = socks.PROXY_TYPE_SOCKS5
        
        logger.debug(f"Creating httplib2.Http with SOCKS5 proxy: {parsed.hostname}:{parsed.port}")
        
        proxy_info = httplib2.ProxyInfo(
            proxy_type=proxy_type,
            proxy_host=parsed.hostname,
            proxy_port=parsed.port or 1080,
            proxy_user=parsed.username,
            proxy_pass=parsed.password,
            proxy_rdns=False
        )
        
        http = httplib2.Http(
            proxy_info=proxy_info,
            disable_ssl_certificate_validation=True
        )
        
        logger.debug("httplib2.Http created with SOCKS5 proxy")
        return http
    
    elif parsed.scheme in ('http', 'https'):
        # For HTTP/HTTPS proxies, httplib2 has built-in support via proxy_info
        # BUT it doesn't work well with authentication through ProxyInfo
        # The ONLY reliable way is to use environment variables
        logger.debug(f"Creating httplib2.Http with HTTP proxy via environment: {parsed.hostname}:{parsed.port}")
        
        # Set environment variables (httplib2 will use them automatically)
        setup_proxy_env(proxy_url)
        
        # Create Http WITHOUT proxy_info (will use environment variables)
        http = httplib2.Http(
            disable_ssl_certificate_validation=True  # Enable for proxy compatibility
        )
        
        logger.debug("httplib2.Http created with HTTP proxy from environment")
        return http
    
    else:
        logger.warning(f"Unsupported proxy scheme: {parsed.scheme}, creating without proxy")
        return httplib2.Http()


def create_aiohttp_connector(proxy_url: Optional[str] = None) -> Optional[aiohttp.TCPConnector]:
    """
    Create aiohttp connector with proxy support.
    
    This is used for aiohttp-based clients (Gemini, Pollinations, etc.).
    
    Args:
        proxy_url: Proxy URL in format:
                  - http://username:password@host:port
                  - https://username:password@host:port
                  - socks5://username:password@host:port (requires aiohttp-socks)
                  - None for no proxy
    
    Returns:
        aiohttp.TCPConnector configured for proxy, or None for default connector
    
    Example:
        >>> connector = create_aiohttp_connector("http://user:pass@proxy.com:8080")
        >>> async with aiohttp.ClientSession(connector=connector) as session:
        ...     async with session.get(url, proxy=proxy_url) as response:
        ...         data = await response.read()
    
    Note:
        For HTTP/HTTPS proxies, aiohttp requires passing proxy URL to each request.
        For SOCKS5 proxies, use aiohttp-socks library (optional dependency).
    """
    if not proxy_url:
        logger.debug("Creating aiohttp connector without proxy")
        return None
    
    # Parse proxy URL
    parsed = urlparse(proxy_url)
    
    if parsed.scheme == 'socks5':
        # SOCKS5 requires aiohttp-socks (optional dependency)
        try:
            from aiohttp_socks import ProxyConnector
            
            connector = ProxyConnector.from_url(proxy_url)
            logger.debug(f"Creating aiohttp SOCKS5 connector: {parsed.hostname}:{parsed.port}")
            return connector
        except ImportError:
            logger.warning(
                "aiohttp-socks not installed, SOCKS5 proxy not supported. "
                "Install with: pip install aiohttp-socks"
            )
            return None
    elif parsed.scheme in ('http', 'https'):
        # HTTP/HTTPS proxies work with default connector + proxy parameter in requests
        logger.debug(f"Using aiohttp with HTTP proxy: {parsed.scheme}://{parsed.hostname}:{parsed.port}")
        return None  # Use default connector, pass proxy_url to requests
    else:
        logger.warning(f"Unsupported proxy scheme for aiohttp: {parsed.scheme}")
        return None


def mask_proxy_url(proxy_url: str) -> str:
    """
    Mask credentials in proxy URL for logging.
    
    Args:
        proxy_url: Proxy URL (e.g., "http://user:pass@host:port")
        
    Returns:
        Masked URL (e.g., "http://***:***@host:port")
    
    Example:
        >>> mask_proxy_url("http://user:pass@proxy.com:8080")
        'http://***:***@proxy.com:8080'
    """
    try:
        from urllib.parse import urlparse, urlunparse
        
        parsed = urlparse(proxy_url)
        
        if parsed.username and parsed.password:
            # Mask credentials
            netloc = f"***:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            
            masked = urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            return masked
        else:
            return proxy_url
    except Exception:
        return "***proxy***"
