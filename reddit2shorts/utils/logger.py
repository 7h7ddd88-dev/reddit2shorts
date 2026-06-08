"""
Logging configuration for Reddit2Shorts application.

This module provides centralized logging setup with console and file handlers,
log rotation, and customizable formatting.

Requirements: 10.1, 10.2, 10.4
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    console_output: bool = True
) -> None:
    """
    Configure logging for the application.
    
    Sets up both console and file handlers with rotation support.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Name of the log file (default: reddit2shorts.log)
        log_dir: Directory for log files (default: ./logs)
        max_bytes: Maximum size of log file before rotation (default: 10MB)
        backup_count: Number of backup log files to keep (default: 5)
        console_output: Whether to output logs to console (default: True)
    
    Requirements:
        - 10.1: Log all important events
        - 10.2: Use different log levels
        - 10.4: Save logs to files with rotation
    """
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Create formatter with timestamps
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # File handler with rotation
    if log_file or log_dir:
        # Set defaults
        if not log_file:
            log_file = "reddit2shorts.log"
        if not log_dir:
            log_dir = "./logs"
        
        # Create log directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Full path to log file
        full_log_path = log_path / log_file
        
        # Create rotating file handler
        file_handler = RotatingFileHandler(
            filename=str(full_log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Log the initialization
    root_logger.info(f"Logging initialized at {log_level} level")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Name of the logger (typically __name__ of the calling module)
    
    Returns:
        Logger instance configured with the application settings
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
    """
    return logging.getLogger(name)
