"""Provider dispatcher that routes provider requests to provider-specific clients
or falls back to a generic HTTP POST when needed.
"""
from typing import Dict, Any, Optional
import os
import logging

from provider_client import post_with_retries

log = logging.getLogger(__name__)


def call_provider(provider: str, url: Optional[str], model: Optional[str], prompt: str, timeout: int = 30) -> Dict[str, Any]:
    """Call the named provider.

    - For 'ollama' we POST to the provided URL (which may be a full URL or host) with {model,prompt}.
    - For 'openai' we prefer the OPENAI_API_KEY env var and the `providers.openai_client` helper if available.
    - Otherwise, fall back to a generic POST to `url` using `provider_client.post_with_retries`.
    """
    # Local import to avoid circular imports at module import time
    try:
        import providers.ollama as _ollama  # type: ignore
    except Exception:
        _ollama = None

    try:
        import providers.openai_client as _openai  # type: ignore
    except Exception:
        _openai = None

    # helper: ensure URL has a scheme when we need to POST directly
    def _ensure_scheme(u: Optional[str]) -> Optional[str]:
        if not u:
            return None
        if u.startswith('http://') or u.startswith('https://'):
            return u
        return 'http://' + u

    # Ollama: accept either a full URL or host and let the ollama client handle it
    if provider == 'ollama':
        if _ollama is not None:
            try:
                # ollama.generate expects a host (without scheme) in our wrapper; pass as-is
                return _ollama.generate(url or 'localhost:11434', model or 'default', prompt, timeout=timeout)
            except Exception as e:
                log.exception('Ollama client failed: %s', e)
        # fallback (ensure scheme present)
        return post_with_retries(_ensure_scheme(url) or 'http://localhost:11434/api/generate', {'model': model, 'prompt': prompt}, timeout=timeout)

    # OpenAI: prefer the client if API key is available
    if provider == 'openai':
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key and _openai is not None:
            try:
                return _openai.complete(api_key, model or 'gpt-3.5-turbo', prompt, timeout=timeout)
            except Exception as e:
                log.exception('OpenAI client failed: %s', e)
    # fallback to generic POST (ensure scheme)
    return post_with_retries(_ensure_scheme(url) or 'https://api.openai.com/v1/completions', {'model': model, 'prompt': prompt}, timeout=timeout)

    # Generic fallback
    if url:
        resp = post_with_retries(_ensure_scheme(url), {'model': model, 'prompt': prompt}, timeout=timeout)
        return normalize_provider_response(resp)

    raise ValueError(f'No provider URL or client available for provider: {provider}')


def normalize_provider_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize provider responses to a stable minimal shape.

    Returns a dict with at least one of:
      - text: a string with generated text
      - choices: list of raw choices
      - raw: original response
    """
    # Try to coerce into our Pydantic model when available
    try:
        from providers.schema import ProviderResponse
        if isinstance(resp, dict):
            # populate canonical fields
            data = {}
            # choices -> choices
            if 'choices' in resp and isinstance(resp['choices'], list):
                data['choices'] = resp['choices']
                first = resp['choices'][0] if resp['choices'] else None
                if isinstance(first, dict):
                    txt = first.get('text') or first.get('message', {}).get('content')
                    if txt:
                        data['text'] = txt
            # text / output
            if 'text' in resp and isinstance(resp['text'], str):
                data.setdefault('text', resp['text'])
            if 'output' in resp and isinstance(resp['output'], str):
                data.setdefault('text', resp['output'])
            data['raw'] = resp
            pr = ProviderResponse(**data)
            return pr.dict()
        else:
            return {'text': str(resp), 'raw': resp}
    except Exception:
        # fallback to best-effort extraction
        if not isinstance(resp, dict):
            return {'text': str(resp), 'raw': resp}
        if 'choices' in resp and isinstance(resp['choices'], list):
            first = resp['choices'][0]
            txt = first.get('text') or first.get('message', {}).get('content') if isinstance(first, dict) else None
            out = {'choices': resp['choices']}
            if txt:
                out['text'] = txt
            out['raw'] = resp
            return out
        if 'text' in resp and isinstance(resp['text'], str):
            return {'text': resp['text'], 'raw': resp}
        if 'output' in resp and isinstance(resp['output'], str):
            return {'text': resp['output'], 'raw': resp}
        return {'raw': resp}
