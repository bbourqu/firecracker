"""Resolve provider URLs from environment, config, or sensible defaults.

Provides helpers to resolve a provider endpoint and validate required providers.
"""
import os
from typing import Optional, Dict, Any


DEFAULTS = {
    'ollama': 'http://localhost:11434/api/generate',
    'openai': 'https://api.openai.com/v1/completions'
}


def resolve_provider_url(provider: str, config: Optional[Any] = None) -> Optional[str]:
    """Return the resolved URL for provider.

    Precedence: ENV < config.providers.<provider>.url < DEFAULT
    """
    env_key = f"{provider.upper()}_URL"
    env_val = os.getenv(env_key)
    if env_val:
        return env_val

    # try config.providers.<provider>.url
    if config is not None:
        try:
            prov = getattr(config.providers, provider)
            url = getattr(prov, 'url', None)
            if url:
                return url
        except Exception:
            pass

    # fallback default
    return DEFAULTS.get(provider)


def validate_providers(config: Optional[Any], required: Optional[Dict[str, bool]] = None) -> Dict[str, bool]:
    """Validate presence of provider URLs for required providers.

    Args:
      config: optional config object used for resolution
      required: iterable of provider names (list or dict keys) to validate

    Returns:
      dict mapping provider->True/False indicating whether a URL was found
    """
    if not required:
        return {}
    result = {}
    for p in required:
        url = resolve_provider_url(p, config)
        result[p] = bool(url)
    return result


def ensure_providers(config: Optional[Any], required) -> None:
    """Raise ValueError if any required provider lacks a resolved URL."""
    missing = [p for p, ok in validate_providers(config, required).items() if not ok]
    if missing:
        raise ValueError(f"Missing provider URL for: {', '.join(missing)}")
