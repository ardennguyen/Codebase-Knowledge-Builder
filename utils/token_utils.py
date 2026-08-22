import logging

import tiktoken

# Get the shared logger from call_llm module
logger = logging.getLogger("llm_logger")

# Lazy-loaded tiktoken encoding (singleton)
_encoding = None


def _get_encoding():
    global _encoding
    if _encoding is None:
        try:
            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoding = None
    return _encoding


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken, with fallback to chars/4."""
    if not text:
        return 0
    enc = _get_encoding()
    if enc:
        return len(enc.encode(text))
    return len(text) // 4


def log_token_estimation(node_name: str, prompt_content: str, max_tokens: int, token_usage: dict | None = None) -> None:
    token_count = count_tokens(prompt_content)
    percentage = (token_count / max_tokens) * 100 if max_tokens else 0

    # Build token usage string if provided
    usage_str = ""
    if token_usage:
        parts = []
        for label, value in token_usage.items():
            pct = (value / token_count * 100) if token_count else 0
            parts.append(f"{label}={value:,} ({pct:.0f}%)")
        usage_str = " | " + " | ".join(parts)

    # Console output (yellow) with token usage
    print(f"\033[93m[Token Analytics] {node_name}: {token_count:,} / {max_tokens:,} tokens ({percentage:.1f}% capacity){usage_str}\033[0m")

    # File log with node context and token usage
    logger.info(f"NODE EXEC | node={node_name} | prompt_tokens={token_count:,} / {max_tokens:,} ({percentage:.1f}% capacity){usage_str}")
