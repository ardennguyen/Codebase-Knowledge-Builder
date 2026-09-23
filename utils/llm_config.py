"""Model configuration and context-length resolution.

Extracted from call_llm.py to break the circular dependency between
call_llm ↔ token_utils. Both modules now import from this one instead
of from each other.

resolve_llm_settings() is the single source of truth for provider, model,
endpoint and API key — main.py, token_utils.py and call_llm.py all use it.
check_anthropic_auth() is the ANTHROPIC credential preflight (no SDK import).
"""

import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time

import requests

DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"
DEFAULT_GEMINI_LOCATION = "global"  # Vertex: Gemini 3.x is served from global / us / eu, not us-central1
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_ANTHROPIC_ENDPOINT = "https://api.anthropic.com"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api"

# Planned max output tokens per thinking level (thinking counts toward output on every
# provider). The same numbers size the prompt budget (token_utils.input_token_budget), so a
# prompt packed to the budget still gets its planned output. None = model default effort.
OUTPUT_TOKENS_BY_EFFORT = {
    None: 64_000,
    "minimal": 32_000,
    "low": 32_000,
    "medium": 64_000,
    "high": 64_000,
    "xhigh": 96_000,
    "max": 128_000,
}
ANTHROPIC_MAX_TOKENS_BY_EFFORT = OUTPUT_TOKENS_BY_EFFORT  # Claude uses the shared table as-is
# Flat safety margin (tokens) between prompt + max_tokens and the context window.
CONTEXT_MARGIN = 2_000
ANTHROPIC_CONTEXT_MARGIN = CONTEXT_MARGIN

# --- Claude model families (native API and gateway IDs after _normalize_claude_id) ---
# Adaptive thinking + output_config.effort; anything else (Haiku 4.5, 4.5 and older) uses budget_tokens.
ANTHROPIC_ADAPTIVE_PREFIXES = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-",
    "claude-mythos-",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)
ANTHROPIC_NO_XHIGH_PREFIXES = ("claude-opus-4-6", "claude-sonnet-4-6")  # 4.6 predates xhigh
# Think adaptively even when `thinking` is omitted (4.6-4.8 do not).
ANTHROPIC_THINKING_BY_DEFAULT_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-", "claude-mythos-")
# Reject temperature/top_p/top_k (400).
_NO_SAMPLING_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5", "claude-fable", "claude-mythos")
# Tokenizer introduced with Opus 4.7: ~1.0-1.35x the tokens of the 4.6-and-older tokenizer.
_NEW_TOKENIZER_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5", "claude-fable", "claude-mythos")
# tiktoken (cl100k) → Claude token multipliers; calibrate with ANTHROPIC_TOKEN_RATIO using the
# observed_token_ratio in the debug log.
CLAUDE_TOKEN_RATIO_NEW_TOKENIZER = 1.4
CLAUDE_TOKEN_RATIO_OLD_TOKENIZER = 1.2
DEFAULT_CLAUDE_TOKEN_RATIO = CLAUDE_TOKEN_RATIO_NEW_TOKENIZER

# --- Gemini model families (native API; OpenRouter google/* IDs are catalog-driven) ---
# Gemini 3.x: ThinkingConfig.thinking_level; allowed levels differ per model (longest prefix wins).
# Sending thinking_level together with thinking_budget is a 400; thinking_level on pre-3 models errors.
GEMINI_THINKING_LEVELS = (
    ("gemini-3.8-flash", ("low", "medium", "high")),
    ("gemini-3.7-flash", ("low", "medium", "high")),
    ("gemini-3.6-flash", ("minimal", "low", "medium", "high")),
    ("gemini-3.5-flash", ("minimal", "low", "medium", "high")),  # also gemini-3.5-flash-lite
    ("gemini-3.1-pro", ("low", "medium", "high")),  # thinking cannot be turned off
    ("gemini-3.1-flash-lite", ("minimal", "low", "medium", "high")),
    ("gemini-3-pro", ("low", "medium", "high")),  # AI Studio serves 3.1 Pro under this retired id
    ("gemini-3-flash", ("minimal", "low", "medium", "high")),
)
GEMINI_3_DEFAULT_LEVELS = ("low", "medium", "high")  # every documented 3.x text model accepts these
# Gemini 2.5 (legacy fallback): ThinkingConfig.thinking_budget. (prefix, min, max, can_disable)
GEMINI_BUDGET_RANGES = (
    ("gemini-2.5-flash-lite", 512, 24_576, True),
    ("gemini-2.5-flash", 1, 24_576, True),
    ("gemini-2.5-pro", 128, 32_768, False),
)
GEMINI_THINKING_BUDGETS = {"minimal": 512, "low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 24576}
GEMINI_DEFAULT_LIMITS = (1_048_576, 65_536)  # every Gemini 3.x / 2.5 text model: input, output
# Gemini output budget per level (the model cap is 65,536 incl. thinking).
GEMINI_OUTPUT_TOKENS_BY_EFFORT = {None: 65_536, "minimal": 32_768, "low": 32_768, "medium": 65_536, "high": 65_536, "xhigh": 65_536, "max": 65_536}
# Shut-down ids → (replacement, still served under the old id on AI Studio).
GEMINI_RETIRED_MODELS = {
    "gemini-3-pro-preview": ("gemini-3.1-pro-preview", True),  # AI Studio routes it to 3.1 Pro Preview
    "gemini-3.1-flash-lite-preview": ("gemini-3.1-flash-lite", False),
}
# Vertex AI locations serving each Gemini 3.x family (longest prefix wins; None = regional endpoints too).
GEMINI_VERTEX_LOCATIONS = (
    ("gemini-3.8-flash-cyber", ("global", "us")),
    ("gemini-3.5-flash-lite", ("global", "us", "eu")),
    ("gemini-3.5-flash", None),
    ("gemini-3.1-pro", ("global",)),
    ("gemini-3-flash", ("global",)),
    ("gemini-3-pro", ("global",)),
)
GEMINI_3_VERTEX_LOCATIONS = ("global", "us", "eu")
# Claude pre-adaptive models (Haiku 4.5 and older): thinking.budget_tokens per level; max_tokens = budget + 16K.
ANTHROPIC_BUDGET_BY_LEVEL = {"low": 2_048, "medium": 8_192, "high": 16_384, "xhigh": 24_576, "max": 32_000}
ANTHROPIC_BUDGET_REPLY_TOKENS = 16_000
ANTHROPIC_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def _env_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


def anthropic_output_cap() -> int | None:
    """ANTHROPIC_MAX_OUTPUT_TOKENS as an int, or None when unset/invalid."""
    return _env_int("ANTHROPIC_MAX_OUTPUT_TOKENS")


def anthropic_output_budget(thinking_level: str | None) -> int:
    """Per-effort table value capped by ANTHROPIC_MAX_OUTPUT_TOKENS (adaptive models)."""
    level = thinking_level.lower() if thinking_level else None
    budget = ANTHROPIC_MAX_TOKENS_BY_EFFORT.get(level, ANTHROPIC_MAX_TOKENS_BY_EFFORT[None])
    cap = anthropic_output_cap()
    return min(budget, cap) if cap else budget


def anthropic_effort(model: str, level: str | None) -> str | None:
    """Thinking level → effort the model accepts: minimal → low, xhigh → high on the 4.6 family,
    unknown values → None (model default)."""
    if not level:
        return None
    level = level.lower()
    if level == "minimal":
        level = "low"
    if level not in ANTHROPIC_EFFORT_LEVELS:
        return None
    if level == "xhigh" and (model or "").lower().startswith(ANTHROPIC_NO_XHIGH_PREFIXES):
        return "high"
    return level


def anthropic_planned_output(model: str, thinking_level: str | None) -> int:
    """Claude max_tokens the request will plan for (before the model/context ceiling): the per-effort
    table on adaptive models, budget_tokens + 16K on pre-adaptive ones (Haiku 4.5), capped by
    ANTHROPIC_MAX_OUTPUT_TOKENS. Shared by llm_anthropic and token_utils.input_token_budget."""
    effort = anthropic_effort(model, thinking_level)
    if (model or "").lower().startswith(ANTHROPIC_ADAPTIVE_PREFIXES):
        return anthropic_output_budget(effort)
    planned = ANTHROPIC_BUDGET_BY_LEVEL.get(effort, 0) + ANTHROPIC_BUDGET_REPLY_TOKENS
    cap = anthropic_output_cap()
    return min(planned, cap) if cap else planned


def gemini_thinking_mode(model: str) -> tuple[str, object]:
    """('level', allowed_levels) for Gemini 3.x, ('budget', (min, max, can_disable)) for 2.5,
    ('none', None) for models without a thinking control the project maps."""
    name = gemini_model_id(model)
    for prefix, low, high, can_disable in GEMINI_BUDGET_RANGES:
        if name.startswith(prefix):
            return "budget", (low, high, can_disable)
    if not name.startswith("gemini-") or name.startswith(("gemini-1", "gemini-2")):
        return "none", None  # 1.x / 2.0, other 2.5 variants (image, live, TTS) and non-Gemini ids
    for prefix, levels in GEMINI_THINKING_LEVELS:
        if name.startswith(prefix):
            return "level", levels
    # Other 3.x ids, '-latest' aliases (gemini-flash-latest, gemini-pro-latest) and newer families:
    # the level set every documented 3.x model accepts (a model that rejects it is handled at runtime).
    return "level", GEMINI_3_DEFAULT_LEVELS


def gemini_model_id(model: str) -> str:
    """'models/gemini-3.7-flash' / 'publishers/google/models/gemini-3.7-flash' → 'gemini-3.7-flash'."""
    return (model or "").strip().lower().rsplit("/", 1)[-1]


def gemini_vertex_locations(model: str) -> tuple | None:
    """Vertex AI locations that serve a Gemini 3.x model (None = any, including regional endpoints)."""
    name = gemini_model_id(model)
    for prefix, locations in GEMINI_VERTEX_LOCATIONS:
        if name.startswith(prefix):
            return locations
    return GEMINI_3_VERTEX_LOCATIONS if name.startswith("gemini-3") else None


def gemini_output_budget(thinking_level: str | None, output_limit: int | None = None) -> int:
    """Planned Gemini max_output_tokens: per-level table, capped by the model output limit and
    GEMINI_MAX_OUTPUT_TOKENS. Shared by llm_gemini (request) and token_utils (prompt budget)."""
    level = thinking_level.lower() if thinking_level else None
    budget = GEMINI_OUTPUT_TOKENS_BY_EFFORT.get(level, GEMINI_OUTPUT_TOKENS_BY_EFFORT[None])
    budget = min(budget, output_limit or GEMINI_DEFAULT_LIMITS[1])
    cap = _env_int("GEMINI_MAX_OUTPUT_TOKENS")
    return min(budget, cap) if cap else budget


def openrouter_output_budget(model: str, thinking_level: str | None) -> int | None:
    """Planned OpenRouter max_tokens: shared per-effort table, capped by the catalog's
    top_provider.max_completion_tokens and OPENROUTER_MAX_OUTPUT_TOKENS. None when the model is not
    in the catalog (unknown limits, e.g. a non-OpenRouter proxy): max_tokens is then omitted."""
    info = openrouter_model_info(model)
    if info is None:
        return _env_int("OPENROUTER_MAX_OUTPUT_TOKENS")
    level = thinking_level.lower() if thinking_level else None
    budget = OUTPUT_TOKENS_BY_EFFORT.get(level, OUTPUT_TOKENS_BY_EFFORT[None])
    model_cap = (info.get("top_provider") or {}).get("max_completion_tokens")
    budget = min(budget, model_cap) if model_cap else min(budget, 32_000)
    cap = _env_int("OPENROUTER_MAX_OUTPUT_TOKENS")
    return min(budget, cap) if cap else budget


def context_output_reserve(thinking_level: str | None) -> int | None:
    """Output tokens that share the context window with the prompt, for the active provider.
    ANTHROPIC / OPENROUTER: the planned max_tokens (thinking included). GEMINI: 0 — Gemini's input and
    output limits are separate. None: the provider does not size output (5% reserve in token_utils)."""
    provider, model, _, _ = resolve_llm_settings()
    if provider == "ANTHROPIC":
        return anthropic_planned_output(model, thinking_level)
    if provider == "GEMINI":
        return 0
    if provider == "OPENROUTER":
        return openrouter_output_budget(model, thinking_level)
    return None


def get_llm_provider() -> str | None:
    """Determine the LLM provider from environment variables.

    Explicit LLM_PROVIDER wins; otherwise Gemini credentials select GEMINI (legacy default).
    ANTHROPIC is never auto-selected: ANTHROPIC_API_KEY is often exported globally for other
    tools (e.g. Claude Code), and a silent switch to a paid Opus run would be surprising.
    """
    provider = os.getenv("LLM_PROVIDER")
    if provider:
        return provider.strip().upper()
    if os.getenv("GEMINI_PROJECT_ID") or os.getenv("GEMINI_API_KEY"):
        return "GEMINI"
    return None


def gemini_location() -> str:
    """GEMINI_LOCATION lower-cased: google-genai matches 'global' / 'us' / 'eu' case-sensitively."""
    return (os.getenv("GEMINI_LOCATION") or DEFAULT_GEMINI_LOCATION).strip().lower()


def openrouter_base_url() -> str:
    """OPENROUTER_BASE_URL without a trailing '/' or '/v1' (OpenAI SDK style); paths add '/v1/...'."""
    base = (os.getenv("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL).strip().rstrip("/")
    return base.removesuffix("/v1")


def is_openrouter_host() -> bool:
    return "openrouter.ai" in openrouter_base_url().lower()


def resolve_llm_settings() -> tuple[str, str, str, str]:
    """Return (provider, model_name, endpoint_url, api_key) for the active provider."""
    provider = get_llm_provider()
    if provider == "GEMINI":
        model = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        if os.getenv("GEMINI_PROJECT_ID"):
            location = gemini_location().lower()
            if location == "global":
                host = "aiplatform.googleapis.com"
            elif location in ("us", "eu"):
                host = f"aiplatform.{location}.rep.googleapis.com"  # multi-region endpoints
            else:
                host = f"{location}-aiplatform.googleapis.com"
            return provider, model, host, ""
        return provider, model, "generativelanguage.googleapis.com", os.getenv("GEMINI_API_KEY", "")
    if provider == "ANTHROPIC":
        endpoint = os.getenv("ANTHROPIC_BASE_URL") or DEFAULT_ANTHROPIC_ENDPOINT
        return provider, os.getenv("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL, endpoint, os.getenv("ANTHROPIC_API_KEY", "")
    if provider == "OPENROUTER":
        return provider, os.getenv("OPENROUTER_MODEL", "unknown"), openrouter_base_url(), os.getenv("OPENROUTER_API_KEY", "")
    if provider:
        return (
            provider,
            os.getenv(f"{provider}_MODEL", "unknown"),
            os.getenv(f"{provider}_BASE_URL", "unknown"),
            os.getenv(f"{provider}_API_KEY", ""),
        )
    return "UNKNOWN", "unknown", "unknown", ""


_CLAUDE_VERSION_FIRST = re.compile(r"claude-(\d+)(?:-(\d+))?-(opus|sonnet|haiku|fable|mythos)")


def _normalize_claude_id(model_name: str) -> str:
    """Gateway/cloud IDs → bare family-first Claude ID: 'anthropic/claude-opus-4.7',
    'bedrock/us.anthropic.claude-opus-4-7-v1:0' and the version-first alias
    'anthropic/claude-4.7-opus-20260416' all → 'claude-opus-4-7...'."""
    name = (model_name or "").lower().replace(".", "-")
    start = name.find("claude-")
    name = name[start:] if start >= 0 else name
    match = _CLAUDE_VERSION_FIRST.match(name)
    if match:
        major, minor, family = match.groups()
        name = f"claude-{family}-{major}" + (f"-{minor}" if minor else "") + name[match.end() :]
    return name


def _catalog_model_id(model_name: str) -> str:
    """On OPENROUTER, resolve aliases ('~anthropic/claude-opus-latest', canonical slugs) through the
    catalog so family checks see the real model; other providers use the name as given."""
    if get_llm_provider() == "OPENROUTER":
        info = openrouter_model_info(model_name)
        if info and info.get("id"):
            return info["id"]
    return model_name or ""


def is_claude_model(provider: str | None, model_name: str) -> bool:
    """True for native Anthropic calls and Claude models reached through a gateway (e.g. OpenRouter)."""
    return provider == "ANTHROPIC" or _normalize_claude_id(model_name).startswith("claude-")


def is_gemini_model(provider: str | None, model_name: str) -> bool:
    return provider == "GEMINI" or "gemini-" in (model_name or "").lower()


def rejects_sampling_params(model_name: str) -> bool:
    """True for models that reject or ignore temperature/top_p/top_k: Claude Opus 4.7+, Opus/Sonnet 5,
    Fable, Mythos (400), and Gemini 3.x (deprecated; ignored or erroring on some endpoints)."""
    name = _catalog_model_id(model_name)
    return _normalize_claude_id(name).startswith(_NO_SAMPLING_PREFIXES) or "gemini-3" in name.lower()


def _ratio_from_env(name: str, default: float) -> float:
    try:
        ratio = float(os.getenv(name, default))
    except ValueError:
        ratio = default
    return max(ratio, 0.5)


def get_token_ratio() -> float:
    """Multiplier from tiktoken (cl100k) counts to the active model's tokenizer.

    tiktoken undercounts Claude tokens (more so on code), so budgets computed with raw counts can
    overflow the real context window. Claude: ANTHROPIC_TOKEN_RATIO, default 1.4 for the tokenizer
    introduced with Opus 4.7 and 1.2 for 4.6 and older. Gemini: GEMINI_TOKEN_RATIO (default 1.0).
    Others: LLM_TOKEN_RATIO (default 1.0). Compare with observed_token_ratio in the debug log.
    """
    provider, model_name, _, _ = resolve_llm_settings()
    model_name = _catalog_model_id(model_name)
    if is_claude_model(provider, model_name):
        claude_id = _normalize_claude_id(model_name) if provider != "ANTHROPIC" else model_name.lower()
        default = CLAUDE_TOKEN_RATIO_NEW_TOKENIZER if claude_id.startswith(_NEW_TOKENIZER_PREFIXES) else CLAUDE_TOKEN_RATIO_OLD_TOKENIZER
        return max(_ratio_from_env("ANTHROPIC_TOKEN_RATIO", default), 1.0)
    if is_gemini_model(provider, model_name):
        return _ratio_from_env("GEMINI_TOKEN_RATIO", 1.0)
    return _ratio_from_env("LLM_TOKEN_RATIO", 1.0)


# ---------------------------------------------------------------------------
# OpenRouter model catalog (GET {base}/v1/models)
# ---------------------------------------------------------------------------
# Failed fetches are never cached: a transient blip at startup must not degrade the whole run.
# After a failure the catalog is retried once the cooldown has passed (callers get None meanwhile).
_openrouter_models_cache = None
_openrouter_last_failure = 0.0
_OPENROUTER_RETRY_COOLDOWN = 60.0
_OPENROUTER_ROUTING_SUFFIXES = (":nitro", ":floor", ":online", ":thinking", ":extended", ":exacto")


def openrouter_catalog() -> list | None:
    """The model catalog, or None when it could not be fetched (yet)."""
    global _openrouter_models_cache, _openrouter_last_failure
    if _openrouter_models_cache is not None:
        return _openrouter_models_cache
    if _openrouter_last_failure and time.time() - _openrouter_last_failure < _OPENROUTER_RETRY_COOLDOWN:
        return None
    url = f"{openrouter_base_url()}/v1/models"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("data")
        if not isinstance(data, list):
            raise ValueError("OpenRouter model catalog response has no 'data' list")
        _openrouter_models_cache = data
        return data
    except Exception as e:
        from utils.llm_common import warn_once
        from utils.output import emit, emit_raw

        _openrouter_last_failure = time.time()
        emit_raw("WARNING", f"Failed to fetch OpenRouter model info from {url}: {e}", dest="LOG")
        if warn_once("openrouter_catalog_unavailable"):
            emit("WARN_OPENROUTER_CATALOG_UNAVAILABLE", url=url, error=str(e)[:200])
        return None


def openrouter_model_info(model_id: str) -> dict | None:
    """Catalog entry for a model id: exact id, canonical_slug, routing-suffix variant
    (':nitro', ':floor', ...), dated canonical slug (e.g. 'anthropic/claude-4.6-opus' →
    'anthropic/claude-4.6-opus-20260205'), or a '~...-latest' alias's target."""
    catalog = openrouter_catalog()
    if not catalog or not model_id:
        return None
    wanted = model_id.strip()
    candidates = [wanted, *(wanted[: -len(suffix)] for suffix in _OPENROUTER_ROUTING_SUFFIXES if wanted.endswith(suffix))]
    for name in candidates:
        entry = next((m for m in catalog if m.get("id") == name or m.get("canonical_slug") == name), None)
        if entry is None:
            # Dated canonical slug only ('anthropic/claude-4.6-opus' → '…-20260205'): a looser prefix
            # match would map typos such as 'google/gemini-3.1-pro' onto a different model.
            dated = re.compile(re.escape(name) + r"-\d{8}")
            entry = next((m for m in catalog if dated.fullmatch(str(m.get("canonical_slug", "")))), None)
        if entry is not None:
            target = (entry.get("alias_target") or {}).get("slug")
            if target and target != entry.get("id"):
                return next((m for m in catalog if m.get("id") == target or m.get("canonical_slug") == target), entry)
            return entry
    return None


_get_openrouter_model_info = openrouter_model_info  # backward-compatible name


def get_model_context_length(endpoint_url: str, model_name: str, api_key: str = "") -> int:
    """
    Maximum context length (input tokens) of the active model.
    ANTHROPIC: Anthropic Models API (max_input_tokens), offline fallback table.
    GEMINI: models.get(input_token_limit) on AI Studio, static 1,048,576 (Vertex, or no SDK).
    OPENROUTER: catalog top_provider.context_length, else context_length.
    Other endpoints: 100,000.
    """
    default_limit = 100000
    provider = get_llm_provider()
    try:
        if provider == "ANTHROPIC":
            from utils.llm_anthropic import get_model_limits

            return get_model_limits(model_name)[0]

        if provider == "OPENROUTER" or "openrouter.ai" in (endpoint_url or ""):
            info = openrouter_model_info(model_name)
            if info:
                return (info.get("top_provider") or {}).get("context_length") or info.get("context_length") or default_limit
            return default_limit

        if provider == "GEMINI":
            try:
                from utils.llm_gemini import get_model_limits as gemini_limits
            except ImportError:
                return GEMINI_DEFAULT_LIMITS[0]
            return gemini_limits(model_name)[0]

        if not endpoint_url:
            return default_limit
        if "generativelanguage.googleapis.com" in endpoint_url or "gemini" in model_name.lower():
            return GEMINI_DEFAULT_LIMITS[0]
    except Exception as e:
        from utils.output import emit

        emit("WARN_CONTEXT_LENGTH_FETCH", model=model_name, endpoint=endpoint_url, error=str(e))

    return default_limit


def _ui(key: str, **kwargs) -> str:
    from utils.output import get

    return get(key, **kwargs)


def describe_thinking_support(provider: str, model: str) -> str:
    """One-line description of how thinking levels are applied for the startup display."""
    if provider == "ANTHROPIC":
        name = (model or "").lower()
        if not name.startswith(ANTHROPIC_ADAPTIVE_PREFIXES):
            return "thinking.budget_tokens (low…max → 2,048…32,000)"
        levels = "low, medium, high, max" if name.startswith(ANTHROPIC_NO_XHIGH_PREFIXES) else "low, medium, high, xhigh, max"
        return f"adaptive thinking + output_config.effort ∈ {{{levels}}}"
    if provider == "GEMINI":
        mode, spec = gemini_thinking_mode(model)
        if mode == "level":
            return f"thinking_level ∈ {{{', '.join(spec)}}}"
        if mode == "budget":
            low, high, can_disable = spec
            return f"thinking_budget {low:,}-{high:,}" + (f" ({_ui('CFG_THINKING_BUDGET_OFF')})" if can_disable else "")
        return "—"
    if provider == "OPENROUTER":
        info = openrouter_model_info(model)
        if info is None:
            return f"reasoning.effort ({_ui('CFG_THINKING_CATALOG_UNAVAILABLE')})" if not openrouter_catalog() else "—"
        reasoning = info.get("reasoning")
        if not isinstance(reasoning, dict):
            return "reasoning.effort" if "reasoning" in (info.get("supported_parameters") or []) else "—"
        efforts = reasoning.get("supported_efforts")
        if "supported_efforts" not in reasoning and reasoning.get("supports_max_tokens"):
            text = "reasoning.max_tokens (minimal…max → 1,024…32,000)"  # llm_openrouter._REASONING_BUDGETS
        elif efforts:
            text = f"reasoning.effort ∈ {{{', '.join(e for e in efforts if e != 'none')}}}"
        else:
            text = "reasoning.effort"
        extras = [_ui("CFG_THINKING_DEFAULT_EFFORT", effort=reasoning["default_effort"])] if reasoning.get("default_effort") else []
        if reasoning.get("mandatory"):
            extras.append(_ui("CFG_THINKING_MANDATORY"))
        return text + (f" · {' · '.join(extras)}" if extras else "")
    return "—"


# ---------------------------------------------------------------------------
# ANTHROPIC credential preflight
# ---------------------------------------------------------------------------
# The anthropic SDK resolves credentials itself (ANTHROPIC_API_KEY → ANTHROPIC_AUTH_TOKEN →
# `ant auth login` profile → Workload Identity Federation). An empty variable counts as unset.
# This preflight runs before any LLM call so a missing login fails fast with instructions
# instead of after crawling and 5 node retries.
_FEDERATION_VARS = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID")
_TOKEN_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]*(?:\.\.\.)?")


def _env_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _anthropic_sdk_installed() -> bool:
    try:
        return importlib.util.find_spec("anthropic") is not None
    except (ImportError, ValueError):  # ValueError: module already imported without a spec
        return "anthropic" in sys.modules


def _anthropic_config_dir() -> str:
    """Directory where `ant auth login` stores profiles (ANTHROPIC_CONFIG_DIR or the OS default)."""
    if os.getenv("ANTHROPIC_CONFIG_DIR"):
        return os.environ["ANTHROPIC_CONFIG_DIR"]
    if os.name == "nt":
        return os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "Anthropic")
    return os.path.join(os.path.expanduser("~"), ".config", "anthropic")


def _redact(text: str) -> str:
    """Mask token prefixes that `ant auth status` prints (e.g. sk-ant-oat01-EXA...)."""
    return _TOKEN_PATTERN.sub("sk-ant-***", text)


def parse_ant_auth_status(output: str) -> tuple[str | None, str | None]:
    """Return (active credential, active workspace) from `ant auth status` output.

    The command's exit code is not a health signal, so read its `(active)` rows instead:
        Credentials
          (active) * Profile (user_oauth) [via active_config]       sk-ant-oat01-EXA...
        Workspace
          (active) * Workspace                                      wrkspc_01... (Engineering)
    """
    section, credential, workspace = None, None, None
    for line in output.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            header = line.strip().lower()
            section = header if header in ("credentials", "workspace") else None
            continue
        if "(active)" not in line:
            continue
        text = re.sub(r"\s{2,}", " ", _redact(re.sub(r"^\s*\(active\)\s*\*?\s*", "", line))).strip()
        if section == "workspace":
            workspace = workspace or text
        else:
            credential = credential or text
    return credential, workspace


def _emit_auth_help(ant_installed: bool) -> None:
    """Print how to authenticate: an API key, or `ant auth login` (installing ant if needed)."""
    from utils.output import emit

    emit("ANTHROPIC_AUTH_HELP_HEADER")
    emit("ANTHROPIC_AUTH_HELP_KEY")
    if not ant_installed:
        platform = "WIN" if os.name == "nt" else "MAC" if sys.platform == "darwin" else "LINUX"
        emit(f"ANTHROPIC_AUTH_HELP_INSTALL_ANT_{platform}")
    emit("ANTHROPIC_AUTH_HELP_LOGIN")
    emit("ANTHROPIC_AUTH_HELP_NOTE")


def check_anthropic_auth() -> bool:
    """Preflight for LLM_PROVIDER=ANTHROPIC. Returns False (after printing instructions) when
    the run cannot authenticate; True otherwise, including for every other provider.

    Order: anthropic package installed → ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN →
    Workload Identity Federation env vars → `ant auth status` (active login profile) →
    stored login files when the `ant` CLI is not installed.
    """
    from utils.output import emit, emit_raw

    if get_llm_provider() != "ANTHROPIC":
        return True
    if not _anthropic_sdk_installed():
        emit("ERROR_ANTHROPIC_SDK_MISSING")
        return False

    if _env_set("ANTHROPIC_API_KEY") and _env_set("ANTHROPIC_AUTH_TOKEN"):
        emit("WARN_ANTHROPIC_KEY_AND_TOKEN")
    if _env_set("ANTHROPIC_API_KEY"):
        emit("ANTHROPIC_AUTH_OK", source="ANTHROPIC_API_KEY")
        return True
    if _env_set("ANTHROPIC_AUTH_TOKEN"):
        emit("ANTHROPIC_AUTH_OK", source="ANTHROPIC_AUTH_TOKEN")
        return True
    if all(_env_set(v) for v in _FEDERATION_VARS) and (_env_set("ANTHROPIC_IDENTITY_TOKEN_FILE") or _env_set("ANTHROPIC_IDENTITY_TOKEN")):
        emit("ANTHROPIC_AUTH_OK", source="Workload Identity Federation")
        return True

    # No key: the SDK falls back to an `ant auth login` profile. Verify one is active.
    ant = shutil.which("ant")
    if not ant:
        stored = sorted(glob.glob(os.path.join(_anthropic_config_dir(), "credentials", "*.json")))
        if stored:
            emit("WARN_ANTHROPIC_ANT_MISSING_LOGIN_FOUND", path=stored[0])
            return True
        emit("ERROR_ANTHROPIC_NO_CREDENTIALS")
        _emit_auth_help(ant_installed=False)
        return False

    # Run with the same environment the SDK will see; empty key variables are dropped so the
    # CLI reports the profile the SDK will actually use (the SDK treats empty as unset).
    env = {k: v for k, v in os.environ.items() if not (k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") and not v.strip())}
    try:
        result = subprocess.run([ant, "auth", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        emit("WARN_ANTHROPIC_AUTH_UNVERIFIED", error=str(e))
        return True

    output = f"{result.stdout}\n{result.stderr}"
    credential, workspace = parse_ant_auth_status(output)
    emit_raw("DEBUG", f"ant auth status | exit={result.returncode}\n{_redact(output).strip()}", dest="LOG")
    if not credential:
        emit("ERROR_ANTHROPIC_NOT_LOGGED_IN")
        details = _redact(output).strip()
        if details:
            emit_raw("INFO", "\n".join(f"    {line}" for line in details.splitlines()))
        _emit_auth_help(ant_installed=True)
        return False

    source = _ui("AUTH_SOURCE_ANT_LOGIN", credential=credential)
    if workspace:
        source += f" | {_ui('AUTH_SOURCE_WORKSPACE', workspace=workspace)}"
    emit("ANTHROPIC_AUTH_OK", source=source)
    return True


# ---------------------------------------------------------------------------
# GEMINI / OPENROUTER preflight + dispatcher
# ---------------------------------------------------------------------------
# thinking_level MINIMAL/MEDIUM arrived in google-genai 1.56.0 (1.51.0 had LOW/HIGH only);
# older SDKs reject thinking_level with a pydantic validation error.
GEMINI_MIN_SDK = (1, 56, 0)


def _installed_version(dist: str) -> tuple[int, ...] | None:
    from importlib import metadata

    try:
        raw = metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None
    parts = []
    for piece in raw.split(".")[:3]:
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts)


def check_gemini_config() -> bool:
    """Preflight for LLM_PROVIDER=GEMINI (or Gemini credentials without LLM_PROVIDER)."""
    from utils.output import emit

    model = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    version = _installed_version("google-genai")
    if version is None:
        emit("ERROR_GEMINI_SDK_MISSING")
        return False
    if version < GEMINI_MIN_SDK:
        emit("ERROR_GEMINI_SDK_OUTDATED", version=".".join(map(str, version)), required=".".join(map(str, GEMINI_MIN_SDK)))
        return False

    retired = GEMINI_RETIRED_MODELS.get(gemini_model_id(model))
    if retired:
        replacement, aliased_on_ai_studio = retired
        if aliased_on_ai_studio and not os.getenv("GEMINI_PROJECT_ID"):
            emit("WARN_GEMINI_MODEL_RETIRED", model=model, replacement=replacement)
        else:
            emit("ERROR_GEMINI_MODEL_RETIRED", model=model, replacement=replacement)
            return False

    if os.getenv("GEMINI_PROJECT_ID"):
        location = gemini_location()
        allowed = gemini_vertex_locations(model)
        if allowed is not None and location.lower() not in allowed:
            emit("WARN_GEMINI_LOCATION", location=location, model=model, allowed=", ".join(allowed))
        try:
            import google.auth

            google.auth.default()
        except Exception as e:  # DefaultCredentialsError, or google-auth missing
            emit("ERROR_GEMINI_VERTEX_CREDENTIALS", error=str(e).splitlines()[0][:200])
            return False
        emit("LLM_AUTH_OK", provider="Gemini", source=_ui("AUTH_SOURCE_VERTEX", project=os.environ["GEMINI_PROJECT_ID"], location=location))
        return True
    if _env_set("GEMINI_API_KEY"):
        emit("LLM_AUTH_OK", provider="Gemini", source=_ui("AUTH_SOURCE_AI_STUDIO"))
        return True
    emit("ERROR_GEMINI_NO_CREDENTIALS")
    return False


def check_openrouter_config() -> bool:
    """Preflight for LLM_PROVIDER=OPENROUTER."""
    from utils.output import emit

    if not _env_set("OPENROUTER_API_KEY") and is_openrouter_host():
        emit("ERROR_OPENROUTER_NO_KEY")
        return False
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not model:
        emit("ERROR_OPENROUTER_NO_MODEL")
        return False
    if openrouter_catalog() and openrouter_model_info(model) is None:
        emit("WARN_OPENROUTER_MODEL_UNKNOWN", model=model)
    emit("LLM_AUTH_OK", provider="OpenRouter", source=f"OPENROUTER_API_KEY | {model} | {openrouter_base_url()}")
    return True


def check_llm_auth() -> bool:
    """Credential/SDK preflight for the active provider, run before any LLM call by main() and the
    utils/call_llm.py self-test. Prints setup instructions and returns False when the run cannot work."""
    provider = get_llm_provider()
    if provider == "ANTHROPIC":
        return check_anthropic_auth()
    if provider == "GEMINI":
        return check_gemini_config()
    if provider == "OPENROUTER":
        return check_openrouter_config()
    return True
