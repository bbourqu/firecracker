"""
Configuration schema validation for Firecracker OpenAI Code Generator.

This module defines dataclasses that provide type safety and validation
for configuration files. Used with Hydra and OmegaConf for robust
configuration management.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path
import os


@dataclass
class VMConfig:
    """Virtual machine configuration settings."""
    memory_mb: int = 512
    vcpus: int = 1
    timeout: int = 60
    network_cidr: str = "172.50.0.0/24"
    boot_timeout: int = 15
    shutdown_timeout: int = 10

    def __post_init__(self):
        """Validate VM configuration values."""
        if self.memory_mb < 128:
            raise ValueError("VM memory must be at least 128 MB")
        if self.memory_mb > 16384:
            raise ValueError("VM memory should not exceed 16 GB")
        if self.vcpus < 1 or self.vcpus > 32:
            raise ValueError("VM vCPUs must be between 1 and 32")
        if self.timeout < 10:
            raise ValueError("VM timeout must be at least 10 seconds")


@dataclass  
class PathsConfig:
    """Directory and file path configuration."""
    vm_images: str = "vm-images"
    ubuntu_images: str = "vm-images-ubuntu"
    shared: str = "shared"
    results: str = "results"
    temp: str = "/tmp"

    def __post_init__(self):
        """Convert string paths to Path objects and validate."""
        self.vm_images = Path(self.vm_images)
        self.ubuntu_images = Path(self.ubuntu_images)
        self.shared = Path(self.shared)
        self.results = Path(self.results)
        self.temp = Path(self.temp)


@dataclass
class OpenAIConfig:
    """OpenAI API configuration settings."""
    model: str = "gpt-3.5-turbo"
    max_tokens: int = 500
    temperature: float = 0.7
    timeout: int = 30

    def __post_init__(self):
        """Validate OpenAI configuration values."""
        if self.max_tokens < 1 or self.max_tokens > 4096:
            raise ValueError("OpenAI max_tokens must be between 1 and 4096")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("OpenAI temperature must be between 0.0 and 2.0")
        if self.timeout < 5:
            raise ValueError("OpenAI timeout must be at least 5 seconds")
        
        # Validate model name
        valid_models = [
            "gpt-3.5-turbo", "gpt-3.5-turbo-16k",
            "gpt-4", "gpt-4-32k", "gpt-4-turbo-preview"
        ]
        if self.model not in valid_models:
            raise ValueError(f"Invalid OpenAI model. Must be one of: {valid_models}")


@dataclass
class LoggingConfig:
    """Logging configuration settings."""
    level: str = "INFO"
    format: str = "detailed"  # simple, detailed, json
    console: bool = True
    file: Optional[str] = None
    rotation: str = "100 MB"
    retention: str = "30 days"
    colorize: bool = True

    def __post_init__(self):
        """Validate logging configuration values."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.level.upper() not in valid_levels:
            raise ValueError(f"Invalid log level. Must be one of: {valid_levels}")
        self.level = self.level.upper()
        
        valid_formats = ["simple", "detailed", "json"]
        if self.format not in valid_formats:
            raise ValueError(f"Invalid log format. Must be one of: {valid_formats}")


@dataclass
class FirecrackerConfig:
    """Firecracker-specific configuration settings."""
    binary_path: str = "firecracker"
    socket_dir: str = "/tmp"
    log_dir: str = "logs"

    def __post_init__(self):
        """Validate Firecracker configuration."""
        self.socket_dir = Path(self.socket_dir)
        self.log_dir = Path(self.log_dir)


@dataclass
class NetworkConfig:
    """Network configuration settings."""
    tap_prefix: str = "tap"
    ip_forward: bool = True
    cleanup_on_exit: bool = True

    def __post_init__(self):
        """Validate network configuration."""
        if not self.tap_prefix.isalnum():
            raise ValueError("TAP prefix must be alphanumeric")
        if len(self.tap_prefix) > 10:
            raise ValueError("TAP prefix must be 10 characters or less")


@dataclass
class TasksConfig:
    """Task processing configuration settings."""
    default_timeout: int = 60
    max_retries: int = 3
    cleanup_temp_files: bool = True

    def __post_init__(self):
        """Validate task configuration."""
        if self.default_timeout < 10:
            raise ValueError("Default timeout must be at least 10 seconds")
        if self.max_retries < 0 or self.max_retries > 10:
            raise ValueError("Max retries must be between 0 and 10")


@dataclass
class ResultsConfig:
    """Results storage configuration settings."""
    save_json: bool = True
    save_code: bool = True
    filename_template: str = "{vm_id}_{task_description}"
    max_filename_length: int = 50

    def __post_init__(self):
        """Validate results configuration."""
        if self.max_filename_length < 10 or self.max_filename_length > 200:
            raise ValueError("Max filename length must be between 10 and 200")
        
        # Validate template has required placeholders
        required_placeholders = ["{vm_id}"]
        for placeholder in required_placeholders:
            if placeholder not in self.filename_template:
                raise ValueError(f"Filename template must contain {placeholder}")


@dataclass
class SecurityConfig:
    """Security configuration settings (for future enhancements)."""
    enable_selinux: bool = False
    restrict_network: bool = False
    enable_audit: bool = True


@dataclass
class FirecrackerOrchestratorConfig:
    """Complete configuration for Firecracker OpenAI Code Generator."""
    vm: VMConfig = field(default_factory=VMConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    firecracker: FirecrackerConfig = field(default_factory=FirecrackerConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    results: ResultsConfig = field(default_factory=ResultsConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def __post_init__(self):
        """Perform cross-section validation."""
        # Ensure VM timeout is compatible with task timeout
        if self.vm.timeout > self.tasks.default_timeout:
            raise ValueError("VM timeout should not exceed default task timeout")
        
        # Ensure directories will be created if they don't exist
        self._ensure_directories()

    def _ensure_directories(self):
        """Create required directories if they don't exist."""
        directories = [
            self.paths.shared,
            self.paths.results,
            self.firecracker.log_dir,
        ]
        
        for directory in directories:
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
            except PermissionError:
                # Don't fail on permission errors during validation
                # This will be handled at runtime
                pass

    def get_openai_api_key(self) -> str:
        """Get OpenAI API key from environment variable."""
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is required. "
                "Set it with: export OPENAI_API_KEY='your-key-here'"
            )
        if not api_key.startswith('sk-'):
            raise ValueError("Invalid OpenAI API key format")
        return api_key


def validate_config(config: Dict[str, Any]) -> FirecrackerOrchestratorConfig:
    """
    Validate configuration dictionary and return typed config object.
    
    Args:
        config: Configuration dictionary from Hydra/OmegaConf
        
    Returns:
        FirecrackerOrchestratorConfig: Validated configuration object
        
    Raises:
        ValueError: If configuration validation fails
    """
    try:
        # Create config object from dictionary (Hydra will handle the conversion)
        validated_config = FirecrackerOrchestratorConfig(**config)
        return validated_config
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}")