"""Native Google Gemini provider for call_llm() (google-genai SDK, Gemini 3.1+ with 2.5 fallback).

All Gemini-specific request/response handling lives here; this is the only module that imports
the google-genai SDK (imported lazily by call_llm.py / llm_config.py).

Behavior:
- Thinking: Gemini 3.x uses ThinkingConfig.thinking_level with a per-model allowed set
  (llm_config.GEMINI_THINKING_LEVELS; e.g. 3.7/3.8 Flash and 3.1 Pro reject MINIMAL);
  levels outside the set clamp to the nearest (xhigh/max → high). Gemini 2.5 uses
  thinking_budget clamped to the model's range. The two are never sent together (400).
  No level → no thinking_config (model default: medium on 3.5-3.8 Flash, high on 3.1 Pro).
- Output: max_output_tokens is sized per level (thinking counts toward it) from the same table
  token_utils.input_token_budget reserves, capped by the model output limit.
- Streaming: generate_content_stream. GEMINI_TIMEOUT_SECONDS (default 1800) is the SDK's total
  per-request deadline (the whole stream, not an idle timeout), so it must exceed the longest
  high-thinking reply; the SDK retries 408/429/5xx once more (PocketFlow node retries sit on top).
- Finish reasons: MAX_TOKENS → TruncatedResponse (never cached). Blocked prompts and
  PROHIBITED_CONTENT / BLOCKLIST / SPII / IMAGE_* → LLMRefusalError (deterministic: not re-sent);
  SAFETY / RECITATION / LANGUAGE / OTHER on the candidate → LLMRefusalError(retryable=True), since
  another sample can pass.
- Sampling parameters are never sent (deprecated on Gemini 3.x; errors on some Vertex models).
- Thought summaries (include_thoughts) are requested only with --debug and go to the log file.
- Usage (prompt / output / thinking / cached tokens) and estimated cost feed the run summary.

Environment: GEMINI_API_KEY (AI Studio) or GEMINI_PROJECT_ID + GEMINI_LOCATION (Vertex AI,
default location global), GEMINI_MODEL, GEMINI_MAX_OUTPUT_TOKENS, GEMINI_TIMEOUT_SECONDS,
GEMINI_TOKEN_RATIO.
"""

import datetime
import os
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from utils.llm_common import LLMRefusalError, TruncatedResponse, count_event, record_usage, warn_once
from utils.llm_config import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_DEFAULT_LIMITS,
    GEMINI_THINKING_BUDGETS,
    gemini_location,
    gemini_model_id,
    gemini_output_budget,
    gemini_thinking_mode,
)
from utils.output import emit, emit_raw, is_debug
from utils.thinking import clamp_level

# Finish reasons that mean "declined / blocked" rather than "cut off". Sampling-dependent stops can
# pass on another attempt (retryable); policy/term-list blocks repeat for the same input.
_RETRYABLE_FINISH_REASONS = {"SAFETY", "RECITATION", "LANGUAGE", "OTHER"}
_BLOCK_FINISH_REASONS = _RETRYABLE_FINISH_REASONS | {
    "PROHIBITED_CONTENT",
    "BLOCKLIST",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
    "IMAGE_OTHER",
}
_TRUNCATION_FINISH_REASONS = {"MAX_TOKENS"}

# USD per million tokens: (input, output, cached_input[, >200K-prompt input, output, cached]).
# Estimates from Google's published standard prices (Sep 2026; AI Studio = Vertex global; Vertex
# regional endpoints cost 10% more). Longest prefix wins.
_PRICING = {
    "gemini-3.8-flash-cyber": (1.50, 7.50, 0.15),  # Vertex only (allowlisted)
    "gemini-3.8-flash": (1.50, 7.50, 0.15),
    "gemini-3.7-flash": (1.50, 7.50, 0.15),
    "gemini-3.6-flash": (1.50, 7.50, 0.15),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.5-flash": (1.50, 9.00, 0.15),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.1-pro": (2.00, 12.00, 0.20, 4.00, 18.00, 0.40),
    "gemini-3-pro": (2.00, 12.00, 0.20, 4.00, 18.00, 0.40),  # served by 3.1 Pro Preview
    "gemini-3-flash": (0.50, 3.00, 0.05),
    "gemini-2.5-pro": (1.25, 10.00, 0.125, 2.50, 15.00, 0.25),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.01),
    "gemini-2.5-flash": (0.30, 2.50, 0.03),
}
# Introductory prices for 3.6-3.8 Flash (not Cyber) through Dec 31, 2026.
_INTRO_PRICING = {"gemini-3.8-flash": (0.75, 3.75, 0.075), "gemini-3.7-flash": (0.75, 3.75, 0.075), "gemini-3.6-flash": (0.75, 3.75, 0.075)}
_INTRO_PRICING_UNTIL = datetime.date(2026, 12, 31)
_REGIONAL_UPLIFT = 1.10
_LONG_CONTEXT_THRESHOLD = 200_000

_client = None
_model_limits_cache = {}
_thinking_rejected = set()  # models that answered 400 to our thinking_config: sent without it afterwards


def get_model() -> str:
    """GEMINI_MODEL without a 'models/' or 'publishers/google/models/' resource prefix."""
    return gemini_model_id(os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL)


def _timeout_ms() -> int:
    """Total per-request deadline (the SDK applies it to the whole streamed response)."""
    try:
        seconds = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "1800"))
    except ValueError:
        seconds = 1800.0
    return int(max(seconds, 30.0) * 1000)


def _get_client():
    global _client
    if _client is None:
        http_options = types.HttpOptions(
            timeout=_timeout_ms(),  # milliseconds; with no timeout a stalled connection hangs forever
            # One SDK retry for transient errors; PocketFlow node retries (5 x 20 s) sit on top.
            retry_options=types.HttpRetryOptions(attempts=2, http_status_codes=[408, 429, 500, 502, 503, 504]),
        )
        if os.getenv("GEMINI_PROJECT_ID"):
            _client = genai.Client(vertexai=True, project=os.getenv("GEMINI_PROJECT_ID"), location=gemini_location(), http_options=http_options)
        elif os.getenv("GEMINI_API_KEY"):
            # vertexai=False explicitly: GOOGLE_GENAI_USE_VERTEXAI=true in the environment would otherwise
            # route the API key to Vertex AI.
            _client = genai.Client(vertexai=False, api_key=os.getenv("GEMINI_API_KEY"), http_options=http_options)
        else:
            raise ValueError("Either GEMINI_PROJECT_ID or GEMINI_API_KEY must be set in the environment")
    return _client


def get_model_limits(model: str) -> tuple[int, int]:
    """(input_token_limit, output_token_limit). AI Studio reports them via models.get; Vertex does
    not (the SDK maps no limits there), so the static Gemini 3.x / 2.5 table applies."""
    if model in _model_limits_cache:
        return _model_limits_cache[model]
    limits = GEMINI_DEFAULT_LIMITS
    if not os.getenv("GEMINI_PROJECT_ID"):
        try:
            info = _get_client().models.get(model=model)
            limits = (getattr(info, "input_token_limit", None) or limits[0], getattr(info, "output_token_limit", None) or limits[1])
            emit_raw("DEBUG", f"Gemini models.get | model={model} | input={limits[0]:,} | output={limits[1]:,}", dest="LOG")
        except Exception as e:
            emit("WARN_GEMINI_MODEL_LOOKUP", model=model, error=str(e)[:200])
    _model_limits_cache[model] = limits
    return limits


def _thinking_config(model: str, level: str | None):
    """(ThinkingConfig | None, description). Never mixes thinking_level with thinking_budget."""
    mode, spec = gemini_thinking_mode(model)
    include = True if is_debug() else None  # thought summaries only for the debug log
    if model in _thinking_rejected:
        return None, "default (thinking config rejected by model)"
    if not level:
        # Model default thinking; with --debug still ask for summaries so they can be logged.
        return (types.ThinkingConfig(include_thoughts=True) if include and mode != "none" else None), "default"
    if mode == "level":
        effective = clamp_level(level.lower(), spec) or spec[-1]
        if effective != level.lower() and warn_once("gemini_level", model, level):
            emit("WARN_THINKING_LEVEL_CLAMPED", level=level, effective=effective, model=model)
        return types.ThinkingConfig(thinking_level=effective, include_thoughts=include), f"thinking_level={effective}"
    if mode == "budget":
        low, high, _can_disable = spec
        budget = min(max(GEMINI_THINKING_BUDGETS.get(level.lower(), 4096), low), high)
        return types.ThinkingConfig(thinking_budget=budget, include_thoughts=include), f"thinking_budget={budget}"
    if warn_once("gemini_no_thinking", model):
        emit("WARN_THINKING_NOT_SUPPORTED", model=model)
    return None, "unsupported"


def _max_output_tokens(model: str, level: str | None) -> int:
    """Per-level budget capped by the model's output limit. Gemini documents separate input and
    output limits, so output is not reduced for large prompts (input_token_budget still reserves it)."""
    _input_limit, output_limit = get_model_limits(model)
    return gemini_output_budget(level, output_limit)


def _name(value) -> str:
    """Enum → 'NAME' (unknown enum members arrive as dynamic values; compare by name)."""
    return (getattr(value, "name", None) or str(value or "")).split(".")[-1].upper()


def _price(model: str, prompt_tokens: int, cached: int, output_tokens: int, today: datetime.date | None = None) -> float | None:
    key = next((k for k in sorted(_PRICING, key=len, reverse=True) if model.lower().startswith(k)), None)
    if key is None:
        return None
    row = _PRICING[key]
    if key in _INTRO_PRICING and (today or datetime.date.today()) <= _INTRO_PRICING_UNTIL:
        row = _INTRO_PRICING[key]
    p_in, p_out, p_cache = row[3:6] if len(row) == 6 and prompt_tokens > _LONG_CONTEXT_THRESHOLD else row[:3]
    uncached = max(prompt_tokens - cached, 0)
    cost = (uncached * p_in + cached * p_cache + output_tokens * p_out) / 1_000_000
    if os.getenv("GEMINI_PROJECT_ID") and gemini_location().lower() != "global":
        cost *= _REGIONAL_UPLIFT
    return cost


def _record(model: str, usage, raw_prompt_tokens: int, level_desc: str, finish: str, elapsed: float) -> None:
    prompt = getattr(usage, "prompt_token_count", 0) or 0
    candidates = getattr(usage, "candidates_token_count", 0) or 0
    thoughts = getattr(usage, "thoughts_token_count", 0) or 0
    cached = getattr(usage, "cached_content_token_count", 0) or 0
    output = candidates + thoughts  # thinking is billed as output
    cost = _price(model, prompt, cached, output)
    record_usage("GEMINI", model, input_tokens=prompt, output_tokens=output, thinking_tokens=thoughts, cache_read=cached, cost=cost)
    ratio = prompt / raw_prompt_tokens if raw_prompt_tokens else 0.0
    from utils.token_utils import observe_prompt_tokens

    observe_prompt_tokens("GEMINI", model, raw_prompt_tokens, prompt)  # prompt_token_count includes cached tokens
    emit_raw(
        "DEBUG",
        f"GEMINI USAGE | model={model} | {level_desc} | finish={finish or 'n/a'} | in={prompt:,} | out={candidates:,} | thinking={thoughts:,} | "
        f"cached={cached:,} | est_cost={'$' + format(cost, '.4f') if cost is not None else 'n/a'} | elapsed={elapsed:.1f}s | observed_token_ratio={ratio:.2f}",
        dest="BOTH",
    )


def _stream(model: str, prompt: str, config) -> dict:
    """Consume generate_content_stream; returns text, thoughts, finish, block_reason, usage."""
    text, thoughts = [], []
    finish, block_reason, usage = "", "", None
    for chunk in _get_client().models.generate_content_stream(model=model, contents=[prompt], config=config):
        feedback = getattr(chunk, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            block_reason = _name(feedback.block_reason)
        if getattr(chunk, "usage_metadata", None) is not None:
            usage = chunk.usage_metadata
        for candidate in getattr(chunk, "candidates", None) or []:
            if getattr(candidate, "finish_reason", None):
                finish = _name(candidate.finish_reason)
            content = getattr(candidate, "content", None)
            for part in (getattr(content, "parts", None) or []) if content is not None else []:
                if getattr(part, "text", None):
                    (thoughts if getattr(part, "thought", False) else text).append(part.text)
            break  # candidate_count is 1
    return {"text": "".join(text), "thoughts": "".join(thoughts), "finish": finish, "block_reason": block_reason, "usage": usage}


def call_gemini(prompt: str, thinking_level: str | None = None) -> str:
    """Send a single-turn prompt to Gemini and return the response text."""
    from utils.token_utils import count_tokens_raw

    model = get_model()
    raw_tokens = count_tokens_raw(prompt)
    max_output = _max_output_tokens(model, thinking_level)
    thinking, level_desc = _thinking_config(model, thinking_level)
    # No tools are passed, so automatic function calling is off (google-genai warns on streams otherwise).
    no_afc = types.AutomaticFunctionCallingConfig(disable=True)
    config = types.GenerateContentConfig(max_output_tokens=max_output, thinking_config=thinking, automatic_function_calling=no_afc)
    emit_raw(
        "DEBUG",
        f"Gemini request | model={model} | {level_desc} | max_output_tokens={max_output:,} | location={gemini_location() if os.getenv('GEMINI_PROJECT_ID') else 'ai-studio'}",
        dest="LOG",
    )

    start = time.time()
    try:
        result = _stream(model, prompt, config)
    except genai_errors.ClientError as e:
        # A model that rejects our thinking control (unknown future model, level set changed):
        # warn once and resend without it for the rest of the run.
        if getattr(e, "code", None) == 400 and thinking is not None and "think" in str(e).lower():
            _thinking_rejected.add(model)
            emit("WARN_GEMINI_THINKING_REJECTED", model=model, error=str(e)[:200])
            config = types.GenerateContentConfig(max_output_tokens=max_output, thinking_config=None, automatic_function_calling=no_afc)
            result = _stream(model, prompt, config)
        else:
            raise
    elapsed = time.time() - start

    if result["usage"] is not None:
        _record(model, result["usage"], raw_tokens, level_desc, result["finish"], elapsed)
    else:
        record_usage("GEMINI", model, cost=None, measured=False)  # stream carried no usage_metadata
    if is_debug() and result["thoughts"]:
        emit_raw("DEBUG", f"THINKING SUMMARY:\n{result['thoughts']}", dest="LOG")

    if result["block_reason"] or result["finish"] in _BLOCK_FINISH_REASONS:
        category = result["block_reason"] or result["finish"]
        # A blocked prompt repeats for the same input; a stop on the candidate may pass on resampling.
        retryable = not result["block_reason"] and result["finish"] in _RETRYABLE_FINISH_REASONS
        count_event("GEMINI", "refusals")
        emit("WARN_LLM_BLOCKED_RETRYABLE" if retryable else "WARN_LLM_REFUSAL", provider="Gemini", model=model, category=category)
        raise LLMRefusalError(model, category, provider="GEMINI", retryable=retryable)
    if result["finish"] in _TRUNCATION_FINISH_REASONS:
        count_event("GEMINI", "truncations")
        emit("WARN_LLM_TRUNCATED", provider="Gemini", max_tokens=f"{max_output:,}")
        return TruncatedResponse(result["text"])
    if not result["text"]:
        emit_raw("WARNING", f"Gemini response contained no text (finish_reason={result['finish'] or 'n/a'})", dest="LOG")
    return result["text"]
