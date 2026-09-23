"""Provider-neutral LLM helpers shared by every provider module (no SDK imports).

- TruncatedResponse: reply text that was cut off (max tokens / context window). call_llm returns
  it but never caches it; parse_yaml_response rejects it so the node retries.
- LLMRefusalError: the provider declined the request (Claude refusal, Gemini safety/recitation
  block, OpenRouter content_filter / moderation). Deterministic declines (retryable=False) are
  remembered by call_llm and not re-sent; sampling-dependent output blocks (retryable=True, e.g.
  Gemini RECITATION / OTHER) are re-sampled by the node retry.
- Usage ledger: per-request token/cost accounting per provider and per step (call_llm(step=...)),
  used for the per-call usage lines, step subtotals and the end-of-run LLM_USAGE_SUMMARY.
- warn_once: de-duplicates warnings that would otherwise repeat on every call.
"""

import contextlib
import contextvars
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
# Totals per provider and per step (the NODE_KEYS name passed to call_llm(step=...)). `input` is the
# TOTAL prompt tokens the provider counted, cached tokens included, for every provider; cache_read /
# cache_write are breakdowns of it. `output` includes thinking; `thinking` is the reported subset.
_usage = {}
_steps = {}
_current_step = contextvars.ContextVar("llm_usage_step", default="other")


def _new_entry() -> dict:
    return {
        "models": set(),
        "calls": 0,
        "input": 0,
        "output": 0,
        "thinking": 0,
        "cache_read": 0,
        "cache_write": 0,
        "cost": 0.0,
        "unpriced_calls": 0,
        "unmeasured_calls": 0,
        "refusals": 0,
        "fallbacks": 0,
        "truncations": 0,
        "estimated_input": 0,
        "cache_hits": 0,
    }


@contextlib.contextmanager
def usage_step(step: str | None):
    """Attribute every record_usage / count_event inside the block to `step`."""
    token = _current_step.set(step or "other")
    try:
        yield
    finally:
        _current_step.reset(token)


def current_step() -> str:
    return _current_step.get()


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
    measured: bool = True,
) -> None:
    """Accumulate one API request. `input_tokens` = total prompt tokens (cached included);
    `output_tokens` includes thinking. `cost` is USD; None = unknown price (counted as unpriced).
    measured=False: the provider reported no usage, or the request was an unbilled decline — it counts
    as a request but is left out of estimate-vs-billed comparisons (`unmeasured_calls`)."""
    for entry in (_usage.setdefault(provider, _new_entry()), _steps.setdefault(current_step(), _new_entry())):
        if model:
            entry["models"].add(model)
        entry["calls"] += 1
        if not measured:
            entry["unmeasured_calls"] += 1
        entry["input"] += input_tokens or 0
        entry["output"] += output_tokens or 0
        entry["thinking"] += thinking_tokens or 0
        entry["cache_read"] += cache_read or 0
        entry["cache_write"] += cache_write or 0
        if cost is None:
            entry["unpriced_calls"] += 1
        else:
            entry["cost"] += cost


def count_event(provider: str, event: str) -> None:
    """Increment 'refusals' | 'fallbacks' | 'truncations' for a provider (and the current step)."""
    _usage.setdefault(provider, _new_entry())[event] += 1
    _steps.setdefault(current_step(), _new_entry())[event] += 1


def record_estimate(step: str, estimated_input: int, *, cache_hit: bool = False) -> None:
    """Add call_llm's input estimate for a call (billed or served from the LLM cache) to a step."""
    entry = _steps.setdefault(step or "other", _new_entry())
    if cache_hit:
        entry["cache_hits"] += 1
    else:
        entry["estimated_input"] += estimated_input or 0


def usage_snapshot(provider: str) -> dict:
    """Copy of a provider's running totals (diff two snapshots to get one call's usage)."""
    entry = _usage.get(provider)
    return {k: v for k, v in entry.items() if k != "models"} if entry else {k: v for k, v in _new_entry().items() if k != "models"}


def usage_delta(before: dict, after: dict) -> dict:
    return {k: after[k] - before.get(k, 0) for k in after}


def _public(entry: dict) -> dict:
    return dict(entry, models=sorted(entry["models"]), cost_known=entry["unpriced_calls"] == 0)


def get_usage_summary() -> dict:
    """{provider: totals} for every provider that made at least one call this run."""
    return {provider: _public(entry) for provider, entry in _usage.items() if entry["calls"]}


def get_step_summary() -> dict:
    """{step: totals} in first-use order, including steps answered only from the LLM cache."""
    return {step: _public(entry) for step, entry in _steps.items() if entry["calls"] or entry["cache_hits"]}


def reset_usage() -> None:
    _usage.clear()
    _steps.clear()
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
