"""Token estimation, prompt budgets and ratio calibration.

- count_tokens_raw(text): tiktoken cl100k_base count, memoized by content (every prompt is counted by
  the node, log_token_estimation, call_llm and the provider — the memo makes the repeats free). If the
  encoding cannot load, one warning and a conservative UTF-8 bytes/3 estimate (over-counts code, never
  under-counts non-English text).
- count_tokens_raw_many(texts) / count_tokens_many(texts): per-item counts; uncached items are
  batch-encoded on several threads.
- count_tokens(text): raw count x token_ratio() for the active provider+model.
- token_ratio(): the static per-family prior (llm_config.get_token_ratio) corrected by the ratio
  observed in provider-reported usage (observe_prompt_tokens). Learned per provider|model, raised fast
  and lowered slowly (an underestimate overflows the context window; an overestimate only batches
  earlier), and saved to TOKEN_CALIBRATION_FILE so the next run's routing starts calibrated.
  TOKEN_RATIO_CALIBRATION=off disables it.
- input_token_budget(max_tokens, thinking_level): largest prompt that still leaves room for the planned
  output, the flat margin, and an estimation-uncertainty reserve (smaller once calibrated).
"""

import json
import os
import threading
from collections import OrderedDict

import tiktoken

from utils.llm_config import (
    CONTEXT_MARGIN,
    context_output_reserve,
    gemini_model_id,
    get_model_context_length,
    get_token_ratio,
    openrouter_catalog_cached,
    openrouter_model_info,
    resolve_llm_settings,
)
from utils.output import emit, emit_raw, get

# Output tokens reserved on providers that do not size output (OLLAMA / other endpoints): 5%, clamped.
MIN_OUTPUT_RESERVE = 8_192
MAX_OUTPUT_RESERVE = 64_000
# Share of the context window kept free for estimation error (tiktoken x ratio vs the provider's
# tokenizer): larger until the ratio for the active model has been calibrated from real usage.
ESTIMATE_RESERVE_UNCALIBRATED = 0.05
ESTIMATE_RESERVE_CALIBRATED = 0.02


def resolve_max_tokens(shared):
    """Resolve max_tokens from shared store or auto-detect from the active provider."""
    max_tokens = shared.get("max_tokens")
    if max_tokens is not None:
        return max_tokens
    _, model_name, endpoint, api_key = resolve_llm_settings()
    max_tokens_val = get_model_context_length(endpoint, model_name, api_key)
    emit_raw("DEBUG", f"resolve_max_tokens | resolved max_tokens={max_tokens_val:,}", dest="LOG")
    return max_tokens_val


def input_token_budget(max_tokens: int, thinking_level: str | None = None) -> int:
    """Largest prompt size (in count_tokens() units) that still leaves room for the response.

    On ANTHROPIC and OPENROUTER the context window holds prompt + output: reserve exactly what the
    provider module will request for this thinking level (llm_config.context_output_reserve —
    thinking tokens count toward output) plus the flat margin. GEMINI's input limit is separate from
    its output limit, so only the margin is reserved for output. Elsewhere (OLLAMA, or an OpenRouter
    model missing from the catalog) reserve 5% (min 8K, max 64K). Every provider also keeps
    ESTIMATE_RESERVE_* of the window free for estimation error (5% until the token ratio of the active
    model is calibrated, then 2%).
    """
    planned = context_output_reserve(thinking_level)
    if planned is not None:
        reserve = planned + CONTEXT_MARGIN
    else:
        reserve = min(max(int(max_tokens * 0.05), MIN_OUTPUT_RESERVE), MAX_OUTPUT_RESERVE)
    reserve += int(max_tokens * (ESTIMATE_RESERVE_CALIBRATED if ratio_is_calibrated() else ESTIMATE_RESERVE_UNCALIBRATED))
    return max(max_tokens - reserve, max_tokens // 2)


# ---------------------------------------------------------------------------
# Raw counting (tiktoken cl100k_base) with a content memo
# ---------------------------------------------------------------------------
_encoding = None
_encoding_failed = False
# (len, hash) -> raw count. hash() is cached on the str object, so re-counting the same object is O(1);
# only ints are stored (never the text). Short strings are cheaper to encode than to track.
_memo = OrderedDict()
_memo_lock = threading.Lock()
MEMO_MAX_ENTRIES = 4_096
MEMO_MIN_CHARS = 256


def _get_encoding():
    """cl100k_base encoding, loaded once. A failed load is remembered (tiktoken retries a download with
    no timeout on every attempt) and warned about once."""
    global _encoding, _encoding_failed
    if _encoding is None and not _encoding_failed:
        try:
            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            _encoding_failed = True
            emit("WARN_TIKTOKEN_UNAVAILABLE", error=str(e)[:200])
    return _encoding


def _fallback_count(text: str) -> int:
    # Conservative when tiktoken is unavailable: UTF-8 bytes/3 over-counts code (~4.3 chars/token)
    # instead of under-counting non-English text as chars/4 would (~2.5 chars/token for Vietnamese).
    return -(-len(text.encode("utf-8", "surrogatepass")) // 3)


def _encode_count(text: str) -> int:
    enc = _get_encoding()
    return len(enc.encode_ordinary(text)) if enc is not None else _fallback_count(text)


def _memo_get(key):
    with _memo_lock:
        value = _memo.get(key)
        if value is not None:
            _memo.move_to_end(key)
        return value


def _memo_put(key, value: int) -> None:
    with _memo_lock:
        _memo[key] = value
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX_ENTRIES:
            _memo.popitem(last=False)


def count_tokens_raw(text: str) -> int:
    """tiktoken cl100k_base token count (no model calibration). Memoized by content."""
    if not text:
        return 0
    if len(text) < MEMO_MIN_CHARS:
        return _encode_count(text)
    key = (len(text), hash(text))
    cached = _memo_get(key)
    if cached is not None:
        return cached
    count = _encode_count(text)
    _memo_put(key, count)
    return count


def count_tokens_raw_many(texts: list[str]) -> list[int]:
    """Raw counts for many texts; the uncached ones are batch-encoded on several threads."""
    counts = [0] * len(texts)
    pending = []
    for i, text in enumerate(texts):
        if not text:
            continue
        key = (len(text), hash(text)) if len(text) >= MEMO_MIN_CHARS else None
        cached = _memo_get(key) if key else None
        if cached is not None:
            counts[i] = cached
        else:
            pending.append((i, text, key))
    enc = _get_encoding()
    if pending and enc is not None:
        encoded = enc.encode_ordinary_batch([text for _, text, _ in pending], num_threads=min(8, os.cpu_count() or 1))
        results = [len(tokens) for tokens in encoded]
    else:
        results = [_fallback_count(text) for _, text, _ in pending]
    for (i, _text, key), count in zip(pending, results, strict=True):
        counts[i] = count
        if key:
            _memo_put(key, count)
    return counts


# ---------------------------------------------------------------------------
# Token ratio: static prior + calibration from provider-reported usage
# ---------------------------------------------------------------------------
TOKEN_CALIBRATION_FILE = "llm_token_calibration.json"
CALIBRATION_MIN_RAW = 2_000  # below this, fixed per-request framing tokens distort the ratio
CALIBRATION_EMA_WEIGHT = 0.35
CALIBRATION_FULL_WEIGHT_RAW = 50_000  # a sample this large gets the full EMA weight
CALIBRATION_HEADROOM = 1.03
# Lowering the ratio (and the smaller 2% reserve) needs real evidence: enough samples AND enough measured
# text. Until then the learned ratio can only raise the static prior.
CALIBRATION_MIN_SAMPLES_TO_LOWER = 3
CALIBRATION_MIN_RAW_TO_LOWER = 3 * CALIBRATION_FULL_WEIGHT_RAW
CALIBRATION_RANGE = (0.75, 1.5)  # learned ratio stays within these multiples of the static prior
CALIBRATION_PRIOR_DRIFT = 0.02  # a saved entry learned against a different static prior is stale
OBSERVED_RATIO_BOUNDS = (0.5, 3.0)  # samples outside are ignored (e.g. a prompt rewritten in transit)
CALIBRATION_COUNTER = "cl100k_base"  # raw counts the saved ratios are relative to

_static_ratios = {}
_calibration = None  # {"provider|model": {"ema", "n", "raw", "w", "prior"}}
_calibration_lock = threading.Lock()


def calibration_enabled() -> bool:
    return (os.getenv("TOKEN_RATIO_CALIBRATION") or "on").strip().lower() not in ("off", "0", "false", "no")


def _model_id(provider: str, model: str) -> str:
    """Normalized id: Gemini resource prefixes stripped ('models/…'), lower-cased."""
    return gemini_model_id(model) if provider == "GEMINI" else (model or "").strip().lower()


def _calibration_model(provider: str, model: str) -> str:
    """OpenRouter aliases ('~anthropic/claude-sonnet-latest') retarget over time: key the learned ratio by
    the catalog model they resolve to (the one the static prior uses). Other providers: the model as is."""
    if provider == "OPENROUTER":
        info = openrouter_model_info(model)
        if info and info.get("id"):
            return info["id"]
    return model


def _key(provider: str, model: str) -> str:
    return f"{provider}|{_model_id(provider, _calibration_model(provider, model))}"


def _active_key() -> tuple[str, str, str]:
    provider, model, _, _ = resolve_llm_settings()
    return provider, model, _key(provider, model)


def _static_ratio(provider: str, key: str) -> float:
    ratio = _static_ratios.get(key)
    if ratio is None:
        ratio = get_token_ratio()
        # An OpenRouter alias resolves through the catalog: do not freeze a value computed without it.
        if provider != "OPENROUTER" or openrouter_catalog_cached():
            _static_ratios[key] = ratio
    return ratio


def _load_calibration() -> dict:
    global _calibration
    if _calibration is None:
        _calibration = {}
        if calibration_enabled():
            try:
                with open(TOKEN_CALIBRATION_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("counter", CALIBRATION_COUNTER) != CALIBRATION_COUNTER:
                    raise ValueError(f"ratios were measured against {data.get('counter')!r}, not {CALIBRATION_COUNTER}")
                for key, entry in (data.get("entries") or {}).items():
                    if isinstance(entry, dict) and entry.get("n", 0) > 0 and entry.get("ema", 0) > 0:
                        n, raw = int(entry["n"]), int(entry.get("raw", 0))
                        loaded = {
                            "ema": float(entry["ema"]),
                            "n": n,
                            "raw": raw,
                            "w": float(entry.get("w", min(raw / CALIBRATION_FULL_WEIGHT_RAW, n))),
                        }
                        if entry.get("prior"):
                            loaded["prior"] = float(entry["prior"])
                        _calibration[key] = loaded
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, AttributeError) as e:
                emit_raw("WARNING", f"Token calibration file ignored ({TOKEN_CALIBRATION_FILE}): {e}", dest="LOG")
    return _calibration


def _save_calibration() -> None:
    tmp_path = f"{TOKEN_CALIBRATION_FILE}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "counter": CALIBRATION_COUNTER, "entries": _calibration}, f, indent=2, sort_keys=True)
        os.replace(tmp_path, TOKEN_CALIBRATION_FILE)
    except OSError as e:
        emit_raw("WARNING", f"Token calibration not saved ({TOKEN_CALIBRATION_FILE}): {e}", dest="LOG")


def _valid_entry(static: float, entry: dict | None) -> dict | None:
    """The entry, unless calibration is off or it was learned against a different static prior (the model
    behind the key changed tokenizer, e.g. an alias retargeted, or ANTHROPIC_TOKEN_RATIO changed)."""
    if not entry or not calibration_enabled():
        return None
    prior = entry.get("prior")
    if prior and abs(prior - static) / static > CALIBRATION_PRIOR_DRIFT:
        return None
    return entry


def _can_lower(entry: dict) -> bool:
    return entry["n"] >= CALIBRATION_MIN_SAMPLES_TO_LOWER and entry["raw"] >= CALIBRATION_MIN_RAW_TO_LOWER


def _effective(static: float, entry: dict | None) -> float:
    entry = _valid_entry(static, entry)
    if not entry:
        return static
    low, high = CALIBRATION_RANGE
    learned = min(max(entry["ema"] * CALIBRATION_HEADROOM, static * low), static * high)
    return learned if _can_lower(entry) else max(static, learned)


def token_ratio() -> float:
    """Multiplier from raw tiktoken counts to the active model's tokenizer (static prior, calibrated)."""
    provider, _model, key = _active_key()
    return _effective(_static_ratio(provider, key), _load_calibration().get(key))


def ratio_is_calibrated() -> bool:
    """True once enough real usage (samples and measured text) has been observed for the active
    provider+model, in this or earlier runs."""
    provider, _model, key = _active_key()
    entry = _valid_entry(_static_ratio(provider, key), _load_calibration().get(key))
    return bool(entry) and _can_lower(entry)


def describe_token_ratio() -> str:
    """'1.55 (static)' or '1.61 (calibrated from 12 calls; static 1.55)' for the startup display."""
    provider, _model, key = _active_key()
    static = _static_ratio(provider, key)
    entry = _valid_entry(static, _load_calibration().get(key))
    effective = _effective(static, entry)
    if not entry:
        return get("CFG_TOKEN_RATIO_STATIC", ratio=f"{static:.2f}")
    return get("CFG_TOKEN_RATIO_CALIBRATED", ratio=f"{effective:.2f}", samples=entry["n"], static=f"{static:.2f}")


def observe_prompt_tokens(provider: str, model: str, raw_tokens: int, billed_tokens: int, served_model: str | None = None) -> None:
    """Feed one request's provider-reported prompt tokens (total, including cached) into the calibration.

    Skipped: prompts under CALIBRATION_MIN_RAW raw tokens (fixed framing dominates), raw counts from the
    bytes/3 fallback (not comparable with cl100k), responses served by a different model (server-side
    fallback: another tokenizer), OpenRouter ':online' routes (search results are injected into the prompt
    in transit), and ratios outside OBSERVED_RATIO_BOUNDS. Samples are weighted by size: a size-weighted
    mean until one full-weight sample's worth of text (CALIBRATION_FULL_WEIGHT_RAW), then an EMA — so a
    few small prompts can never outweigh a large one, whatever the order.
    """
    if not calibration_enabled() or raw_tokens < CALIBRATION_MIN_RAW or billed_tokens <= 0:
        return
    if _get_encoding() is None:
        return
    model_id = _model_id(provider, model)
    served = _model_id(provider, served_model or "")
    if served and not (served.startswith(model_id) or model_id.startswith(served)):
        return
    if provider == "OPENROUTER" and ":online" in model_id:
        return
    ratio = billed_tokens / raw_tokens
    if not OBSERVED_RATIO_BOUNDS[0] <= ratio <= OBSERVED_RATIO_BOUNDS[1]:
        return
    key = _key(provider, model)
    static = _static_ratio(provider, key)
    weight = min(raw_tokens / CALIBRATION_FULL_WEIGHT_RAW, 1.0)
    with _calibration_lock:
        calibration = _load_calibration()
        entry = _valid_entry(static, calibration.get(key))
        before = _effective(static, entry)
        if entry is None:
            entry = calibration[key] = {"ema": ratio, "n": 0, "raw": 0, "w": 0.0}
        seen = entry.get("w", 0.0)
        if seen < 1.0:
            entry["ema"] = (entry["ema"] * seen + ratio * weight) / (seen + weight)
        else:
            alpha = CALIBRATION_EMA_WEIGHT * weight
            entry["ema"] = (1 - alpha) * entry["ema"] + alpha * ratio
        entry["w"] = seen + weight
        entry["n"] += 1
        entry["raw"] += raw_tokens
        entry["prior"] = static
        after = _effective(static, entry)
        _save_calibration()
    emit_raw(
        "DEBUG",
        f"TOKEN RATIO | key={key} | observed={ratio:.3f} | ema={entry['ema']:.3f} | samples={entry['n']} | effective {before:.3f} -> {after:.3f}",
        dest="LOG",
    )
    if abs(after - before) / before >= 0.02:
        emit("TOKEN_RATIO_UPDATED", model=model, before=f"{before:.2f}", after=f"{after:.2f}", observed=f"{ratio:.2f}", samples=entry["n"])


def reset_token_calibration(forget_saved: bool = False) -> None:
    """Drop in-memory ratio state (tests, provider switches). forget_saved also ignores the saved file."""
    global _calibration
    _static_ratios.clear()
    _calibration = {} if forget_saved else None


def count_tokens(text: str) -> int:
    """Estimate tokens for the active model: raw tiktoken count x token_ratio()."""
    raw = count_tokens_raw(text)
    if not raw:
        return 0
    ratio = token_ratio()
    return int(raw * ratio) if ratio != 1.0 else raw


def count_tokens_many(texts: list[str]) -> list[int]:
    """count_tokens for many texts (batch-encoded; one ratio lookup)."""
    ratio = token_ratio()
    return [int(raw * ratio) if ratio != 1.0 else raw for raw in count_tokens_raw_many(texts)]


def log_token_estimation(node_name: str, prompt_content: str, max_tokens: int, token_usage: dict | None = None) -> None:
    token_count = count_tokens(prompt_content)
    percentage = (token_count / max_tokens) * 100 if max_tokens else 0

    # Build token usage breakdown suffix for stdout display
    suffix = ""
    usage_log_str = ""
    if token_usage:
        max_label_len = max(len(label) for label in token_usage)
        lines = []
        log_parts = []
        for label, value in token_usage.items():
            pct = (value / token_count * 100) if token_count else 0
            padded_label = label.ljust(max_label_len)
            lines.append(f"\t{padded_label} : {value:,} ({pct:.0f}%)")
            log_parts.append(f"{label}={value:,} ({pct:.0f}%)")
        suffix = "\n" + "\n".join(lines)
        usage_log_str = " | " + " | ".join(log_parts)

    # Console output via emit (styled by CSV LEVEL=WARNING → yellow)
    emit(
        "TOKEN_ANALYTICS",
        suffix=suffix,
        node_name=node_name,
        token_count=f"{token_count:,}",
        max_tokens=f"{max_tokens:,}",
        percentage=f"{percentage:.1f}",
    )

    # Single-line, parseable record in the log file
    emit_raw(
        "DEBUG",
        f"NODE EXEC | node={node_name} | prompt_tokens={token_count:,} / {max_tokens:,} ({percentage:.1f}% capacity) | ratio={token_ratio():.3f}{usage_log_str}",
        dest="LOG",
    )


def emit_step_usage(key: str, step: str, usage: dict) -> None:
    """Emit one per-step usage row (LLM_USAGE_STEP / LLM_STEP_SUBTOTAL) from llm_common.get_step_summary()."""
    estimate = usage.get("estimated_input", 0)
    billed = usage.get("input", 0)
    deviation = f"{(billed - estimate) / estimate:+.0%}" if estimate and usage.get("calls") else get("CFG_VALUE_UNKNOWN")
    emit(
        key,
        step=step,
        calls=f"{usage.get('calls', 0):,}",
        cache_hits=f"{usage.get('cache_hits', 0):,}",
        input=f"{billed:,}",
        estimate=f"{estimate:,}",
        deviation=deviation,
        output=f"{usage.get('output', 0):,}",
        thinking=f"{usage.get('thinking', 0):,}",
        cost=format_cost(usage),
    )


def format_cost(usage: dict) -> str:
    """'$1.23', '$0.0041' (sub-cent costs keep 4 decimals), '>= $1.23 (2 calls unpriced)' or n/a."""
    cost = usage.get("cost", 0.0)
    amount = f"${cost:.4f}" if 0 < cost < 0.01 else f"${cost:.2f}"
    unpriced = usage.get("unpriced_calls", 0)
    priced = usage.get("calls", 0) - unpriced
    if not unpriced:
        return amount
    if priced <= 0:
        return get("CFG_VALUE_UNKNOWN")
    return get("LLM_USAGE_COST_PARTIAL", cost=amount, unpriced=unpriced)
