import argparse
import os
import shutil
import sys

import dotenv

# Import the function that creates the flow
from flow import create_tutorial_flow
from utils.call_llm import LEGACY_CACHE_FILE, cache_file, notice_legacy_cache
from utils.exclude_patterns import DEFAULT_EXCLUDE_PATTERNS
from utils.llm_config import check_llm_auth, describe_thinking_support, resolve_llm_settings
from utils.output import configure_logging, emit, emit_raw, get, translate_missing_strings
from utils.output import init as init_output
from utils.thinking import (
    MODE_NODES,
    NODE_KEYS,
    THINKING_LEVELS,
    THINKING_PROFILES,
    build_thinking_plan,
    describe_plan,
    parse_overrides,
    resolve_profile_name,
)
from utils.token_utils import TOKEN_CALIBRATION_FILE, describe_token_ratio

dotenv.load_dotenv()

# Default file patterns
DEFAULT_INCLUDE_PATTERNS = {"*"}


# --- Argument Parsing ---
def _thinking_level_arg(value):
    """argparse type for --thinking-level: a level from THINKING_LEVELS; '' or 'default' → None (model default)."""
    level = value.strip().lower()
    if level in ("", "default"):
        return None
    if level not in THINKING_LEVELS:
        raise argparse.ArgumentTypeError(f"invalid choice: {value!r} (choose from {', '.join(THINKING_LEVELS)}, default)")
    return level


def parse_arguments():
    """Parse and return command-line arguments."""
    parser = argparse.ArgumentParser(description="Generate a tutorial for a GitHub codebase or local directory.")

    # Source: --repo or --dir (mutually exclusive but not required if --cleanup is used)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--repo", help="URL of the public GitHub repository.")
    source_group.add_argument("--dir", help="Path to local directory.")
    parser.add_argument("--cleanup", action="store_true", help="Clean up logs and cache files. Can be used standalone or after a run.")

    parser.add_argument("-n", "--name", help="Project name (optional, derived from repo/directory if omitted).")
    parser.add_argument("-t", "--token", help="GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).")
    parser.add_argument("-o", "--output", default="output", help="Base directory for output (default: ./output).")
    parser.add_argument("-i", "--include", nargs="+", help="Files to include (e.g., '*.py' '*.js'). Defaults to '*' (all files).")
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        help="Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native .gitignore rules.",
    )
    parser.add_argument("-s", "--max-size", type=int, default=200000, help="Maximum file size in bytes (default: 200000, about 200KB).")
    # Add language parameter for multi-language support
    parser.add_argument("--language", default="english", help="Language for the generated tutorial (default: english).")
    # Add use_cache parameter to control LLM caching
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM response caching (default: caching enabled).")
    # Add max_abstraction_num parameter to control the number of abstractions
    parser.add_argument("--max-abstractions", type=int, default=10, help="Maximum number of abstractions to identify (default: 10).")
    # Add thinking_level parameter for LLM reasoning capabilities
    parser.add_argument(
        "--thinking-level",
        default=None,
        type=_thinking_level_arg,
        metavar="{" + ",".join(THINKING_LEVELS) + "}",
        help="Global thinking effort for EVERY LLM call. Overrides --thinking-profile. 'default' (or empty) = model default. "
        "Mapped per provider: Anthropic effort (thinking budget on Haiku 4.5), Gemini thinking_level (3.x) / thinking budget (2.5), "
        "OpenRouter reasoning effort or budget, Ollama reasoning effort (clamped to what the model supports).",
    )
    parser.add_argument(
        "--thinking-profile",
        default="auto",
        type=str.lower,
        choices=THINKING_PROFILES,
        help="Per-node thinking effort profile (default: auto = balanced on ANTHROPIC, GEMINI and OPENROUTER, off elsewhere). "
        "economy/balanced/quality/max give reasoning-heavy nodes (abstractions, relationships) more effort than "
        "mechanical ones (summaries, translation), adjusted per --mode. off = model defaults.",
    )
    parser.add_argument(
        "--thinking-override",
        nargs="+",
        metavar="NODE=LEVEL",
        help=f"Per-node thinking level overrides, highest precedence (e.g., write_chapters=high identify_abstractions=xhigh). NODE: {', '.join(NODE_KEYS)}.",
    )
    # Add max_tokens parameter
    parser.add_argument(
        "--max-tokens", type=int, default=None, help="Maximum number of tokens for the context window (default: fetched dynamically)."
    )

    # --- Documentation Mode & Generation Styles ---
    parser.add_argument(
        "--mode",
        choices=["tutorial", "advanced", "api-reference", "sdk"],
        default="tutorial",
        help="Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial).",
    )
    parser.add_argument("--advanced", action="store_true", help="Legacy flag: equivalent to --mode advanced.")
    parser.add_argument("--mkdocs", action="store_true", help="Format output for MkDocs Material (adds YAML frontmatter & nav snippet).")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference).",
    )
    parser.add_argument(
        "--force-rebuild", action="store_true", help="Clear incremental cache and regenerate all chapters from scratch (use with --incremental)."
    )

    # Add batching parameters
    parser.add_argument("--batch", type=int, default=50, help="Maximum files per batch when using map-reduce mode (default: 50).")
    parser.add_argument("--force-batch", action="store_true", help="Force map-reduce mode regardless of context size.")
    # Debug mode
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output.")

    return parser, parser.parse_args()


def _check_quoting_errors(parser, args):
    """Detect shell quoting errors where --exclude/--include values accidentally swallowed other CLI flags.

    When users misquote patterns (e.g., --exclude "autogen/* "SmartFO/*" --language Vietnamese),
    the shell merges subsequent flags into the pattern value. This silently causes ALL following
    arguments to be ignored. We detect this by checking if any pattern value contains a known
    CLI flag string, which no legitimate file/directory pattern would ever contain.

    Flags are extracted dynamically from the argparse parser — no hardcoded list to maintain.
    """
    # Extract all registered flags (both --long and -short) from the parser
    known_flags = set()
    for action in parser._actions:
        for opt in action.option_strings:
            known_flags.add(opt)

    for pattern_list, flag_name in [(args.exclude, "--exclude"), (args.include, "--include")]:
        if not pattern_list:
            continue
        for pattern in pattern_list:
            for known_flag in known_flags:
                if f" {known_flag} " in pattern or (f" {known_flag}" in pattern and pattern.endswith(known_flag)):
                    emit(
                        "ERROR_QUOTING",
                        flag=flag_name,
                        pattern=pattern[:120],
                        embedded=known_flag,
                    )
                    sys.exit(1)


# --- Mode & Project Name Resolution ---
def resolve_mode_and_project(args):
    """Resolve documentation mode (handling --advanced legacy flag) and derive project name.

    Returns:
        tuple[str, str]: (mode, project_name)
    """
    if args.advanced:
        if args.mode != "tutorial":  # User explicitly set --mode AND --advanced
            emit("WARN_ADVANCED_OVERRIDES_MODE", mode=args.mode)
        mode = "advanced"
    else:
        mode = args.mode
    project_name = args.name
    if not project_name:
        if args.dir:
            project_name = os.path.basename(os.path.abspath(args.dir))
        elif args.repo:
            project_name = args.repo.rstrip("/").split("/")[-1].removesuffix(".git")
        else:
            project_name = "project"
    return mode, project_name


# --- Shared Store Construction ---
def build_shared_store(args, github_token, mode, thinking_plan, project_name):
    """Construct the shared store dictionary passed between PocketFlow nodes.

    Returns:
        dict: The shared store with all CLI args, patterns, and empty output slots.
    """
    return {
        "repo_url": args.repo,
        "local_dir": args.dir,
        "project_name": project_name,  # Resolved once in main so logs, --force-rebuild and output agree
        "github_token": github_token,
        "output_dir": args.output,  # Base directory for CombineTutorial output
        # Include/exclude patterns and max file size
        "include_patterns": set(args.include) if args.include else DEFAULT_INCLUDE_PATTERNS,
        "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.union(set(args.exclude)) if args.exclude else DEFAULT_EXCLUDE_PATTERNS,
        "max_file_size": args.max_size,
        # Language for multi-language support
        "language": args.language,
        # Cache flag (inverse of no-cache)
        "use_cache": not args.no_cache,
        # Max abstractions
        "max_abstraction_num": args.max_abstractions,
        # LLM reasoning capabilities: global level (legacy) + per-node plan (utils/thinking.py)
        "thinking_level": args.thinking_level,
        "thinking_plan": thinking_plan,
        # Max tokens override
        "max_tokens": args.max_tokens,
        # Mode, mkdocs, and incremental
        "mode": mode,
        "mkdocs": args.mkdocs,
        "incremental": args.incremental,
        "advanced_mode": mode == "advanced",
        # Batching settings
        "batch_size": args.batch,
        "force_batch": args.force_batch,
        # Debug mode
        "debug": args.debug,
        # Outputs populated by downstream nodes
        "files": [],
        "abstractions": [],
        "relationships": {},
        "chapter_order": [],
        "chapters": [],
        "final_output_dir": None,
    }


# --- LLM Configuration Detection ---
def detect_llm_config(args):
    """Detect LLM provider, model, endpoint, and context length from environment.

    Returns:
        tuple: (provider, model_name, endpoint_url, api_key, context_length)
    """
    from utils.llm_config import get_model_context_length

    provider, model_name, endpoint_url, api_key = resolve_llm_settings()
    context_length = args.max_tokens or get_model_context_length(endpoint_url, model_name, api_key)
    return provider, model_name, endpoint_url, api_key, context_length


# --- Thinking Plan Resolution ---
def resolve_thinking_plan(args):
    """Build the per-node thinking plan from --thinking-override / --thinking-level / --thinking-profile.

    Pure (no emit): runs before init_output(). Validation messages come from _validate_thinking_args().

    Returns:
        tuple[str, dict, list[str]]: (resolved profile name, {node_key: level | None}, invalid override strings)
    """
    mode = "advanced" if args.advanced else args.mode
    overrides, invalid = parse_overrides(args.thinking_override)
    profile = "global" if args.thinking_level else resolve_profile_name(args.thinking_profile, resolve_llm_settings()[0])
    return profile, build_thinking_plan(profile, mode, args.thinking_level, overrides), invalid


def _validate_thinking_args(args, invalid_overrides):
    """Report malformed --thinking-override values (fatal), overrides for nodes the mode never runs,
    and --thinking-level/--thinking-profile conflicts."""
    if invalid_overrides:
        emit("ERROR_THINKING_OVERRIDE", value=", ".join(invalid_overrides), nodes=", ".join(NODE_KEYS), levels=", ".join(THINKING_LEVELS))
        sys.exit(1)
    mode = "advanced" if args.advanced else args.mode
    overrides, _ = parse_overrides(args.thinking_override)
    unused = [node for node in overrides if node not in MODE_NODES[mode]]
    if unused:
        emit("WARN_THINKING_OVERRIDE_UNUSED", nodes=", ".join(unused), mode=mode, active=", ".join(MODE_NODES[mode]))
    if args.thinking_level and args.thinking_profile != "auto":
        emit("WARN_THINKING_LEVEL_OVERRIDES_PROFILE", level=args.thinking_level, profile=args.thinking_profile)


# --- Configuration Display ---
def display_config(args, mode, provider, model_name, endpoint_url, context_length, log_file, thinking_profile, thinking_plan):
    """Emit all configuration values to the console."""
    emit("START_GENERATION", source=args.repo or args.dir, language=args.language.capitalize())
    emit("CFG_HEADER")
    emit("CFG_AI_PROVIDER", value=provider)
    emit("CFG_AI_ENDPOINT", value=endpoint_url)
    emit("CFG_AI_MODEL", value=model_name)
    emit("CFG_CONTEXT_LENGTH", value=f"{context_length:,}")
    emit("CFG_THINKING_LEVEL", value=args.thinking_level or "None")
    emit("CFG_THINKING_PROFILE", value=thinking_profile)
    if any(thinking_plan.values()):
        emit("CFG_THINKING_PLAN", value=describe_plan(thinking_plan, mode))
    emit("CFG_THINKING_SUPPORT", value=describe_thinking_support(provider, model_name))
    emit("CFG_TOKEN_RATIO", value=describe_token_ratio())
    emit("CFG_BATCH_SIZE", value=f"{args.batch}")
    _enabled = get("CFG_VALUE_ENABLED")
    _disabled = get("CFG_VALUE_DISABLED")
    emit("CFG_FORCE_BATCH", value=_enabled if args.force_batch else _disabled)
    emit("CFG_OUTPUT_MODE", value=mode)
    emit("CFG_MKDOCS", value=_enabled if args.mkdocs else _disabled)
    emit("CFG_INCREMENTAL", value=_enabled if args.incremental else _disabled)
    if args.incremental:
        emit("CFG_FORCE_REBUILD", value=_enabled if args.force_rebuild else _disabled)
    if mode == "api-reference":
        emit("CFG_MAX_ABSTRACTIONS", value=get("CFG_VALUE_API_REF_MAX"))
    else:
        emit("CFG_MAX_ABSTRACTIONS", value=str(args.max_abstractions))
    emit("CFG_LLM_CACHING", value=_disabled if args.no_cache else _enabled)
    if args.debug:
        emit("CFG_DEBUG_MODE")
    emit("CFG_LOG_FILE", value=log_file)
    print()  # Blank line after config block


# --- Cleanup ---
def _run_cleanup():
    """Clean up cache files and log directory."""
    emit("CLEANUP_START")

    for cache_path in [cache_file, f"{cache_file}.tmp", LEGACY_CACHE_FILE, TOKEN_CALIBRATION_FILE, f"{TOKEN_CALIBRATION_FILE}.tmp"]:
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                emit("CLEANUP_REMOVED", path=cache_path)
            except Exception as e:
                emit("CLEANUP_FAILED", path=cache_path, error=e)

    log_dir = os.environ.get("LOG_DIR", "logs")
    if os.path.exists(log_dir) and os.path.isdir(log_dir):
        try:
            shutil.rmtree(log_dir)
            emit("CLEANUP_REMOVED_DIR", path=log_dir)
        except Exception as e:
            emit("CLEANUP_FAILED", path=log_dir, error=e)


# --- LLM Usage Summary ---
def _emit_usage_summary():
    """Emit accumulated token usage and estimated cost per provider, then the per-step breakdown."""
    from utils.llm_common import get_step_summary, get_usage_summary
    from utils.token_utils import emit_step_usage, format_cost

    for name, usage in get_usage_summary().items():
        emit(
            "LLM_USAGE_SUMMARY",
            provider=name,
            models=", ".join(usage["models"]) or "-",
            calls=f"{usage['calls']:,}",
            input=f"{usage['input']:,}",
            output=f"{usage['output']:,}",
            thinking=f"{usage['thinking']:,}",
            cache_read=f"{usage['cache_read']:,}",
            cache_write=f"{usage['cache_write']:,}",
            cost=format_cost(usage),
            refusals=usage["refusals"],
            fallbacks=usage["fallbacks"],
            truncations=usage["truncations"],
        )
    steps = get_step_summary()
    if steps:
        emit("LLM_USAGE_STEPS_HEADER")
        for step, usage in steps.items():
            emit_step_usage("LLM_USAGE_STEP", step, usage)


# --- Main Orchestrator ---
def main():
    parser, args = parse_arguments()
    # Resolved silently before init_output(): string translation itself uses the plan's translate_strings level.
    thinking_profile, thinking_plan, invalid_overrides = resolve_thinking_plan(args)
    # Translation of missing strings is an LLM call: deferred until arguments and credentials are checked.
    init_output(
        language=args.language,
        use_cache=not args.no_cache,
        thinking_level=thinking_plan["translate_strings"],
        debug=args.debug,
        auto_translate=False,
    )
    _check_quoting_errors(parser, args)
    _validate_thinking_args(args, invalid_overrides)

    # Handle standalone --cleanup (no --dir or --repo)
    if args.cleanup and not args.dir and not args.repo:
        _run_cleanup()
        return

    # Require --dir or --repo for generation
    if not args.dir and not args.repo:
        parser.error("one of the arguments --repo --dir --cleanup is required")

    # Fail fast (with setup instructions) before crawling if the configured provider cannot authenticate
    if not check_llm_auth():
        sys.exit(1)
    translate_missing_strings()
    notice_legacy_cache()

    # Get GitHub token from argument or environment variable if using repo
    github_token = None
    if args.repo:
        github_token = args.token or os.environ.get("GITHUB_TOKEN")
        if not github_token:
            emit("WARN_NO_GITHUB_TOKEN")
    elif args.token:
        emit("WARN_TOKEN_NO_REPO")

    mode, project_name = resolve_mode_and_project(args)

    # Enforce incremental cache constraints
    if args.incremental and mode != "api-reference":
        emit("WARN_INCREMENTAL_API_ONLY")
        args.incremental = False

    # --force-rebuild requires --incremental
    if args.force_rebuild and not args.incremental:
        emit("ERROR_FORCE_REBUILD_NO_INCREMENTAL")
        sys.exit(1)

    # Handle --force-rebuild: delete the cache manifest to force fresh generation
    if args.force_rebuild and args.incremental:
        output_base = args.output or "output"
        manifest_path = os.path.join(output_base, project_name, ".doc_cache_manifest.json")
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
            emit("FORCE_REBUILD_DELETED", path=manifest_path)
        else:
            emit("FORCE_REBUILD_NO_MANIFEST", path=manifest_path)

    # Warn about args ignored in api-reference mode
    if mode == "api-reference" and args.force_batch:
        emit("WARN_FORCE_BATCH_API_REF")
        args.force_batch = False

    shared = build_shared_store(args, github_token, mode, thinking_plan, project_name)
    provider, model_name, endpoint_url, _, context_length = detect_llm_config(args)
    log_file = configure_logging(project_name=project_name, mode=mode)
    display_config(args, mode, provider, model_name, endpoint_url, context_length, log_file, thinking_profile, thinking_plan)

    # Create and run the flow
    tutorial_flow = create_tutorial_flow()
    try:
        tutorial_flow.run(shared)

        # Cleanup after run if requested
        if args.cleanup:
            _run_cleanup()
    finally:
        from utils.output import shutdown

        # Report spend even when the run fails — failed runs are often the expensive ones.
        try:
            _emit_usage_summary()
        except Exception as e:
            emit_raw("WARNING", f"Usage summary failed: {e}", dest="LOG")
        shutdown()


if __name__ == "__main__":
    main()
