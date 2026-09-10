import json
import os
import time

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables from .env file
load_dotenv()


# In-memory cache singleton — loaded once on first access, avoids
# re-parsing the (potentially hundreds of MB) JSON file on every call_llm().
cache_file = "llm_cache.json"
_cache = None


def load_cache():
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(cache_file) as f:
            _cache = json.load(f)
        from utils.output import emit

        emit("CACHE_LOADED", count=f"{len(_cache):,}", file=cache_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        from utils.output import emit, emit_raw

        emit("WARN_CACHE_LOAD_FAIL")
        emit_raw("WARNING", f"Cache load error: {e}", dest="LOG")
        _cache = {}
    return _cache


def save_cache(cache):
    global _cache
    _cache = cache
    try:
        with open(cache_file, "w") as f:
            json.dump(cache, f)
    except (OSError, TypeError) as e:
        from utils.output import emit, emit_raw

        emit("WARN_CACHE_SAVE_FAIL")
        emit_raw("WARNING", f"Cache save error: {e}", dest="LOG")


from utils.llm_config import _get_openrouter_model_info, get_llm_provider, get_model_context_length  # noqa: F401


def _call_llm_provider(prompt: str, thinking_level: str | None = None) -> str:
    """
    Call an LLM provider based on environment variables.
    Environment variables:
    - LLM_PROVIDER: "OLLAMA" or "OPENROUTER"
    - <provider>_MODEL: Model name (e.g., OLLAMA_MODEL, OPENROUTER_MODEL)
    - <provider>_BASE_URL: Base URL without endpoint (e.g., OLLAMA_BASE_URL, OPENROUTER_BASE_URL)
    - <provider>_API_KEY: API key (e.g., OLLAMA_API_KEY, OPENROUTER_API_KEY; optional for providers that don't require it)
    The endpoint /v1/chat/completions will be appended to the base URL.
    """

    # Read the provider from environment variable
    provider = os.environ.get("LLM_PROVIDER")
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

    if provider == "OPENROUTER" and thinking_level:
        model_info = _get_openrouter_model_info(model)
        if model_info and "reasoning" in model_info:
            supported_efforts = model_info["reasoning"].get("supported_efforts", [])
            if thinking_level.lower() in supported_efforts:
                payload["reasoning"] = {"effort": thinking_level.lower()}
                payload["temperature"] = 1.0  # Required for many reasoning models
            else:
                from utils.output import emit

                emit("WARN_THINKING_LEVEL_INVALID", level=thinking_level, model=model, supported=str(supported_efforts))
        else:
            from utils.output import emit

            emit("WARN_THINKING_NOT_SUPPORTED", model=model)

    elif provider == "OLLAMA" and thinking_level:
        # Some Ollama SDKs / API versions look for `think`, others look for standard `reasoning_effort`
        payload["think"] = thinking_level.lower()
        payload["reasoning_effort"] = thinking_level.lower()
        payload["temperature"] = 1.0

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(10, 300))
        try:
            response_json = response.json()  # Log the response
        except (ValueError, requests.exceptions.JSONDecodeError):
            from utils.output import emit

            emit(
                "WARN_INVALID_JSON",
                status_code=response.status_code,
                preview=response.text[:200].strip(),
            )
            raise ValueError(f"Provider returned invalid JSON. Status Code: {response.status_code}") from None
        response.raise_for_status()

        # Defensive check: API may return 200 with error/rate-limit payload missing 'choices'
        if "choices" not in response_json or not response_json["choices"]:
            error_detail = response_json.get("error", response_json)
            from utils.output import emit

            emit("WARN_API_NO_CHOICES", detail=str(error_detail))
            raise ValueError(f"API response missing 'choices' key. Response: {error_detail}")

        return response_json["choices"][0]["message"]["content"]
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


# By default, we use Google Gemini 3.7 flash, as it shows great performance for code understanding
def call_llm(prompt: str, use_cache: bool = True, thinking_level: str | None = None) -> str:
    from utils.output import emit, emit_raw
    from utils.token_utils import count_tokens

    provider = get_llm_provider()
    model = os.environ.get(f"{provider}_MODEL", os.environ.get("GEMINI_MODEL", "unknown"))
    prompt_tokens = count_tokens(prompt)

    emit_raw("DEBUG", f"{'=' * 80}", dest="LOG")
    emit_raw(
        "DEBUG",
        f"LLM CALL START | provider={provider} | model={model} | thinking={thinking_level} | cache={'enabled' if use_cache else 'disabled'} | prompt_tokens={prompt_tokens:,}",
        dest="LOG",
    )
    emit_raw("DEBUG", f"PROMPT:\n{prompt}", dest="LOG")

    # Check cache if enabled
    if use_cache:
        cache = load_cache()
        if prompt in cache:
            cached_response = cache[prompt]
            emit("CACHE_HIT", chars=f"{len(cached_response):,}")
            emit_raw("DEBUG", f"RESPONSE (cached):\n{cached_response}", dest="LOG")
            emit_raw("DEBUG", "LLM CALL END | result=cache_hit", dest="LOG")
            return cached_response
        emit("CACHE_MISS")

    # Make the actual LLM call
    start_time = time.time()
    emit_raw("DEBUG", f"API CALL | sending request to {provider}...", dest="LOG")

    if provider == "GEMINI":
        response_text = _call_llm_gemini(prompt, thinking_level=thinking_level)
    else:  # generic method using a URL that is OpenAI compatible API (Ollama, ...)
        response_text = _call_llm_provider(prompt, thinking_level=thinking_level)

    elapsed = time.time() - start_time
    emit_raw("DEBUG", f"API CALL COMPLETE | elapsed={elapsed:.1f}s | response_chars={len(response_text):,}", dest="LOG")
    emit_raw("DEBUG", f"RESPONSE:\n{response_text}", dest="LOG")

    # Update cache if enabled
    if use_cache:
        cache = load_cache()
        cache[prompt] = response_text
        save_cache(cache)
        emit_raw("DEBUG", "CACHE WRITE | saved response to cache", dest="LOG")

    emit_raw("DEBUG", f"LLM CALL END | result=success | elapsed={elapsed:.1f}s", dest="LOG")
    return response_text


def _call_llm_gemini(prompt: str, thinking_level: str | None = None) -> str:
    if os.getenv("GEMINI_PROJECT_ID"):
        client = genai.Client(vertexai=True, project=os.getenv("GEMINI_PROJECT_ID"), location=os.getenv("GEMINI_LOCATION", "us-central1"))
    elif os.getenv("GEMINI_API_KEY"):
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    else:
        raise ValueError("Either GEMINI_PROJECT_ID or GEMINI_API_KEY must be set in the environment")
    model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

    kwargs = {"model": model, "contents": [prompt]}

    if thinking_level:
        # Map string levels to budgets for the installed SDK version
        budget_map = {"low": 1024, "medium": 4096, "high": 8192}
        budget = budget_map.get(thinking_level.lower(), 4096)
        from utils.output import emit_raw

        emit_raw("DEBUG", f"Gemini thinking config | budget={budget}", dest="LOG")
        thinking_config = types.ThinkingConfig(include_thoughts=True, thinking_budget=budget)
        kwargs["config"] = types.GenerateContentConfig(thinking_config=thinking_config)

    response = client.models.generate_content(**kwargs)

    response_text = ""
    # Extract only text parts to avoid "non-text parts: ['thought_signature']" warnings
    if response.candidates and response.candidates[0].content.parts:
        text_parts = [part.text for part in response.candidates[0].content.parts if part.text is not None]
        response_text = "".join(text_parts)

    if not response_text:
        from utils.output import emit_raw

        emit_raw("WARNING", "Gemini response contained no text parts", dest="LOG")

    return response_text


if __name__ == "__main__":
    from utils.output import emit

    test_prompt = "Hello, how are you?"

    emit("SELFTEST_LLM_CALL")
    response1 = call_llm(test_prompt, use_cache=False)
    emit("SELFTEST_LLM_RESPONSE", response=response1)
