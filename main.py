import dotenv
import os
import argparse
# Import the function that creates the flow
from flow import create_tutorial_flow

dotenv.load_dotenv()

# Default file patterns
DEFAULT_INCLUDE_PATTERNS = {"*"}

DEFAULT_EXCLUDE_PATTERNS = {
    # 1. Media, Data, and Static Assets
    "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*", "tmp/*", "media/*",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.ico", "*.svg", "*.webp",
    "*.mp4", "*.webm", "*.mov", "*.mp3", "*.wav",
    "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
    "*.zip", "*.tar", "*.gz", "*.rar", "*.7z",

    # 2. Build, Distribution, and Framework Caches
    "dist/*", "build/*", "out/*", "target/*", "bin/*", "obj/*",
    ".next/*", ".nuxt/*", ".svelte-kit/*", ".expo/*", 
    "docs/*", "test/*", "tests/*", "examples/*",
    "v1/*", "experimental/*", "deprecated/*", "misc/*", "legacy/*",
    "*.log", "*.bak", "*.tmp", "*.swp",

    # 3. Environments, Dependencies & Lockfiles
    "venv/*", ".venv/*", "env/*", ".env", ".env.*",
    "node_modules/*", "bower_components/*", "jspm_packages/*",
    "vendor/*", "packages/*", 
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "Gemfile.lock", "poetry.lock", "mix.lock", "Pipfile.lock",

    # 4. Language-Specific Exclusions
    "__pycache__/*", "*.pyc", "*.pyo", "*.pyd", ".pytest_cache/*", ".tox/*", ".coverage", "htmlcov/*", # Python
    ".gradle/*", "*.class", "*.jar", "*.war", "*.ear", "*.nar", # Java / JVM
    "*.o", "*.obj", "*.dll", "*.exe", "*.so", "*.dylib", "*.lib", "*.a", # C/C++/Native
    "ios/Pods/*", "android/.gradle/*", "android/app/build/*", # Mobile

    # 5. OS & Version Control
    ".git/*", ".github/*", ".svn/*", ".hg/*",
    ".DS_Store", "Thumbs.db", "desktop.ini",

    # 6. Classic IDEs
    ".vscode/*", ".idea/*", "*.iml", ".eclipse/*", ".settings/*", ".classpath", ".project", ".vs/*",

    # 7. AI Agents & Modern AI IDEs
    ".cursor/*", ".cursorrules",
    ".windsurf/*", ".windsurfrules",
    ".cline/*", ".clinerules",
    ".roo/*", ".roorules",
    ".agent/*", ".agents/*",
    ".continue/*", ".aide/*",
    ".gemini/*", ".antigravity/*",
    ".claude/*", ".copilot/*",
}

# --- Main Function ---
def main():
    parser = argparse.ArgumentParser(description="Generate a tutorial for a GitHub codebase or local directory.")

    # Create mutually exclusive group for source
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--repo", help="URL of the public GitHub repository.")
    source_group.add_argument("--dir", help="Path to local directory.")

    parser.add_argument("-n", "--name", help="Project name (optional, derived from repo/directory if omitted).")
    parser.add_argument("-t", "--token", help="GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).")
    parser.add_argument("-o", "--output", default="output", help="Base directory for output (default: ./output).")
    parser.add_argument("-i", "--include", nargs="+", help="Files to include (e.g., '*.py' '*.js'). Defaults to '*' (all files).")
    parser.add_argument("-e", "--exclude", nargs="+", help="Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native .gitignore rules.")
    parser.add_argument("-s", "--max-size", type=int, default=200000, help="Maximum file size in bytes (default: 200000, about 200KB).")
    # Add language parameter for multi-language support
    parser.add_argument("--language", default="english", help="Language for the generated tutorial (default: english)")
    # Add use_cache parameter to control LLM caching
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM response caching (default: caching enabled)")
    # Add cleanup parameter
    parser.add_argument("--cleanup", action="store_true", help="Clean up logs and cache JSON at the end of the script (default: No)")
    # Add max_abstraction_num parameter to control the number of abstractions
    parser.add_argument("--max-abstractions", type=int, default=10, help="Maximum number of abstractions to identify (default: 10)")
    # Add thinking_level parameter for LLM reasoning capabilities
    parser.add_argument("--thinking-level", default=None, help="Thinking effort level for OpenRouter models (e.g., low, medium, high). Default is auto.")
    # Add max_tokens parameter
    parser.add_argument("--max-tokens", type=int, default=None, help="Maximum number of tokens for the context window (default: fetched dynamically).")
    # Add advanced prompt mode
    parser.add_argument("--advanced", action="store_true", help="Load advanced prompts from prompts/advanced/ directory")
    # Add batching parameters
    parser.add_argument("--batch", type=int, default=50, help="Max files per batch in map-reduce mode")
    parser.add_argument("--force-batch", action="store_true", help="Force map-reduce mode regardless of context size")
    # Debug mode
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")

    args = parser.parse_args()

    # Get GitHub token from argument or environment variable if using repo
    github_token = None
    if args.repo:
        github_token = args.token or os.environ.get('GITHUB_TOKEN')
        if not github_token:
            print("Warning: No GitHub token provided. You might hit rate limits for public repositories.")

    # Initialize the shared dictionary with inputs
    shared = {
        "repo_url": args.repo,
        "local_dir": args.dir,
        "project_name": args.name, # Can be None, FetchRepo will derive it
        "github_token": github_token,
        "output_dir": args.output, # Base directory for CombineTutorial output

        # Add include/exclude patterns and max file size
        "include_patterns": set(args.include) if args.include else DEFAULT_INCLUDE_PATTERNS,
        "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS.union(set(args.exclude)) if args.exclude else DEFAULT_EXCLUDE_PATTERNS,
        "max_file_size": args.max_size,

        # Add language for multi-language support
        "language": args.language,
        
        # Add use_cache flag (inverse of no-cache flag)
        "use_cache": not args.no_cache,
        
        # Add max_abstraction_num parameter
        "max_abstraction_num": args.max_abstractions,

        # Add thinking_level for LLM reasoning capabilities
        "thinking_level": args.thinking_level,
        
        # Add max tokens override
        "max_tokens": args.max_tokens,
        
        # Advanced mode
        "advanced_mode": args.advanced,
        
        # Batching settings
        "batch_size": args.batch,
        "force_batch": args.force_batch,

        # Debug mode
        "debug": args.debug,

        # Outputs will be populated by the nodes
        "files": [],
        "abstractions": [],
        "relationships": {},
        "chapter_order": [],
        "chapters": [],
        "final_output_dir": None
    }

    # Get LLM configuration for display
    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        model_name = os.environ.get(f"{provider}_MODEL", "unknown")
        endpoint_url = os.environ.get(f"{provider}_BASE_URL", "unknown")
        api_key = os.environ.get(f"{provider}_API_KEY", "")
    else:
        # Fallback to Gemini if neither provider is explicitly set but it's used
        if os.environ.get("GEMINI_PROJECT_ID") or os.environ.get("GEMINI_API_KEY"):
            provider = "GEMINI"
            model_name = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
            endpoint_url = "generativelanguage.googleapis.com"
            api_key = os.environ.get("GEMINI_API_KEY", "")
        else:
            provider = "UNKNOWN"
            model_name = "unknown"
            endpoint_url = "unknown"
            api_key = ""

    from utils.call_llm import get_model_context_length
    context_length = args.max_tokens if args.max_tokens else get_model_context_length(endpoint_url, model_name, api_key)

    # Display configuration
    print(f"Starting tutorial generation for: {args.repo or args.dir} in {args.language.capitalize()} language")
    print(f"--- Configuration ---")
    print(f"AI Provider    : {provider}")
    print(f"AI Endpoint    : {endpoint_url}")
    print(f"AI Model       : {model_name}")
    print(f"Context Length : {context_length:,} tokens")
    print(f"Thinking Level : {args.thinking_level if args.thinking_level else 'None'}")
    print(f"Advanced Prompts: {'Enabled' if args.advanced else 'Disabled'}")
    print(f"Batch Size     : {args.batch} files/batch")
    print(f"Force Batch    : {'Enabled' if args.force_batch else 'Disabled'}")
    print(f"Max Abstractions: {args.max_abstractions}")
    print(f"LLM Caching    : {'Disabled' if args.no_cache else 'Enabled'}")
    if args.debug:
        print(f"Debug Mode     : Enabled")
    print(f"---------------------")

    # Create the flow instance
    tutorial_flow = create_tutorial_flow()

    # Run the flow
    tutorial_flow.run(shared)
    
    # Cleanup logs and cache if requested
    if args.cleanup:
        print("\nCleaning up cache and logs...")
        cache_path = "llm_cache.json"
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                print(f" - Removed {cache_path}")
            except Exception as e:
                print(f" - Failed to remove {cache_path}: {e}")
                
        log_dir = os.environ.get("LOG_DIR", "logs")
        if os.path.exists(log_dir) and os.path.isdir(log_dir):
            import shutil
            try:
                shutil.rmtree(log_dir)
                print(f" - Removed {log_dir} directory")
            except Exception as e:
                print(f" - Failed to remove {log_dir}: {e}")

if __name__ == "__main__":
    main()
