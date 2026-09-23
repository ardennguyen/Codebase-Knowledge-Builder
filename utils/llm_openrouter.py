"""OpenRouter provider for call_llm() (OpenAI-compatible chat completions, catalog-driven).

Every per-model decision comes from the OpenRouter model catalog (utils/llm_config.openrouter_model_info),
so any upstream family works without hardcoded tables:
- Thinking: `reasoning.effort`, clamped to the model's `reasoning.supported_efforts` (never 'none',
  which 400s on mandatory-reasoning models). Models with reasoning but no effort list send
  `reasoning.max_tokens` (a thinking budget per level) when the catalog flags `supports_max_tokens`,
  else `effort` — OpenRouter converts it to a budget (e.g. Claude Haiku 4.5, Gemini 2.5, Qwen).
  Reasoning text is excluded from the response unless --debug (it is billed either way).
  Claude 4.6+ maps effort → output_config.effort; Gemini 3.x maps it → thinkingLevel.
- Output: `max_tokens` — reasoning tokens count toward it — from the same per-level table
  token_utils.input_token_budget reserves, capped by top_provider.max_completion_tokens. Omitted for
  a model the catalog does not know (limits unknown; the upstream default applies).
- Sampling: temperature only when the model lists it, it is not a reasoning request, the model does
  not reason by default, and the family does not reject sampling (Claude 4.7+/5.x, Gemini 3.x).
- Streaming SSE (keep-alive ': OPENROUTER PROCESSING' comments are skipped), so long reasoning never
  hits a read timeout; transient HTTP errors (408/429/502/503/524/529) are retried honoring Retry-After.
- finish_reason 'length' → TruncatedResponse (never cached). Model refusals and policy blocks
  (refusal field, native refusal / prohibited_content / blocklist / spii, HTTP 403 moderation or
  refusal) → LLMRefusalError (not re-sent); 'content_filter' / safety / recitation stops →
  LLMRefusalError(retryable=True). 'error' (in a 200 body or mid-stream), and a stream that ends
  without a finish_reason (dropped connection) → exception, so the node retries.
- Usage (prompt / completion / reasoning / cached tokens and the returned USD cost; BYOK requests add
  cost_details.upstream_inference_cost) feeds the run summary.

Environment: OPENROUTER_API_KEY (optional for non-OpenRouter hosts), OPENROUTER_MODEL,
OPENROUTER_BASE_URL (default https://openrouter.ai/api; a trailing /v1 is accepted),
OPENROUTER_MAX_OUTPUT_TOKENS, OPENROUTER_TIMEOUT_SECONDS (max silence between stream events, default 300),
OPENROUTER_TEMPERATURE (default 0.7, non-reasoning requests only), OPENROUTER_APP_URL (opt-in app
attribution: when set, sent as HTTP-Referer with the X-OpenRouter-Title / X-Title headers; unset = no
attribution headers).
"""

import json
import os
import time

import requests

from utils.llm_common import LLMRefusalError, TruncatedResponse, count_event, record_usage, warn_once
from utils.llm_config import (
    CONTEXT_MARGIN,
    openrouter_base_url,
    openrouter_catalog,
    openrouter_model_info,
    openrouter_output_budget,
    rejects_sampling_params,
)
from utils.output import emit, emit_raw, is_debug
from utils.thinking import clamp_level

_RETRYABLE_STATUS = {408, 429, 502, 503, 524, 529}
_MAX_ATTEMPTS = 3
_REFUSAL_NATIVE_REASONS = {"refusal", "safety", "prohibited_content", "recitation", "blocklist", "spii", "content_filter"}
# Upstream stops that repeat for the same input (a model refusal, a policy or term-list block).
_DETERMINISTIC_NATIVE_REASONS = {"refusal", "prohibited_content", "blocklist", "spii"}
_REFUSAL_ERROR_TYPES = {"refusal", "content_policy_violation", "moderation"}
# Thinking budget per level for models that take reasoning.max_tokens but no effort (min 1024).
_REASONING_BUDGETS = {"minimal": 1_024, "low": 2_048, "medium": 8_192, "high": 16_384, "xhigh": 24_576, "max": 32_000}
# OpenRouter app attribution title (tool identity, not user-facing text); sent only when
# OPENROUTER_APP_URL opts in.
_APP_TITLE = "Codebase Knowledge Builder"


def get_model() -> str:
    return os.getenv("OPENROUTER_MODEL", "").strip()


def _read_timeout() -> float:
    try:
        return max(float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "300")), 30.0)
    except ValueError:
        return 300.0


def _reasoning(model: str, info: dict | None, level: str | None, max_tokens: int | None = None) -> tuple[dict | None, str]:
    """(reasoning payload | None, description)."""
    if not level:
        return None, "default"
    level = level.lower()
    exclude = not is_debug()
    if info is None:
        # Catalog unavailable or model unknown: send the level; OpenRouter clamps server-side.
        return {"effort": level, "exclude": exclude}, f"effort={level} (unverified)"
    reasoning = info.get("reasoning")
    if not isinstance(reasoning, dict) and "reasoning" not in (info.get("supported_parameters") or []):
        if warn_once("openrouter_no_reasoning", model):
            emit("WARN_THINKING_NOT_SUPPORTED", model=model)
        return None, "unsupported"
    meta = reasoning if isinstance(reasoning, dict) else {}
    if "supported_efforts" not in meta and meta.get("supports_max_tokens"):
        # Budget-only model: an explicit thinking budget (OpenRouter's effort ratio of a large
        # max_tokens would over-spend). It must stay below max_tokens.
        budget = _REASONING_BUDGETS.get(level, _REASONING_BUDGETS["medium"])
        if max_tokens:
            budget = max(min(budget, max_tokens - 1_024), 1_024)
        return {"max_tokens": budget, "exclude": exclude}, f"reasoning.max_tokens={budget}"
    efforts = meta.get("supported_efforts")
    effort = level
    if efforts:
        effort = clamp_level(level, [e for e in efforts if e != "none"]) or level
        if effort != level and warn_once("openrouter_level", model, level):
            emit("WARN_THINKING_LEVEL_CLAMPED", level=level, effective=effort, model=model)
    return {"effort": effort, "exclude": exclude}, f"effort={effort}"


def _sends_temperature(model: str, info: dict | None, reasoning: dict | None) -> bool:
    if reasoning is not None or rejects_sampling_params(model):
        return False
    if info is None:
        return True
    if "temperature" not in (info.get("supported_parameters") or []):
        return False
    meta = info.get("reasoning") if isinstance(info.get("reasoning"), dict) else {}
    return not (meta.get("mandatory") or meta.get("default_enabled"))


def _max_tokens(model: str, info: dict | None, level: str | None, prompt_tokens: int) -> int | None:
    """Planned max_tokens clamped to the context left after the prompt; None = omit (unknown model)."""
    planned = openrouter_output_budget(model, level)
    context = ((info or {}).get("top_provider") or {}).get("context_length") or (info or {}).get("context_length")
    if planned and context:
        planned = min(planned, max(context - prompt_tokens - CONTEXT_MARGIN, 4_096))
    return planned


def build_payload(prompt: str, model: str, level: str | None, prompt_tokens: int) -> tuple[dict, str]:
    info = openrouter_model_info(model)
    max_tokens = _max_tokens(model, info, level, prompt_tokens)
    reasoning, desc = _reasoning(model, info, level, max_tokens)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if reasoning is not None:
        payload["reasoning"] = reasoning
    if _sends_temperature(model, info, reasoning):
        try:
            payload["temperature"] = float(os.getenv("OPENROUTER_TEMPERATURE", "0.7"))
        except ValueError:
            payload["temperature"] = 0.7
    return payload, desc


def _attribution_headers() -> dict:
    """OpenRouter app attribution (rankings / activity page), opt-in: nothing identifying the tool is
    sent unless OPENROUTER_APP_URL is set. OpenRouter attributes by HTTP-Referer; the title needs it."""
    url = os.getenv("OPENROUTER_APP_URL", "").strip()
    if not url:
        return {}
    return {"HTTP-Referer": url, "X-OpenRouter-Title": _APP_TITLE, "X-Title": _APP_TITLE}  # X-Title: legacy name


def _retry_after(resp) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _error_body(resp) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    err = body.get("error", body) if isinstance(body, dict) else body
    return err if isinstance(err, dict) else {"message": str(err)}


def _error_detail(resp) -> str:
    err = _error_body(resp)
    if not err:
        return resp.text[:300].strip()
    meta = err.get("metadata") or {}
    raw = meta.get("raw") or meta.get("provider_name") or ""
    return f"{err.get('message', err)}" + (f" ({raw})" if raw else "")


def _refusal_category(resp) -> str | None:
    """Category when an HTTP 403 is a moderation / guardrail / upstream refusal, else None."""
    if resp.status_code != 403:
        return None
    err = _error_body(resp)
    meta = err.get("metadata") or {}
    kind = str(err.get("type") or err.get("error_type") or meta.get("error_type") or "").lower()
    if kind in _REFUSAL_ERROR_TYPES:
        return kind
    if meta.get("reasons") or meta.get("flagged_input"):
        reasons = meta.get("reasons") or ["moderation"]
        return ",".join(map(str, reasons)) if isinstance(reasons, list) else str(reasons)
    return None


def _post(url: str, headers: dict, payload: dict):
    """POST with bounded retries on transient failures; returns an open streaming response."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=(15, _read_timeout()))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == _MAX_ATTEMPTS:
                raise RuntimeError(f"OpenRouter request failed after {attempt} attempts: {e}") from e
            time.sleep(2**attempt)
            continue
        if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
            wait = min(_retry_after(resp) or 2**attempt * 2, 60)
            emit_raw("WARNING", f"OpenRouter HTTP {resp.status_code}; retrying in {wait:.0f}s ({_error_detail(resp)})", dest="LOG")
            resp.close()
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            detail, category = _error_detail(resp), _refusal_category(resp)
            resp.close()
            if category:
                model = payload.get("model", "")
                count_event("OPENROUTER", "refusals")
                emit("WARN_LLM_REFUSAL", provider="OpenRouter", model=model, category=category)
                emit_raw("WARNING", f"OpenRouter HTTP 403 refusal: {detail}", dest="LOG")
                raise LLMRefusalError(model, category, provider="OPENROUTER")
            raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {detail}")
        return resp
    raise RuntimeError("OpenRouter request failed")  # unreachable


def _consume(resp) -> dict:
    """Parse the SSE stream: text, reasoning, finish / native finish reason, refusal, usage.

    Lines are split as bytes and decoded one by one: str.splitlines() (used by
    iter_lines(decode_unicode=True)) also breaks on U+2028 / U+0085, which JSON strings may contain raw.
    """
    out = {"text": [], "reasoning": [], "finish": None, "native": None, "refusal": None, "usage": None, "events": 0}
    try:
        if "application/json" in (resp.headers.get("Content-Type") or "").lower():
            # An OpenAI-compatible proxy that ignores stream=true answers with one JSON body.
            _apply_chunk(out, resp.json())
        else:
            for raw_line in resp.iter_lines():
                line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue  # blank separators and ': OPENROUTER PROCESSING' keep-alives
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                _apply_chunk(out, chunk)
    finally:
        resp.close()
    out["text"] = "".join(out["text"])
    out["reasoning"] = "".join(out["reasoning"])
    return out


def _apply_chunk(out: dict, chunk: dict) -> None:
    """Fold one stream chunk (or a whole non-streamed completion) into the _consume result."""
    out["events"] += 1
    if chunk.get("error"):
        err = chunk["error"]
        raise RuntimeError(f"OpenRouter stream error: {err.get('message', err) if isinstance(err, dict) else err}")
    if chunk.get("usage"):
        out["usage"] = chunk["usage"]
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or choice.get("message") or {}
        if delta.get("content"):
            out["text"].append(delta["content"])
        if delta.get("reasoning"):
            out["reasoning"].append(delta["reasoning"])
        if delta.get("refusal"):
            out["refusal"] = delta["refusal"]
        if choice.get("finish_reason"):
            out["finish"] = choice["finish_reason"]
        if choice.get("native_finish_reason"):
            out["native"] = choice["native_finish_reason"]
        if choice.get("error"):
            err = choice["error"]
            raise RuntimeError(f"OpenRouter upstream error: {err.get('message', err) if isinstance(err, dict) else err}")


def _record(model: str, result: dict, raw_prompt_tokens: int, desc: str, elapsed: float, generation_id: str | None) -> None:
    if not result["usage"]:
        # No usage chunk (dropped stream, or a proxy that omits usage): a request, but unmeasured.
        record_usage("OPENROUTER", model, cost=None, measured=False)
        emit_raw("DEBUG", f"OPENROUTER USAGE | model={model} | no usage reported | generation_id={generation_id or 'n/a'}", dest="BOTH")
        return
    usage = result["usage"]
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0  # includes reasoning tokens
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens") or 0
    cache_write = details.get("cache_write_tokens") or 0
    cost = usage.get("cost")
    upstream = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    if usage.get("is_byok") and isinstance(upstream, int | float):
        # BYOK: `cost` is only OpenRouter's fee; the provider bills upstream_inference_cost to your key.
        cost = (cost if isinstance(cost, int | float) else 0.0) + upstream
    record_usage(
        "OPENROUTER",
        model,
        input_tokens=prompt,
        output_tokens=completion,
        thinking_tokens=reasoning_tokens,
        cache_read=cached,
        cache_write=cache_write,
        cost=float(cost) if isinstance(cost, int | float) else None,
    )
    ratio = prompt / raw_prompt_tokens if raw_prompt_tokens else 0.0
    # usage counts come from the upstream model's own tokenizer (OpenRouter usage accounting), so they
    # calibrate like the native provider; observe_prompt_tokens skips ':online' routes (injected search
    # results) and implausible ratios (prompt rewritten in transit).
    from utils.token_utils import observe_prompt_tokens

    observe_prompt_tokens("OPENROUTER", model, raw_prompt_tokens, prompt)
    emit_raw(
        "DEBUG",
        f"OPENROUTER USAGE | model={model} | {desc} | finish={result['finish']} (native={result['native']}) | in={prompt:,} | out={completion:,} | "
        f"reasoning={reasoning_tokens:,} | cached={cached:,} | cost={'$' + format(cost, '.4f') if isinstance(cost, int | float) else 'n/a'} | "
        f"elapsed={elapsed:.1f}s | observed_token_ratio={ratio:.2f} | generation_id={generation_id or 'n/a'}",
        dest="BOTH",
    )


def call_openrouter(prompt: str, thinking_level: str | None = None) -> str:
    """Send a single-turn prompt through OpenRouter and return the response text."""
    from utils.token_utils import count_tokens_raw, token_ratio

    model = get_model()
    if not model:
        raise ValueError("OPENROUTER_MODEL environment variable is required")
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    raw_tokens = count_tokens_raw(prompt)  # memoized: the node already counted this prompt
    payload, desc = build_payload(prompt, model, thinking_level, int(raw_tokens * token_ratio()))
    headers = {"Content-Type": "application/json", **_attribution_headers()}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    max_tokens = payload.get("max_tokens")
    emit_raw(
        "DEBUG",
        f"OpenRouter request | model={model} | {desc} | max_tokens={f'{max_tokens:,}' if max_tokens else 'omitted'} | "
        f"temperature={payload.get('temperature', 'omitted')} | catalog={'yes' if openrouter_catalog() else 'no'} | "
        f"attribution={'on' if 'HTTP-Referer' in headers else 'off'}",
        dest="LOG",
    )

    start = time.time()
    resp = _post(f"{openrouter_base_url()}/v1/chat/completions", headers, payload)
    generation_id = resp.headers.get("X-Generation-Id")
    result = _consume(resp)
    _record(model, result, raw_tokens, desc, time.time() - start, generation_id)
    if is_debug() and result["reasoning"]:
        emit_raw("DEBUG", f"REASONING:\n{result['reasoning']}", dest="LOG")

    finish, native = (result["finish"] or ""), (result["native"] or "")
    if finish == "error":
        raise RuntimeError(f"OpenRouter generation ended with an error (native_finish_reason={native or 'n/a'})")
    if finish == "content_filter" or result["refusal"] or native.lower() in _REFUSAL_NATIVE_REASONS:
        category = native or finish or "refusal"
        # Filters on sampled output (safety, recitation, content_filter) may pass on another attempt.
        retryable = not result["refusal"] and native.lower() not in _DETERMINISTIC_NATIVE_REASONS
        count_event("OPENROUTER", "refusals")
        emit("WARN_LLM_BLOCKED_RETRYABLE" if retryable else "WARN_LLM_REFUSAL", provider="OpenRouter", model=model, category=category)
        raise LLMRefusalError(model, category, provider="OPENROUTER", retryable=retryable)
    if not finish:
        # No data at all, or the connection dropped mid-answer: never return a partial reply.
        raise RuntimeError(
            f"OpenRouter stream ended without a finish_reason after {result['events']} events ({len(result['text']):,} characters received)"
        )
    if finish == "length":
        count_event("OPENROUTER", "truncations")
        emit("WARN_LLM_TRUNCATED", provider="OpenRouter", max_tokens=f"{max_tokens:,}" if max_tokens else "default")
        return TruncatedResponse(result["text"])
    if not result["text"]:
        emit_raw("WARNING", f"OpenRouter response contained no text (finish_reason={finish or 'n/a'})", dest="LOG")
    return result["text"]
