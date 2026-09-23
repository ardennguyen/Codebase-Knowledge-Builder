import hashlib
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

# Self-test runs as a script (`python utils/call_llm.py`) as well as a module (`python -m utils.call_llm`):
# as a script, the repo root is not on sys.path, so `utils.*` imports would fail.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file
load_dotenv()


# In-memory cache singleton — loaded once on first access, avoids
# re-parsing the (potentially hundreds of MB) JSON file on every call_llm().
# Keys are sha256(provider | model | thinking level | prompt): responses are scoped to
# the model that produced them, and full prompts are no longer stored on disk.
# LEGACY_CACHE_FILE (prompt-keyed, pre-v2) is never read: notice_legacy_cache() points out a
# leftover copy at startup, and --cleanup removes both files.
cache_file = "llm_cache_v2.json"
LEGACY_CACHE_FILE = "llm_cache.json"
_cache = None


def load_cache():
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(cache_file, encoding="utf-8") as f:
            _cache = json.load(f)
        from utils.output import emit

        emit("CACHE_LOADED", count=f"{len(_cache):,}", file=cache_file)
    except FileNotFoundError:
        _cache = {}
    except (json.JSONDecodeError, OSError) as e:
        from utils.output import emit, emit_raw

        emit("WARN_CACHE_LOAD_FAIL")
        emit_raw("WARNING", f"Cache load error: {e}", dest="LOG")
        _cache = {}
    return _cache


def save_cache(cache):
    global _cache
    _cache = cache
    # Write to a temp file and atomically replace, so an interrupted run never leaves a truncated cache.
    tmp_path = f"{cache_file}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp_path, cache_file)
    except (OSError, TypeError) as e:
        from utils.output import emit, emit_raw

        emit("WARN_CACHE_SAVE_FAIL")
        emit_raw("WARNING", f"Cache save error: {e}", dest="LOG")


def notice_legacy_cache() -> None:
    """Point out a leftover pre-v2 cache file: it is never read, so it only takes disk space."""
    try:
        size = os.path.getsize(LEGACY_CACHE_FILE)
    except OSError:
        return
    from utils.output import emit

    emit("CACHE_LEGACY_FOUND", file=LEGACY_CACHE_FILE, size=f"{size / 1_048_576:,.1f}", current=cache_file)


def _cache_key(prompt: str, provider: str, model: str, thinking_level: str | None) -> str:
    scope = f"{provider}|{model}|{(thinking_level or 'default').lower()}\n"
    return hashlib.sha256((scope + prompt).encode("utf-8")).hexdigest()


from utils.llm_common import LLMRefusalError, previous_refusal, remember_refusal, request_key
from utils.llm_config import (
    GEMINI_THINKING_BUDGETS,  # noqa: F401 — re-exported for callers of the old location
    get_llm_provider,
    get_model_context_length,  # noqa: F401
    rejects_sampling_params,
    resolve_llm_settings,
)
from utils.thinking import clamp_level as _clamp_level


def _call_llm_provider(prompt: str, thinking_level: str | None = None) -> str:
    """
    Call a generic OpenAI-compatible provider (OLLAMA and other endpoints; OPENROUTER uses
    utils/llm_openrouter.py) based on environment variables.
    Environment variables:
    - LLM_PROVIDER: e.g. "OLLAMA"
    - <provider>_MODEL: Model name (e.g., OLLAMA_MODEL, OPENROUTER_MODEL)
    - <provider>_BASE_URL: Base URL without endpoint (e.g., OLLAMA_BASE_URL, OPENROUTER_BASE_URL)
    - <provider>_API_KEY: API key (e.g., OLLAMA_API_KEY, OPENROUTER_API_KEY; optional for providers that don't require it)
    The endpoint /v1/chat/completions will be appended to the base URL.
    """

    # Read the provider from environment variable
    provider = get_llm_provider()
    if not provider:
        raise ValueError("LLM_PROVIDER environment variable is required")

    # Construct the names of the other environment variables
    model_var = f"{provider}_MODEL"
    base_url_var = f"{provider}_BASE_URL"
    api_key_var = f"{provider}_API_KEY"

    # Read the provider-specific variables
    model = os.environ.get(model_var)
    base_url = os.environ.get(base_url_var)
    api_key = os.environ.get(api_key_var, "")  # API key is optional, default to empty string

    # Validate required variables
    if not model:
        raise ValueError(f"{model_var} environment variable is required")
    if not base_url:
        raise ValueError(f"{base_url_var} environment variable is required")

    # Append the endpoint to the base URL
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Configure headers and payload based on provider
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:  # Only add Authorization header if API key is provided
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }

    if provider == "OLLAMA" and thinking_level:
        # Ollama reasoning models accept low/medium/high; xhigh/max clamp to high.
        # Some Ollama SDKs / API versions look for `think`, others look for standard `reasoning_effort`
        effort = _clamp_level(thinking_level.lower(), ["low", "medium", "high"]) or "medium"
        payload["think"] = effort
        payload["reasoning_effort"] = effort
        payload["temperature"] = 1.0

    if rejects_sampling_params(model):
        # Claude Opus 4.7+ / Opus 5.x / Sonnet 5 / Fable reject sampling parameters (400).
        payload.pop("temperature", None)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(10, 300))
        response.raise_for_status()  # HTTP status first: an HTML 502 page must not look like a JSON bug
        try:
            response_json = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            from utils.output import emit

            emit(
                "WARN_INVALID_JSON",
                status_code=response.status_code,
                preview=response.text[:200].strip(),
            )
            raise ValueError(f"Provider returned invalid JSON. Status Code: {response.status_code}") from None

        # Defensive check: API may return 200 with error/rate-limit payload missing 'choices'
        if "choices" not in response_json or not response_json["choices"]:
            error_detail = response_json.get("error", response_json)
            from utils.output import emit

            emit("WARN_API_NO_CHOICES", detail=str(error_detail))
            raise RuntimeError(f"API response missing 'choices' key. Response: {error_detail}")

        usage = response_json.get("usage") or {}
        from utils.llm_common import record_usage

        record_usage(provider, model, input_tokens=usage.get("prompt_tokens") or 0, output_tokens=usage.get("completion_tokens") or 0, cost=None)
        choice = response_json["choices"][0]
        text = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "length":
            from utils.llm_common import TruncatedResponse

            return TruncatedResponse(text)
        return text
    except requests.exceptions.HTTPError as e:
        error_message = f"HTTP error occurred: {e}"
        try:
            error_details = response.json().get("error", "No additional details")
            error_message += f" (Details: {error_details})"
        except Exception:
            pass
        raise Exception(error_message) from e
    except requests.exceptions.ConnectionError as e:
        raise Exception(f"Failed to connect to {provider} API. Check your network connection.") from e
    except requests.exceptions.Timeout as e:
        raise Exception(f"Request to {provider} API timed out.") from e
    except requests.exceptions.RequestException as e:
        raise Exception(f"An error occurred while making the request to {provider}: {e}") from e
    except ValueError as e:
        raise Exception(f"Failed to parse response as JSON from {provider}. The server might have returned an invalid response.") from e


def _call_llm_anthropic(prompt: str, thinking_level: str | None = None) -> str:
    try:
        from utils.llm_anthropic import call_anthropic
    except ImportError as e:
        raise ImportError("LLM_PROVIDER=ANTHROPIC requires the 'anthropic' package: pip install -r requirements.txt") from e
    return call_anthropic(prompt, thinking_level=thinking_level)


def _call_llm_gemini(prompt: str, thinking_level: str | None = None) -> str:
    try:
        from utils.llm_gemini import call_gemini
    except ImportError as e:
        raise ImportError("LLM_PROVIDER=GEMINI requires the 'google-genai' package (>=1.56): pip install -r requirements.txt") from e
    return call_gemini(prompt, thinking_level=thinking_level)


def _call_llm_openrouter(prompt: str, thinking_level: str | None = None) -> str:
    from utils.llm_openrouter import call_openrouter

    return call_openrouter(prompt, thinking_level=thinking_level)


# Provider and model come from resolve_llm_settings(): LLM_PROVIDER, or Gemini when only Gemini
# credentials are set (default gemini-3.8-flash; Claude defaults to claude-sonnet-5).
def call_llm(prompt: str, use_cache: bool = True, thinking_level: str | None = None) -> str:
    from utils.output import emit, emit_raw
    from utils.token_utils import count_tokens

    provider, model, _, _ = resolve_llm_settings()
    prompt_tokens = count_tokens(prompt)

    emit_raw("DEBUG", f"{'=' * 80}", dest="LOG")
    emit_raw(
        "DEBUG",
        f"LLM CALL START | provider={provider} | model={model} | thinking={thinking_level} | cache={'enabled' if use_cache else 'disabled'} | prompt_tokens={prompt_tokens:,}",
        dest="LOG",
    )
    emit_raw("DEBUG", f"PROMPT:\n{prompt}", dest="LOG")

    # Check cache if enabled
    key = _cache_key(prompt, provider, model, thinking_level)
    if use_cache:
        cache = load_cache()
        if key in cache:
            cached_response = cache[key]
            emit("CACHE_HIT", chars=f"{len(cached_response):,}")
            emit_raw("DEBUG", f"RESPONSE (cached):\n{cached_response}", dest="LOG")
            emit_raw("DEBUG", "LLM CALL END | result=cache_hit", dest="LOG")
            return cached_response
        emit("CACHE_MISS")

    # A request the provider already declined this run is declined again: do not re-send it on
    # node retries (rate limits, billed partial output). The node retry still sees the error.
    refusal_key = request_key(provider, model, thinking_level, prompt)
    refused = previous_refusal(refusal_key)
    if refused is not None:
        emit_raw("DEBUG", "LLM CALL END | result=refused_before (not re-sent)", dest="LOG")
        raise refused

    # Make the actual LLM call
    start_time = time.time()
    emit_raw("DEBUG", f"API CALL | sending request to {provider}...", dest="LOG")

    try:
        if provider == "GEMINI":
            response_text = _call_llm_gemini(prompt, thinking_level=thinking_level)
        elif provider == "ANTHROPIC":
            response_text = _call_llm_anthropic(prompt, thinking_level=thinking_level)
        elif provider == "OPENROUTER":
            response_text = _call_llm_openrouter(prompt, thinking_level=thinking_level)
        else:  # generic method using a URL that is OpenAI compatible API (Ollama, ...)
            response_text = _call_llm_provider(prompt, thinking_level=thinking_level)
    except LLMRefusalError as e:
        if not e.retryable:
            remember_refusal(refusal_key, e)
        raise

    elapsed = time.time() - start_time
    emit_raw("DEBUG", f"API CALL COMPLETE | elapsed={elapsed:.1f}s | response_chars={len(response_text):,}", dest="LOG")
    emit_raw("DEBUG", f"RESPONSE:\n{response_text}", dest="LOG")

    # Update cache if enabled. Empty and truncated responses (llm_common.TruncatedResponse)
    # are never cached — they would be replayed on every later run.
    if use_cache and response_text and not getattr(response_text, "truncated", False):
        cache = load_cache()
        cache[key] = response_text
        save_cache(cache)
        emit_raw("DEBUG", "CACHE WRITE | saved response to cache", dest="LOG")

    emit_raw("DEBUG", f"LLM CALL END | result=success | elapsed={elapsed:.1f}s", dest="LOG")
    return response_text


if __name__ == "__main__":
    from utils.llm_config import check_llm_auth
    from utils.output import emit
    from utils.output import init as init_output

    init_output(language="english", use_cache=False)
    # Same preflight as main.py: SDK installed, credentials present (API key / `ant auth login` / Vertex ADC).
    if not check_llm_auth():
        sys.exit(1)
    notice_legacy_cache()

    test_prompt = "Hello, how are you?"

    emit("SELFTEST_LLM_CALL")
    response1 = call_llm(test_prompt, use_cache=False)
    emit("SELFTEST_LLM_RESPONSE", response=response1)
