"""Provider-neutral LLM helpers shared by every provider module (no SDK imports).

- TruncatedResponse: reply text that was cut off (max tokens / context window). call_llm returns
  it but never caches it; parse_yaml_response rejects it so the node retries.
- LLMRefusalError: the provider declined the request (Claude refusal, Gemini safety/recitation
  block, OpenRouter content_filter / moderation). Deterministic declines (retryable=False) are
  remembered by call_llm and not re-sent; sampling-dependent output blocks (retryable=True, e.g.
  Gemini RECITATION / OTHER) are re-sampled by the node retry.
- Usage ledger: per-call token/cost accounting for the end-of-run LLM_USAGE_SUMMARY.
- warn_once: de-duplicates warnings that would otherwise repeat on every call.
"""

import hashlib


class TruncatedResponse(str):
    """Response text from a reply that was cut off; call_llm returns it but never caches it."""

    truncated = True


class LLMRefusalError(RuntimeError):
    """Raised when the provider (and any configured fallback) declines a request.

    retryable=False: the same request is declined again (Claude refusal, blocked prompt,
    prohibited content) — call_llm remembers it and does not re-send it on node retries.
    retryable=True: an output-side block that a new sample can pass (Gemini RECITATION / OTHER /
    SAFETY on the candidate, OpenRouter content_filter) — node retries re-sample normally.
    """

    def __init__(self, model: str, category: str | None, provider: str = "ANTHROPIC", retryable: bool = False):
        self.model = model
        self.category = category
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"{provider} model {model} declined the request (category={category or 'unknown'})")


# ---------------------------------------------------------------------------
# Refused-request memo: a declined prompt is declined again, so PocketFlow retries
# must not re-send it (wasted rate limit, and billed partial output on mid-stream declines).
# ---------------------------------------------------------------------------
_refused = {}


def request_key(provider: str, model: str, thinking_level: str | None, prompt: str) -> str:
    scope = f"{provider}|{model}|{(thinking_level or 'default').lower()}\n"
    return hashlib.sha256((scope + prompt).encode("utf-8")).hexdigest()


def remember_refusal(key: str, error: LLMRefusalError) -> None:
    _refused[key] = error


def previous_refusal(key: str) -> LLMRefusalError | None:
    return _refused.get(key)


# ---------------------------------------------------------------------------
# Usage ledger (one per process; a run is sequential)
# ---------------------------------------------------------------------------
_usage = {}


def record_usage(
    provider: str,
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    thinking_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    cost: float | None = None,
) -> None:
    """Accumulate one call. `output_tokens` includes thinking; `thinking_tokens` is the reported subset.
    `cost` is USD; None means the price is unknown for this model (summary shows n/a)."""
    entry = _usage.setdefault(
        provider,
        {
            "models": set(),
            "calls": 0,
            "input": 0,
            "output": 0,
            "thinking": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost": 0.0,
            "cost_known": True,
            "refusals": 0,
            "fallbacks": 0,
            "truncations": 0,
        },
    )
    if model:
        entry["models"].add(model)
    entry["calls"] += 1
    entry["input"] += input_tokens or 0
    entry["output"] += output_tokens or 0
    entry["thinking"] += thinking_tokens or 0
    entry["cache_read"] += cache_read or 0
    entry["cache_write"] += cache_write or 0
    if cost is None:
        entry["cost_known"] = False
    else:
        entry["cost"] += cost


def count_event(provider: str, event: str) -> None:
    """Increment 'refusals' | 'fallbacks' | 'truncations' for a provider."""
    entry = _usage.setdefault(
        provider,
        {
            "models": set(),
            "calls": 0,
            "input": 0,
            "output": 0,
            "thinking": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost": 0.0,
            "cost_known": True,
            "refusals": 0,
            "fallbacks": 0,
            "truncations": 0,
        },
    )
    entry[event] += 1


def get_usage_summary() -> dict:
    """{provider: totals} for every provider that made at least one call this run."""
    return {provider: dict(entry, models=sorted(entry["models"])) for provider, entry in _usage.items() if entry["calls"]}


def reset_usage() -> None:
    _usage.clear()
    _refused.clear()


# ---------------------------------------------------------------------------
# De-duplicated warnings
# ---------------------------------------------------------------------------
_warned = set()


def warn_once(key: str, *parts) -> bool:
    """True the first time a (key, parts) combination is seen this run."""
    marker = (key, *parts)
    if marker in _warned:
        return False
    _warned.add(marker)
    return True
