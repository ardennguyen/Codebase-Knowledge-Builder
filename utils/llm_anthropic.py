"""Native Anthropic (Claude) provider for call_llm().

All Claude-specific request/response handling lives here so call_llm.py stays a
thin provider dispatcher. The anthropic SDK is imported lazily by call_llm.py,
so users of other providers do not need it installed.

Behavior (tuned for the Claude 5 family — default Sonnet 5 — and works for every Claude
model from 4.6, plus Haiku 4.5):
- Thinking: the Claude 5 family thinks adaptively by default (always on for Opus 5.5 /
  Fable); depth is controlled with output_config.effort (low | medium | high | xhigh | max;
  Sonnet 5 defaults to high, Opus 5.5 to medium). Pre-4.6 models (e.g. Haiku 4.5) fall back
  to a budget_tokens mapping.
- Streaming: every request streams, so large max_tokens (thinking + reply,
  up to 128K) never hit HTTP timeouts.
- max_tokens: sized per effort level (thinking counts toward it; same table as
  token_utils.input_token_budget) and clamped so prompt + output fits the context window.
- Refusals: server-side fallbacks (beta) are opted in by default for models
  with safety classifiers (Opus 5.x, Fable 5.x — not Sonnet 5); a remaining refusal
  raises LLMRefusalError.
- Truncation: stop_reason == "max_tokens" retries once at the largest budget that fits;
  a still-truncated reply is returned as TruncatedResponse, which call_llm never caches.
- Usage: per-call usage is logged and accumulated for an end-of-run cost summary.

Environment variables:
- ANTHROPIC_API_KEY            (or ANTHROPIC_AUTH_TOKEN / `ant auth login` profile)
- ANTHROPIC_MODEL              default: claude-sonnet-5
- ANTHROPIC_BASE_URL           optional (read by the SDK)
- ANTHROPIC_FALLBACKS          "default" (default) | "off" | comma-separated model IDs
- ANTHROPIC_MAX_OUTPUT_TOKENS  optional hard cap for max_tokens (also caps the truncation retry)
- ANTHROPIC_PROMPT_CACHE       "off" (default) | "on" — top-level automatic prompt caching
- ANTHROPIC_TOKEN_RATIO        tiktoken→Claude token multiplier for budgeting (default 1.4 for the Opus 4.7+ tokenizer, 1.2 for 4.6 and older)
"""

import os
import time

import anthropic

from utils.llm_common import LLMRefusalError, TruncatedResponse, count_event, record_usage
from utils.llm_config import (
    ANTHROPIC_ADAPTIVE_PREFIXES,
    ANTHROPIC_BUDGET_BY_LEVEL,
    ANTHROPIC_CONTEXT_MARGIN,
    ANTHROPIC_EFFORT_LEVELS,
    ANTHROPIC_NO_XHIGH_PREFIXES,
    ANTHROPIC_THINKING_BY_DEFAULT_PREFIXES,
    DEFAULT_ANTHROPIC_MODEL,
    anthropic_effort,
    anthropic_output_cap,
    anthropic_planned_output,
)
from utils.output import emit, emit_raw, is_debug

EFFORT_LEVELS = ANTHROPIC_EFFORT_LEVELS

# Model-family tables live in utils/llm_config.py (SDK-free, shared with OpenRouter Claude IDs):
# ANTHROPIC_ADAPTIVE_PREFIXES (adaptive + effort; others use budget_tokens), ANTHROPIC_NO_XHIGH_PREFIXES
# (4.6 family), ANTHROPIC_THINKING_BY_DEFAULT_PREFIXES (think when `thinking` is omitted).
_ADAPTIVE_PREFIXES = ANTHROPIC_ADAPTIVE_PREFIXES
_NO_XHIGH_PREFIXES = ANTHROPIC_NO_XHIGH_PREFIXES
_THINKING_BY_DEFAULT_PREFIXES = ANTHROPIC_THINKING_BY_DEFAULT_PREFIXES

# Models with safety classifiers that can decline a request (stop_reason "refusal"): Opus 5.x and
# Fable 5.x. ANTHROPIC_FALLBACKS=default opts these in to server-side fallbacks. An explicit list
# (ANTHROPIC_FALLBACKS=<model>,<model>) applies to any model — e.g. Mythos 5.1, whose default
# fallback targets are unconfirmed. (Mythos 5 runs no classifiers.)
_FALLBACK_PREFIXES = ("claude-opus-5", "claude-fable-5")
_FALLBACK_DEFAULT_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_LIST_BETA = "server-side-fallback-2026-06-01"

# Offline fallbacks when the Models API cannot be reached: (context window, max output).
_MODEL_LIMITS = {
    "claude-haiku-4-5": (200_000, 64_000),
}
_DEFAULT_LIMITS = (1_000_000, 128_000)

# Planned max_tokens (per-effort table on adaptive models, budget_tokens + 16K on Haiku 4.5 and older)
# comes from llm_config.anthropic_planned_output — shared with token_utils.input_token_budget.
# Streaming makes large values safe.
_BUDGET_BY_LEVEL = ANTHROPIC_BUDGET_BY_LEVEL
# Stop reasons that mean the reply was cut off.
_TRUNCATION_STOPS = ("max_tokens", "model_context_window_exceeded")

# USD per million tokens: (input, output, cache_read). 5-minute cache writes are
# billed at 1.25x input. Longest-prefix match on the served model ID.
_PRICING = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-mythos-5-1": (10.00, 50.00, 0.25),
    "claude-mythos-5": (10.00, 50.00, 1.00),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}


# TruncatedResponse and LLMRefusalError are shared with the other providers (utils/llm_common.py)
# and re-exported here for backward compatibility.
__all__ = ["LLMRefusalError", "TruncatedResponse", "call_anthropic", "get_model_limits"]


# ---------------------------------------------------------------------------
# Module state (a run is sequential; one client and one usage ledger per process)
# ---------------------------------------------------------------------------
_client = None
_model_limits_cache = {}
_fallbacks_disabled = False


def _get_client():
    global _client
    if _client is None:
        # SDK resolves credentials (ANTHROPIC_API_KEY / AUTH_TOKEN / ant profile) and
        # ANTHROPIC_BASE_URL itself. SDK retries 408/409/429/5xx with backoff;
        # PocketFlow node retries sit on top of this.
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def get_model() -> str:
    return os.getenv("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL


def _matches(model: str, prefixes) -> bool:
    return any(model.startswith(p) for p in prefixes)


def uses_adaptive_thinking(model: str) -> bool:
    return _matches(model, _ADAPTIVE_PREFIXES)


def get_model_limits(model: str) -> tuple[int, int]:
    """Return (context_window, max_output_tokens) from the Models API, with offline fallback."""
    if model in _model_limits_cache:
        return _model_limits_cache[model]
    fallback = next((v for k, v in _MODEL_LIMITS.items() if model.startswith(k)), _DEFAULT_LIMITS)
    try:
        info = _get_client().models.retrieve(model)
        limits = (getattr(info, "max_input_tokens", None) or fallback[0], getattr(info, "max_tokens", None) or fallback[1])
        emit_raw("DEBUG", f"Anthropic Models API | model={model} | context={limits[0]:,} | max_output={limits[1]:,}", dest="LOG")
    except anthropic.APIError as e:
        emit("WARN_ANTHROPIC_MODEL_LOOKUP", model=model, error=str(e))
        limits = fallback
    _model_limits_cache[model] = limits
    return limits


def normalize_effort(model: str, level: str | None) -> str | None:
    """Map a thinking level to an effort value the model accepts (None = model default)."""
    effort = anthropic_effort(model, level)  # minimal → low; xhigh → high on the 4.6 family
    if level and effort is None:
        emit("WARN_THINKING_LEVEL_INVALID", level=level.lower(), model=model, supported=str(list(EFFORT_LEVELS)))
    return effort


def _fallback_config(model: str) -> tuple[list[str], dict]:
    """Return (betas, extra_body) for server-side refusal fallbacks, or empty when disabled."""
    setting = (os.getenv("ANTHROPIC_FALLBACKS") or "default").strip()
    if _fallbacks_disabled or setting.lower() == "off":
        return [], {}
    if setting.lower() == "default":
        if not _matches(model, _FALLBACK_PREFIXES):
            return [], {}
        return [_FALLBACK_DEFAULT_BETA], {"fallbacks": "default"}
    targets = [m.strip() for m in setting.split(",") if m.strip()]
    return [_FALLBACK_LIST_BETA], {"fallbacks": [{"model": m} for m in targets]}


def _build_request(prompt: str, model: str, effort: str | None, max_tokens: int) -> tuple[dict, list[str]]:
    params = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if uses_adaptive_thinking(model):
        if effort or _matches(model, _THINKING_BY_DEFAULT_PREFIXES):
            thinking = {"type": "adaptive"}
            if is_debug():
                # Readable reasoning summaries go to the log file (never to stdout).
                thinking["display"] = "summarized"
            params["thinking"] = thinking
        if effort:
            params["output_config"] = {"effort": effort}
    elif effort:
        budget = min(_BUDGET_BY_LEVEL[effort], max_tokens - 1_024)
        if budget >= 1_024:
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}

    if (os.getenv("ANTHROPIC_PROMPT_CACHE") or "off").strip().lower() == "on":
        params["cache_control"] = {"type": "ephemeral"}

    betas, extra_body = _fallback_config(model)
    if extra_body:
        params["extra_body"] = extra_body
    return params, betas


def _resolve_max_tokens(prompt_tokens: int, model: str, effort: str | None) -> tuple[int, int]:
    """Return (max_tokens, ceiling): the planned budget and the largest budget allowed.

    `prompt_tokens` comes from count_tokens() (already scaled by ANTHROPIC_TOKEN_RATIO).
    The ceiling respects the model output cap, the context window (prompt + output +
    ANTHROPIC_CONTEXT_MARGIN — the same margin input_token_budget reserves), and
    ANTHROPIC_MAX_OUTPUT_TOKENS when set.
    """
    context_window, output_cap = get_model_limits(model)
    cap = anthropic_output_cap()
    wanted = anthropic_planned_output(model, effort)  # same value input_token_budget reserved

    room = max(context_window - prompt_tokens - ANTHROPIC_CONTEXT_MARGIN, 4_096)
    ceiling = min(output_cap, room, cap) if cap else min(output_cap, room)
    if ceiling < wanted:
        # Small shortfalls (template overhead on a budget-packed prompt) are expected; only report real cuts.
        if ceiling < wanted * 0.9:
            emit("WARN_ANTHROPIC_OUTPUT_CLAMPED", wanted=f"{wanted:,}", available=f"{ceiling:,}")
        wanted = ceiling
    return wanted, ceiling


def _stream_message(params: dict, betas: list[str]):
    client = _get_client()
    if betas:
        with client.beta.messages.stream(betas=betas, **params) as stream:
            return stream.get_final_message()
    with client.messages.stream(**params) as stream:
        return stream.get_final_message()


def _fallback_rejected(error_text: str, params: dict) -> bool:
    """True when a 400 rejects the fallback feature itself (beta header not enabled, or
    `fallbacks: "default"` unsupported for this model/account) — not a user config error."""
    text = error_text.lower()
    if "anthropic-beta" in text and "server-side-fallback" in text:
        return True
    return params.get("extra_body", {}).get("fallbacks") == "default" and "fallbacks" in text


def _send(params: dict, betas: list[str]):
    """Send one streamed request; disable fallbacks for the run if the feature is unavailable."""
    global _fallbacks_disabled
    try:
        return _stream_message(params, betas)
    except anthropic.BadRequestError as e:
        if "extra_body" in params and _fallback_rejected(str(e), params):
            _fallbacks_disabled = True
            emit("WARN_ANTHROPIC_FALLBACK_DISABLED", error=str(e))
            retry_params = {k: v for k, v in params.items() if k != "extra_body"}
            return _stream_message(retry_params, [])
        raise


def _price(model: str, tokens_in: int, tokens_out: int, cache_read: int, cache_write: int) -> float | None:
    price = next((_PRICING[k] for k in sorted(_PRICING, key=len, reverse=True) if (model or "").startswith(k)), None)
    if price is None:
        return None
    p_in, p_out, p_read = price
    return (tokens_in * p_in + tokens_out * p_out + cache_read * p_read + cache_write * p_in * 1.25) / 1_000_000


def _tokens(usage) -> tuple[int, int, int, int]:
    return (
        getattr(usage, "input_tokens", 0) or 0,
        getattr(usage, "output_tokens", 0) or 0,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


def _message_cost(message, served_model: str) -> float | None:
    """Estimated USD cost of one response. With server-side fallbacks, usage.iterations holds the
    per-attempt usage (each billed at its own model's rate; an attempt declined before any output is
    unbilled); top-level usage covers only the attempt that produced the returned message."""
    iterations = getattr(message.usage, "iterations", None) or []
    if iterations:
        total, known = 0.0, True
        for entry in iterations:
            tokens_in, tokens_out, cache_read, cache_write = _tokens(entry)
            if tokens_out == 0:
                continue  # declined before any output (primary or fallback attempt): not billed
            cost = _price(getattr(entry, "model", None) or served_model, tokens_in, tokens_out, cache_read, cache_write)
            known = known and cost is not None
            total += cost or 0.0
        return total if known else None
    if message.stop_reason == "refusal" and not _extract_text(message):
        return 0.0  # declined before any output: not billed
    return _price(served_model, *_tokens(message.usage))


def _record_usage(message, raw_prompt_tokens: int, effort: str | None, elapsed: float) -> None:
    served_model = getattr(message, "model", "") or ""
    tokens_in, tokens_out, cache_read, cache_write = _tokens(message.usage)
    cost = _message_cost(message, served_model)
    record_usage(
        "ANTHROPIC", served_model, input_tokens=tokens_in, output_tokens=tokens_out, cache_read=cache_read, cache_write=cache_write, cost=cost
    )

    # Observed Claude/tiktoken ratio helps tune ANTHROPIC_TOKEN_RATIO for this codebase.
    ratio = (tokens_in + cache_read + cache_write) / raw_prompt_tokens if raw_prompt_tokens else 0.0
    emit_raw(
        "DEBUG",
        f"ANTHROPIC USAGE | model={served_model} | effort={effort or 'default'} | stop={message.stop_reason} | "
        f"in={tokens_in:,} | out={tokens_out:,} | cache_read={cache_read:,} | cache_write={cache_write:,} | "
        f"est_cost={'$' + format(cost, '.4f') if cost is not None else 'n/a'} | elapsed={elapsed:.1f}s | observed_token_ratio={ratio:.2f}",
        dest="LOG",
    )


def _log_thinking(message) -> None:
    for block in message.content:
        if getattr(block, "type", None) == "thinking" and getattr(block, "thinking", ""):
            emit_raw("DEBUG", f"THINKING SUMMARY:\n{block.thinking}", dest="LOG")


def _served_by_fallback(message) -> bool:
    if any(getattr(block, "type", None) == "fallback" for block in message.content):
        return True
    iterations = getattr(message.usage, "iterations", None) or []
    return any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)


def _extract_text(message) -> str:
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


def call_anthropic(prompt: str, thinking_level: str | None = None) -> str:
    """Send a single-turn prompt to Claude and return the response text."""
    from utils.llm_config import get_token_ratio
    from utils.token_utils import count_tokens_raw

    model = get_model()
    effort = normalize_effort(model, thinking_level)
    raw_tokens = count_tokens_raw(prompt)  # tokenize once; the scaled estimate drives the budget
    max_tokens, ceiling = _resolve_max_tokens(int(raw_tokens * get_token_ratio()), model, effort)
    params, betas = _build_request(prompt, model, effort, max_tokens)
    emit_raw(
        "DEBUG",
        f"Anthropic request | model={model} | effort={effort or 'default'} | max_tokens={max_tokens:,} | "
        f"fallbacks={'on' if betas else 'off'} | prompt_cache={'on' if 'cache_control' in params else 'off'}",
        dest="LOG",
    )

    start = time.time()
    message = _send(params, betas)

    if message.stop_reason == "max_tokens" and max_tokens < ceiling:
        # Thinking + reply outgrew the budget: retry once at the largest budget that fits.
        emit("WARN_ANTHROPIC_TRUNCATED_RETRY", max_tokens=f"{max_tokens:,}", cap=f"{ceiling:,}")
        _record_usage(message, raw_tokens, effort, time.time() - start)
        params, betas = _build_request(prompt, model, effort, ceiling)
        start = time.time()
        message = _send(params, betas)

    _record_usage(message, raw_tokens, effort, time.time() - start)
    if is_debug():
        _log_thinking(message)

    if _served_by_fallback(message) and message.stop_reason != "refusal":
        count_event("ANTHROPIC", "fallbacks")
        emit("WARN_ANTHROPIC_FALLBACK_SERVED", model=model, served_by=getattr(message, "model", "unknown"))

    if message.stop_reason == "refusal":
        count_event("ANTHROPIC", "refusals")
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        emit("WARN_ANTHROPIC_REFUSAL", model=model, category=category or "unknown")
        raise LLMRefusalError(model, category, provider="ANTHROPIC")

    text = _extract_text(message)
    if message.stop_reason in _TRUNCATION_STOPS:
        count_event("ANTHROPIC", "truncations")
        emit("WARN_ANTHROPIC_TRUNCATED", max_tokens=f"{params['max_tokens']:,}")
        return TruncatedResponse(text)
    if not text:
        emit_raw("WARNING", f"Anthropic response contained no text blocks (stop_reason={message.stop_reason})", dest="LOG")
    return text
