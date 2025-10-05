#!/usr/bin/env python3
"""
Configuration Manager for Firecracker OpenAI Code Generator

Provides centralized configuration management using Hydra and OmegaConf frameworks.
Handles configuration validation, environment-specific settings, and dynamic overrides.

Features:
- YAML-based hierarchical configuration files
- Type-safe configuration validation with dataclasses
- Environment-specific configuration profiles (dev, staging, production)
- Command-line parameter overrides with nested dot notation
- Configuration schema validation with helpful error messages

Dependencies:
- hydra-core: Configuration management framework by Facebook
- omegaconf: Configuration objects with validation
- dataclasses: Type-safe configuration schemas
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
import os

import hydra
from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from omegaconf import DictConfig, OmegaConf, ValidationError
from dataclasses import is_dataclass

# Import configuration schemas
from config.schema import FirecrackerOrchestratorConfig


class ConfigManager:
    """Centralized configuration management using Hydra and OmegaConf frameworks.
    
    Manages Hydra configuration lifecycle, validation, and environment-specific
    settings for the Firecracker orchestration system. Provides type-safe
    configuration loading with comprehensive validation.
    
    Attributes:
        config_dir (Path): Directory containing configuration files
        config (DictConfig): Currently loaded configuration
        schema_class: Configuration schema class for validation
        
    Example:
        config_manager = ConfigManager()
        config = config_manager.load_config("default", ["vm.memory_mb=1024"])
        config_manager.validate_config(config)
    """
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize the configuration manager.
        
        Args:
            config_dir (Path, optional): Directory containing config files.
                                       Defaults to ./config/
        """
        if config_dir is None:
            config_dir = Path(__file__).parent / "config"
        
        self.config_dir = config_dir
        self.config: Optional[DictConfig] = None
        self.schema_class = FirecrackerOrchestratorConfig
        
    def load_config(self, 
                   config_name: str = "default", 
                   overrides: Optional[List[str]] = None) -> DictConfig:
        """Load configuration from YAML files with optional overrides.
        
        Loads the base configuration and applies any command-line overrides.
        Supports environment-specific configurations (development, production, etc.)
        and nested parameter overrides.
        
        Args:
            config_name (str): Name of the configuration file to load
            overrides (List[str], optional): Command-line parameter overrides
                                           in dot notation (e.g., "vm.memory_mb=1024")
        
        Returns:
            DictConfig: Loaded and validated configuration object
            
        Raises:
            ConfigurationError: If configuration files are not found or invalid
            ValidationError: If configuration values fail validation
            
        Examples:
            # Load default configuration
            config = manager.load_config("default")
            
            # Load development configuration with overrides
            config = manager.load_config("development", 
                                       ["vm.memory_mb=2048", "logging.level=DEBUG"])
        """
        if overrides is None:
            overrides = []
            
        # Clear any existing Hydra global state
        if GlobalHydra().is_initialized():
            GlobalHydra.instance().clear()
        
        # Initialize Hydra with config directory
        config_dir_absolute = self.config_dir.resolve()
        
        try:
            with initialize_config_dir(
                config_dir=str(config_dir_absolute),
                version_base=None
            ):
                # Compose configuration with overrides
                self.config = compose(
                    config_name=config_name,
                    overrides=overrides
                )
                
                # Validate the loaded configuration
                self.validate_config(self.config)
                
                return self.config
                
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")
    
    def validate_config(self, config: DictConfig) -> None:
        """Validate configuration against schema with comprehensive error reporting.
        
        Performs type checking and business logic validation using dataclass
        schemas. Provides detailed error messages for configuration issues.
        
        Args:
            config (DictConfig): Configuration object to validate
            
        Raises:
            ValidationError: If configuration validation fails with detailed messages
            
        Example:
            try:
                config_manager.validate_config(config)
            except ValidationError as e:
                print(f"Configuration error: {e}")
        """
        try:
            # Convert OmegaConf to structured config for validation
            structured_config = OmegaConf.structured(self.schema_class)
            
            # Merge with loaded config to validate
            validated_config = OmegaConf.merge(structured_config, config)
            
            # Additional business logic validation
            self._validate_paths(validated_config)
            self._validate_network_settings(validated_config)
            self._validate_resource_limits(validated_config)
            
        except ValidationError as e:
            raise ValidationError(f"Configuration validation failed: {e}")
        except Exception as e:
            raise ConfigurationError(f"Unexpected validation error: {e}")
    
    def _validate_paths(self, config: DictConfig) -> None:
        """Validate path configurations and create directories if needed.
        
        Args:
            config (DictConfig): Configuration to validate
        """
        paths = config.paths
        
        # Validate ubuntu_images directory exists for VM operations
        ubuntu_images_path = Path(paths.ubuntu_images)
        if not ubuntu_images_path.exists():
            raise ValidationError(
                f"Ubuntu images directory not found: {ubuntu_images_path}. "
                f"Run setup_vm_images_ubuntu.sh first."
            )
        
        # Check for required VM image files
        kernel_path = ubuntu_images_path / "vmlinux.bin"
        rootfs_path = ubuntu_images_path / "ubuntu-rootfs.ext4"
        
        if not kernel_path.exists():
            raise ValidationError(f"VM kernel not found: {kernel_path}")
        if not rootfs_path.exists():
            raise ValidationError(f"VM rootfs not found: {rootfs_path}")
    
    def _validate_network_settings(self, config: DictConfig) -> None:
        """Validate network configuration settings.
        
        Args:
            config (DictConfig): Configuration to validate
        """
        import ipaddress
        
        try:
            # Validate CIDR format
            network = ipaddress.IPv4Network(config.vm.network_cidr, strict=False)
            
            # Ensure it's a private network
            if not network.is_private:
                raise ValidationError(f"VM network must be private: {config.vm.network_cidr}")
                
        except ipaddress.AddressValueError:
            raise ValidationError(f"Invalid CIDR format: {config.vm.network_cidr}")
    
    def _validate_resource_limits(self, config: DictConfig) -> None:
        """Validate resource limit configurations.
        
        Args:
            config (DictConfig): Configuration to validate
        """
        vm_config = config.vm
        
        # Check memory limits
        if vm_config.memory_mb > 8192:
            import warnings
            warnings.warn(f"High memory allocation: {vm_config.memory_mb}MB may impact performance")
        
        # Check timeout settings
        if vm_config.timeout < vm_config.boot_timeout:
            raise ValidationError("VM timeout must be greater than boot timeout")
    
    def merge_environment_config(self, config: DictConfig, env: str) -> DictConfig:
        """Merge environment-specific configuration overrides.
        
        Loads environment-specific configuration files and merges them with
        the base configuration. Supports development, staging, production, etc.
        
        Args:
            config (DictConfig): Base configuration
            env (str): Environment name (development, production, etc.)
            
        Returns:
            DictConfig: Merged configuration with environment overrides
            
        Example:
            dev_config = manager.merge_environment_config(base_config, "development")
        """
        env_config_path = self.config_dir / f"{env}.yaml"
        
        if env_config_path.exists():
            env_config = OmegaConf.load(env_config_path)
            merged_config = OmegaConf.merge(config, env_config)
            return merged_config
        
        return config
    
    def get_config_summary(self, config: DictConfig) -> Dict[str, Any]:
        """Get a summary of current configuration for logging/debugging.
        
        Args:
            config (DictConfig): Configuration to summarize
            
        Returns:
            Dict[str, Any]: Configuration summary with key settings
        """
        return {
            "vm_memory_mb": config.vm.memory_mb,
            "vm_vcpus": config.vm.vcpus,
            "vm_timeout": config.vm.timeout,
            "network_cidr": config.vm.network_cidr,
            "openai_model": config.openai.model,
            "logging_level": config.logging.level,
            "logging_format": config.logging.format,
            "paths_ubuntu_images": str(config.paths.ubuntu_images),
            "paths_results": str(config.paths.results)
        }
    
    def save_effective_config(self, config: DictConfig, output_path: Path) -> None:
        """Save the effective configuration to a file for debugging.
        
        Args:
            config (DictConfig): Configuration to save
            output_path (Path): Output file path
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            OmegaConf.save(config, f)
    
    @staticmethod
    def create_override_list(overrides_dict: Dict[str, Any]) -> List[str]:
        """Convert dictionary of overrides to Hydra override list format.
        
        Args:
            overrides_dict (Dict[str, Any]): Dictionary of parameter overrides
            
        Returns:
            List[str]: List of override strings in dot notation
            
        Example:
            overrides = ConfigManager.create_override_list({
                "vm.memory_mb": 2048,
                "logging.level": "DEBUG"
            })
            # Returns: ["vm.memory_mb=2048", "logging.level=DEBUG"]
        """
        override_list = []
        
        def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> None:
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else key
                
                if isinstance(value, dict):
                    _flatten_dict(value, full_key)
                else:
                    override_list.append(f"{full_key}={value}")
        
        _flatten_dict(overrides_dict)
        return override_list


class ConfigurationError(Exception):
    """Exception raised for configuration-related errors."""
    pass


# Global configuration manager instance
_config_manager = ConfigManager()

def load_config(config_name: str = "default", 
               overrides: Optional[List[str]] = None) -> DictConfig:
    """Load configuration using global ConfigManager instance.
    
    Convenience function for loading configuration that maintains backward
    compatibility with existing code.
    
    Args:
        config_name (str): Name of configuration file to load
        overrides (List[str], optional): Command-line overrides
        
    Returns:
        DictConfig: Loaded configuration object
    """
    return _config_manager.load_config(config_name, overrides)

def validate_config(config: DictConfig) -> None:
    """Validate configuration using global ConfigManager instance.
    
    Args:
        config (DictConfig): Configuration to validate
    """
    _config_manager.validate_config(config)