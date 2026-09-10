"""Model configuration and context-length resolution.

Extracted from call_llm.py to break the circular dependency between
call_llm ↔ token_utils. Both modules now import from this one instead
of from each other.
"""

import os

import requests


def get_llm_provider() -> str | None:
    """Determine the LLM provider from environment variables."""
    provider = os.getenv("LLM_PROVIDER")
    if not provider and (os.getenv("GEMINI_PROJECT_ID") or os.getenv("GEMINI_API_KEY")):
        provider = "GEMINI"
    return provider


# Cache for OpenRouter model list to avoid repeated API calls
_openrouter_models_cache = None


def _get_openrouter_model_info(model_id: str) -> dict | None:
    """Fetch info for a specific model from the OpenRouter model catalog."""
    global _openrouter_models_cache
    if _openrouter_models_cache is None:
        try:
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            _openrouter_models_cache = resp.json().get("data", [])
        except Exception as e:
            from utils.output import emit_raw

            emit_raw("WARNING", f"Failed to fetch OpenRouter model info: {e}", dest="LOG")
            _openrouter_models_cache = []

    return next((m for m in _openrouter_models_cache if m.get("id") == model_id), None)


def get_model_context_length(endpoint_url: str, model_name: str, api_key: str = "") -> int:
    """
    Fetch the maximum context length of a model based on the endpoint.
    If endpoint is Gemini API, safely default to 1,000,000 tokens.
    If endpoint is openrouter.ai, make GET to /api/v1/models and extract.
    Default to 100,000.
    """
    default_limit = 100000
    try:
        if not endpoint_url:
            return default_limit

        if "generativelanguage.googleapis.com" in endpoint_url or "gemini" in model_name.lower():
            # Safely default to 1M tokens for Gemini models
            return 1000000

        if "openrouter.ai" in endpoint_url:
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            data = resp.json().get("data", [])
            for m in data:
                if m.get("id") == model_name:
                    return m.get("context_length", default_limit)
    except Exception as e:
        from utils.output import emit

        emit("WARN_CONTEXT_LENGTH_FETCH", model=model_name, endpoint=endpoint_url, error=str(e))

    return default_limit
