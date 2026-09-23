"""Per-node thinking effort resolution ("thinking flows").

Every LLM call site in the flow has a NODE key. A thinking plan maps each key to a
thinking level (minimal | low | medium | high | xhigh | max, or None for the model default),
built once in main.py from:

    --thinking-override NODE=LEVEL   (highest precedence, per node)
    --thinking-level LEVEL           (global: every node)
    --thinking-profile PROFILE       (per-node table below, adjusted per mode)

`auto` (the default profile) resolves to `balanced` on providers whose thinking the project
maps per model — ANTHROPIC, GEMINI and OPENROUTER: current models there think by default
(Claude 5 family, Gemini 3.x) and explicit per-node effort is the main quality/cost lever —
and to `off` (model defaults) elsewhere (OLLAMA and other OpenAI-compatible endpoints).

Levels are provider-neutral; each provider maps or clamps them with clamp_level():
Anthropic → output_config.effort (minimal → low), Gemini 3.x → thinking_level (per-model
set), Gemini 2.5 → thinking_budget, OpenRouter → reasoning.effort (catalog supported_efforts),
Ollama → low/medium/high.
"""

# Ordered effort scale. `minimal` exists for OpenRouter models that expose it; profiles never use it.
THINKING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
THINKING_PROFILES = ("auto", "off", "economy", "balanced", "quality", "max")

# LLM call sites, in pipeline order.
NODE_KEYS = (
    "filter_files",  # DeterministicFileMapper — code/non-code file classification (api-reference)
    "map_abstractions",  # MapAbstractions — per-batch abstraction extraction (batch route)
    "reduce_abstractions",  # ReduceAbstractions — merge partial abstractions (batch route)
    "identify_abstractions",  # IdentifyAbstractions — whole-codebase abstraction discovery (direct route)
    "analyze_relationships",  # AnalyzeRelationships — project summary + abstraction relationships
    "order_chapters",  # OrderChapters — pedagogical chapter ordering
    "write_chapters",  # WriteChapters — long-form chapter / reference page generation
    "chapter_summary",  # WriteChapters — 3-5 sentence summary for cross-chapter context
    "group_modules",  # CombineTutorial — MkDocs nav grouping (api-reference, 6+ modules)
    "translate_strings",  # i18n — CLI string table translation (first run in a new language)
)

# Nodes that can make an LLM call in each mode. api-reference always takes the deterministic
# route (1:1 file mapping) and is the only mode with MkDocs nav grouping.
_ANALYSIS_NODES = ("map_abstractions", "reduce_abstractions", "identify_abstractions", "analyze_relationships", "order_chapters")
MODE_NODES = {
    "tutorial": (*_ANALYSIS_NODES, "write_chapters", "chapter_summary", "translate_strings"),
    "advanced": (*_ANALYSIS_NODES, "write_chapters", "chapter_summary", "translate_strings"),
    "sdk": (*_ANALYSIS_NODES, "write_chapters", "chapter_summary", "translate_strings"),
    "api-reference": ("filter_files", "write_chapters", "chapter_summary", "group_modules", "translate_strings"),
}

# Base per-node levels. Reasoning-heavy synthesis (identify/reduce abstractions) gets the
# most effort; relationship analysis only feeds the summary, diagram and ordering, so it
# sits one level lower; long-form generation gets enough to plan accurately; mechanical
# transforms stay low. Current Claude 5 models already do strong work at medium (Opus 5.5 at
# medium beats Opus 5 at high on knowledge work), and chapter writing runs N times, so
# shipped profiles stop at high. xhigh/max appear
# only in the explicit `max` profile (use it when you have measured a gain).
_PROFILES = {
    "economy": {
        "filter_files": "low",
        "map_abstractions": "low",
        "reduce_abstractions": "medium",
        "identify_abstractions": "medium",
        "analyze_relationships": "low",
        "order_chapters": "low",
        "write_chapters": "low",
        "chapter_summary": "low",
        "group_modules": "low",
        "translate_strings": "low",
    },
    "balanced": {
        "filter_files": "low",
        "map_abstractions": "medium",
        "reduce_abstractions": "high",
        "identify_abstractions": "high",
        "analyze_relationships": "medium",
        "order_chapters": "medium",
        "write_chapters": "medium",
        "chapter_summary": "low",
        "group_modules": "medium",
        "translate_strings": "low",
    },
    "quality": {
        "filter_files": "medium",
        "map_abstractions": "high",
        "reduce_abstractions": "high",
        "identify_abstractions": "high",
        "analyze_relationships": "high",
        "order_chapters": "high",
        "write_chapters": "high",
        "chapter_summary": "medium",
        "group_modules": "high",
        "translate_strings": "medium",
    },
    "max": {
        "filter_files": "medium",
        "map_abstractions": "xhigh",
        "reduce_abstractions": "max",
        "identify_abstractions": "max",
        "analyze_relationships": "xhigh",
        "order_chapters": "high",
        "write_chapters": "xhigh",
        "chapter_summary": "medium",
        "group_modules": "high",
        "translate_strings": "medium",
    },
}

# Mode-specific adjustments on top of the base profile. advanced chapters carry design-
# rationale analysis and there are at most max_abstraction_num of them, so economy keeps
# them at medium instead of low.
_MODE_ADJUSTMENTS = {
    "economy": {"advanced": {"write_chapters": "medium"}},
}


# Providers whose thinking controls are mapped per model (auto → balanced).
PROFILED_PROVIDERS = ("ANTHROPIC", "GEMINI", "OPENROUTER")


def resolve_profile_name(profile: str | None, provider: str | None) -> str:
    """Resolve `auto` to a concrete profile for the active provider."""
    profile = (profile or "auto").lower()
    if profile == "auto":
        return "balanced" if provider in PROFILED_PROVIDERS else "off"
    return profile


def clamp_level(level: str, supported) -> str | None:
    """Return `level` if the model supports it, else the nearest supported level on
    THINKING_LEVELS (ties → lower). None when nothing on the scale is supported."""
    if level in supported:
        return level
    ranked = [lvl for lvl in THINKING_LEVELS if lvl in supported]
    if not ranked or level not in THINKING_LEVELS:
        return None
    target = THINKING_LEVELS.index(level)
    return min(ranked, key=lambda lvl: (abs(THINKING_LEVELS.index(lvl) - target), THINKING_LEVELS.index(lvl)))


def parse_overrides(values: list[str] | None) -> tuple[dict, list[str]]:
    """Parse NODE=LEVEL strings. Returns (overrides, invalid_values)."""
    overrides, invalid = {}, []
    for value in values or []:
        node, sep, level = value.partition("=")
        node, level = node.strip().lower(), level.strip().lower()
        if not sep or node not in NODE_KEYS or level not in THINKING_LEVELS:
            invalid.append(value)
        else:
            overrides[node] = level
    return overrides, invalid


def build_thinking_plan(profile: str, mode: str, global_level: str | None, overrides: dict) -> dict:
    """Return {node_key: level | None} for every NODE key.

    Precedence: overrides > global_level > profile table (+ mode adjustments).
    `profile` must already be resolved (see resolve_profile_name).
    """
    if global_level:
        plan = dict.fromkeys(NODE_KEYS, global_level.lower())
    elif profile in _PROFILES:
        plan = dict(_PROFILES[profile])
        plan.update(_MODE_ADJUSTMENTS.get(profile, {}).get(mode, {}))
    else:  # "off": every node uses the model's default thinking behavior
        plan = dict.fromkeys(NODE_KEYS)
    plan.update(overrides)
    return plan


def resolve_thinking_level(shared: dict, node_key: str) -> str | None:
    """Thinking level for one LLM call site. Falls back to the global level when no plan exists."""
    plan = shared.get("thinking_plan")
    if plan and node_key in plan:
        return plan[node_key]
    return shared.get("thinking_level")


def describe_plan(plan: dict, mode: str | None = None) -> str:
    """Compact one-line rendering for the startup config display (only nodes that run in `mode`)."""
    keys = MODE_NODES.get(mode, NODE_KEYS)
    return ", ".join(f"{key}={plan.get(key) or 'default'}" for key in keys)
