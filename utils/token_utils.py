import logging

import tiktoken

from utils.llm_config import (
    CONTEXT_MARGIN,
    context_output_reserve,
    get_model_context_length,
    get_token_ratio,
    resolve_llm_settings,
)
from utils.output import emit

# Get the shared logger from call_llm module
logger = logging.getLogger("llm_logger")

# Output tokens reserved on providers that do not size output (OLLAMA / other endpoints): 5%, clamped.
MIN_OUTPUT_RESERVE = 8_192
MAX_OUTPUT_RESERVE = 64_000


def resolve_max_tokens(shared):
    """Resolve max_tokens from shared store or auto-detect from the active provider."""
    max_tokens = shared.get("max_tokens")
    if max_tokens is not None:
        return max_tokens
    _, model_name, endpoint, api_key = resolve_llm_settings()
    max_tokens_val = get_model_context_length(endpoint, model_name, api_key)
    from utils.output import emit_raw

    emit_raw("DEBUG", f"resolve_max_tokens | resolved max_tokens={max_tokens_val:,}", dest="LOG")
    return max_tokens_val


def input_token_budget(max_tokens: int, thinking_level: str | None = None) -> int:
    """Largest prompt size (in count_tokens() units) that still leaves room for the response.

    On ANTHROPIC and OPENROUTER the context window holds prompt + output: reserve exactly what the
    provider module will request for this thinking level (llm_config.context_output_reserve —
    thinking tokens count toward output) plus the same flat margin, so a prompt packed to this budget
    still gets its planned output. GEMINI's input limit is separate from its output limit, so only the
    margin is reserved. Elsewhere (OLLAMA, or an OpenRouter model missing from the catalog) reserve 5%
    (min 8K, max 64K) — identical to the historical 95% rule on 1M-token models.
    """
    planned = context_output_reserve(thinking_level)
    if planned is not None:
        reserve = planned + CONTEXT_MARGIN
    else:
        reserve = min(max(int(max_tokens * 0.05), MIN_OUTPUT_RESERVE), MAX_OUTPUT_RESERVE)
    return max(max_tokens - reserve, max_tokens // 2)


# Lazy-loaded tiktoken encoding and model token ratio (singletons)
_encoding = None
_token_ratio = None


def _get_encoding():
    global _encoding
    if _encoding is None:
        try:
            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoding = None
    return _encoding


def count_tokens_raw(text: str) -> int:
    """Count tokens with tiktoken (cl100k_base), with fallback to chars/4. No model calibration."""
    if not text:
        return 0
    enc = _get_encoding()
    if enc:
        return len(enc.encode(text, disallowed_special=()))
    return len(text) // 4


def count_tokens(text: str) -> int:
    """Estimate tokens for the active model: tiktoken count x llm_config.get_token_ratio() (per model family)."""
    global _token_ratio
    raw = count_tokens_raw(text)
    if not raw:
        return 0
    if _token_ratio is None:
        _token_ratio = get_token_ratio()
    return int(raw * _token_ratio) if _token_ratio != 1.0 else raw


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

    # File log stays single-line for parseability (structured, not translatable)
    logger.info(f"NODE EXEC | node={node_name} | prompt_tokens={token_count:,} / {max_tokens:,} ({percentage:.1f}% capacity){usage_log_str}")
