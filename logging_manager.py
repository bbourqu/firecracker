#!/usr/bin/env python3
"""
Logging Manager for Firecracker OpenAI Code Generator

Provides centralized logging infrastructure management using Loguru framework.
Handles console and file logging with configurable formats, rotation, and retention.

Features:
- Beautiful colored console output with structured data
- JSON logging for production monitoring and analysis  
- Automatic log rotation, compression, and retention
- Context binding for correlated logging across VM lifecycle
- Environment-specific logging profiles (dev/prod)

Dependencies:
- loguru: Professional logging framework
- omegaconf: Configuration management
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger
from omegaconf import DictConfig


class LoggingManager:
    """Centralized logging infrastructure management using Loguru framework.
    
    Manages Loguru setup and configuration for the entire Firecracker orchestration system.
    Provides console logging with colors, file logging with rotation, and structured
    logging for production environments.
    
    Attributes:
        config (DictConfig): Logging configuration from Hydra
        logger (Logger): Configured Loguru logger instance
        
    Example:
        log_manager = LoggingManager()
        log_manager.setup_logging(config)
        log_manager.log_info("VM started", vm_id="abc123", memory_mb=512)
    """
    
    def __init__(self):
        """Initialize the logging manager."""
        self.config: Optional[DictConfig] = None
        
    def setup_logging(self, cfg: DictConfig):
        """Configure Loguru logging based on Hydra configuration.
        
        Sets up console and file logging with the specified format, level, and rotation
        settings. Removes default Loguru handlers and configures new handlers based
        on the provided configuration.
        
        Args:
            cfg (DictConfig): Configuration object with logging settings
            
        Logging Configuration Options:
            - level: DEBUG, INFO, WARNING, ERROR, CRITICAL
            - format: simple, detailed, json
            - file: Optional file path for file logging
            - rotation: Log rotation size (default: 100 MB)
            - retention: Log retention period (default: 30 days)
            - colorize: Enable/disable console colors (default: True)
            
        Example:
            log_config = {
                'logging': {
                    'level': 'INFO',
                    'format': 'detailed',
                    'file': 'logs/firecracker.log',
                    'rotation': '50 MB',
                    'retention': '14 days'
                }
            }
            log_manager.setup_logging(log_config)
        """
        self.config = cfg
        log_config = cfg.logging
        
        # Remove default Loguru handler
        logger.remove()
        
        # Configure console logging format
        console_format = self._get_console_format(log_config.format)
        
        # Add console handler with colors
        logger.add(
            sys.stderr,
            format=console_format,
            level=log_config.level.upper(),
            colorize=log_config.get("colorize", True),
            backtrace=True,
            diagnose=True
        )
        
        # Add file handler if specified
        if log_config.file:
            self._setup_file_logging(log_config)
        
        # Log the configuration
        logger.info("Loguru logging configured", 
                    level=log_config.level, 
                    format=log_config.format,
                    file=log_config.file or "console-only")
    
    def _get_console_format(self, format_type: str) -> str:
        """Get console logging format string based on configuration.
        
        Args:
            format_type (str): Format type - simple, detailed, or json
            
        Returns:
            str: Loguru format string for console output
        """
        if format_type == "simple":
            return "<level>{level}</level> - {message}"
        elif format_type == "json":
            # For JSON format, use structured format but still readable on console
            return "{time:HH:mm:ss} | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | {message}"
        else:  # detailed
            return "{time:HH:mm:ss} | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    
    def _setup_file_logging(self, log_config: DictConfig):
        """Setup file logging with rotation and compression.
        
        Args:
            log_config (DictConfig): Logging configuration object
        """
        file_path = Path(log_config.file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if log_config.format == "json":
            # JSON format for structured logging
            logger.add(
                file_path,
                format="{time} | {level} | {name} | {function} | {line} | {message} | {extra}",
                level=log_config.level.upper(),
                rotation=log_config.get("rotation", "100 MB"),
                retention=log_config.get("retention", "30 days"),
                compression="gz",
                serialize=True  # Enable JSON serialization
            )
        else:
            # Human-readable format for files
            logger.add(
                file_path,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                level=log_config.level.upper(),
                rotation=log_config.get("rotation", "100 MB"),
                retention=log_config.get("retention", "30 days"),
                compression="gz"
            )
    
    @staticmethod
    def get_logger():
        """Get the configured Loguru logger instance.
        
        Returns:
            Logger: Configured Loguru logger
        """
        return logger
    
    def log_vm_operation(self, message: str, vm_id: str, **context):
        """Log VM operation with structured context.
        
        Args:
            message (str): Log message
            vm_id (str): Virtual machine identifier
            **context: Additional context data (memory_mb, vcpus, etc.)
        """
        logger.info(message, vm_id=vm_id, **context)
    
    def log_network_operation(self, message: str, tap_name: str, **context):
        """Log network operation with structured context.
        
        Args:
            message (str): Log message  
            tap_name (str): TAP interface name
            **context: Additional context data (cidr, gateway_ip, etc.)
        """
        logger.info(message, tap_name=tap_name, **context)
    
    def log_task_operation(self, message: str, task_id: str, **context):
        """Log task operation with structured context.
        
        Args:
            message (str): Log message
            task_id (str): Task identifier
            **context: Additional context data (status, api_status, etc.)
        """
        logger.info(message, task_id=task_id, **context)
    
    def log_success(self, message: str, **context):
        """Log success message with SUCCESS level.
        
        Args:
            message (str): Success message
            **context: Additional context data
        """
        logger.success(message, **context)
    
    def log_error(self, message: str, **context):
        """Log error message with ERROR level.
        
        Args:
            message (str): Error message
            **context: Additional context data
        """
        logger.error(message, **context)
    
    def log_warning(self, message: str, **context):
        """Log warning message with WARNING level.
        
        Args:
            message (str): Warning message
            **context: Additional context data
        """
        logger.warning(message, **context)
    
    def log_debug(self, message: str, **context):
        """Log debug message with DEBUG level.
        
        Args:
            message (str): Debug message
            **context: Additional context data
        """
        logger.debug(message, **context)


# Global logging manager instance for easy access
_logging_manager = LoggingManager()

def setup_logging(cfg: DictConfig):
    """Setup global logging configuration.
    
    Convenience function for setting up logging using the global LoggingManager instance.
    This maintains backward compatibility with the existing setup_logging function.
    
    Args:
        cfg (DictConfig): Configuration object with logging settings
    """
    _logging_manager.setup_logging(cfg)

def get_logger():
    """Get the configured logger instance.
    
    Returns:
        Logger: Configured Loguru logger
    """
    return _logging_manager.get_logger()