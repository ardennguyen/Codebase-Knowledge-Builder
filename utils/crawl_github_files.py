import base64
import fnmatch
import os
import tempfile
import time
from urllib.parse import urlparse

import git
import pathspec
import requests


def crawl_github_files(
    repo_url,
    token=None,
    max_file_size: int = 1 * 1024 * 1024,  # 1 MB
    use_relative_paths: bool = False,
    include_patterns: str | set[str] | None = None,
    exclude_patterns: str | set[str] | None = None
):
    """
    Crawl files from a specific path in a GitHub repository at a specific commit.

    Args:
        repo_url (str): URL of the GitHub repository with specific path and commit
                        (e.g., 'https://github.com/microsoft/autogen/tree/e45a15766746d95f8cfaaa705b0371267bec812e/python/packages/autogen-core/src/autogen_core')
        token (str, optional): **GitHub personal access token.**
            - **Required for private repositories.**
            - **Recommended for public repos to avoid rate limits.**
            - Can be passed explicitly or set via the `GITHUB_TOKEN` environment variable.
        max_file_size (int, optional): Maximum file size in bytes to download (default: 1 MB)
        use_relative_paths (bool, optional): If True, file paths will be relative to the specified subdirectory
        include_patterns (str or set of str, optional): Pattern or set of patterns specifying which files to include (e.g., "*.py", {"*.md", "*.txt"}).
                                                       If None, all files are included.
        exclude_patterns (str or set of str, optional): Pattern or set of patterns specifying which files to exclude.
                                                       If None, no files are excluded.

    Returns:
        dict: Dictionary with files and statistics
    """
    # Convert single pattern to set
    if include_patterns and isinstance(include_patterns, str):
        include_patterns = {include_patterns}
    if exclude_patterns and isinstance(exclude_patterns, str):
        exclude_patterns = {exclude_patterns}

    def should_include_file(file_path: str, file_name: str, gitignore_spec=None) -> bool:
        """Determine if a file should be included based on patterns"""
        # If no include patterns are specified, include all files
        if not include_patterns:
            include_file = True
        else:
            # Check if file matches any include pattern
            include_file = any(fnmatch.fnmatch(file_name, pattern) for pattern in include_patterns)

        # Check gitignore if provided
        if include_file and gitignore_spec and gitignore_spec.match_file(file_path):
            return False

        # If exclude patterns are specified, check if file should be excluded
        if exclude_patterns and include_file:
            # Exclude if file matches any exclude pattern
            exclude_file = any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns)
            return not exclude_file

        return include_file

    # Detect SSH URL (git@ or .git suffix)
    is_ssh_url = repo_url.startswith("git@") or repo_url.endswith(".git")

    if is_ssh_url:
        # Clone repo via SSH to temp dir
        with tempfile.TemporaryDirectory() as tmpdirname:
            print(f"Cloning SSH repo {repo_url} to temp dir {tmpdirname} ...")
            try:
                repo = git.Repo.clone_from(repo_url, tmpdirname)
            except Exception as e:
                print(f"Error cloning repo: {e}")
                return {"files": {}, "stats": {"error": str(e)}}

            # Attempt to checkout specific commit/branch if in URL
            # Parse ref and subdir from SSH URL? SSH URLs don't have branch info embedded
            # So rely on default branch, or user can checkout manually later
            # Optionally, user can pass ref explicitly in future API

            # Walk directory
            files = {}
            skipped_files = []

            # --- ANSI colors ---
            C_GREEN  = "\033[92m"
            C_GRAY   = "\033[90m"
            C_RED    = "\033[91m"
            C_RESET  = "\033[0m"

            # --- Counters ---
            count_processed = 0
            count_excluded = 0
            count_size_limit = 0
            count_non_text = 0
            skipped_size_list = []
            skipped_non_text_list = []
            entry_num = 0

            # --- Load .gitignore ---
            gitignore_path = os.path.join(tmpdirname, ".gitignore")
            gitignore_spec = None
            if os.path.exists(gitignore_path):
                try:
                    with open(gitignore_path, "r", encoding="utf-8-sig") as f:
                        gitignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", f.readlines())
                    print("Loaded .gitignore patterns from repository.")
                except Exception:
                    pass

            for root, dirs, filenames in os.walk(tmpdirname):
                # Filter directories
                excluded_dirs = set()
                for d in sorted(dirs):
                    dirpath_rel = os.path.relpath(os.path.join(root, d), tmpdirname)
                    reason = None
                    if gitignore_spec and gitignore_spec.match_file(dirpath_rel):
                        reason = "excluded (.gitignore)"
                    elif exclude_patterns:
                        for pattern in exclude_patterns:
                            dir_pattern = pattern[:-2] if pattern.endswith("/*") else pattern
                            if fnmatch.fnmatch(dirpath_rel, dir_pattern) or fnmatch.fnmatch(d, dir_pattern):
                                reason = "excluded"
                                break

                    if reason:
                        excluded_dirs.add(d)
                        entry_num += 1
                        count_excluded += 1
                        print(f"{C_GRAY}  [{entry_num}] {dirpath_rel}/ [{reason}]{C_RESET}")

                for d in dirs.copy():
                    if d in excluded_dirs:
                        dirs.remove(d)

                # Sort remaining dirs for consistent traversal order
                dirs.sort()

                for filename in sorted(filenames):
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, tmpdirname)
                    entry_num += 1

                    # Check include/exclude patterns
                    if not should_include_file(rel_path, filename, gitignore_spec=gitignore_spec):
                        count_excluded += 1
                        print(f"{C_GRAY}  [{entry_num}] {rel_path} [excluded]{C_RESET}")
                        continue

                    # Check file size
                    try:
                        file_size = os.path.getsize(abs_path)
                    except OSError:
                        continue

                    if file_size > max_file_size:
                        count_size_limit += 1
                        skipped_size_list.append(rel_path)
                        size_kb = file_size / 1024
                        print(f"{C_RED}  [{entry_num}] {rel_path} [size limit: {size_kb:.0f}KB]{C_RESET}")
                        continue

                    # Read content
                    try:
                        with open(abs_path, "r", encoding="utf-8-sig") as f:
                            content = f.read()
                        files[rel_path] = content
                        count_processed += 1
                        print(f"{C_GREEN}  [{entry_num}] {rel_path} [processed]{C_RESET}")
                    except (UnicodeDecodeError, ValueError):
                        count_non_text += 1
                        skipped_non_text_list.append(rel_path)
                        print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: not a text file]{C_RESET}")
                    except Exception as e:
                        count_non_text += 1
                        skipped_non_text_list.append(rel_path)
                        print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: {e}]{C_RESET}")

            # --- Summary ---
            total_fetched = count_processed + count_excluded + count_size_limit + count_non_text
            print("\n--- Crawl Summary ---")
            print(f"  Total found : {total_fetched}")
            print(f"{C_GREEN}  Processed   : {count_processed}{C_RESET}")
            if count_excluded > 0:
                print(f"{C_GRAY}  Excluded    : {count_excluded}{C_RESET}")
            if count_size_limit > 0:
                print(f"{C_RED}  Size limit  : {count_size_limit}{C_RESET}")
                for sf in skipped_size_list:
                    print(f"{C_RED}    - {sf}{C_RESET}")
            if count_non_text > 0:
                print(f"{C_RED}  Non-text    : {count_non_text}{C_RESET}")
                for sf in skipped_non_text_list:
                    print(f"{C_RED}    - {sf}{C_RESET}")
            print("---------------------")

            return {
                "files": files,
                "stats": {
                    "downloaded_count": len(files),
                    "skipped_count": len(skipped_files),
                    "skipped_files": skipped_files,
                    "base_path": None,
                    "include_patterns": include_patterns,
                    "exclude_patterns": exclude_patterns,
                    "source": "ssh_clone"
                }
            }

    # Parse GitHub URL to extract owner, repo, commit/branch, and path
    parsed_url = urlparse(repo_url)
    path_parts = parsed_url.path.strip('/').split('/')

    if len(path_parts) < 2:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    # Extract the basic components
    owner = path_parts[0]
    repo = path_parts[1]

    # Setup for GitHub API
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    def fetch_branches(owner: str, repo: str):
        """Get brancshes of the repository"""

        url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        response = requests.get(url, headers=headers, timeout=(30, 30))

        if response.status_code in (403, 429) and not token:
            raise Exception("GitHub API rate limit exceeded. Please provide a GitHub token using --token or GITHUB_TOKEN env var.")

        if response.status_code == 404:
            if not token:
                print("Error 404: Repository not found or is private.\n"
                      "If this is a private repository, please provide a valid GitHub token via the 'token' argument or set the GITHUB_TOKEN environment variable.")
            else:
                print("Error 404: Repository not found or insufficient permissions with the provided token.\n"
                      "Please verify the repository exists and the token has access to this repository.")
            return []

        if response.status_code != 200:
            print(f"Error fetching the branches of {owner}/{repo}: {response.status_code} - {response.text}")
            return []

        return response.json()

    def check_tree(owner: str, repo: str, tree: str):
        """Check the repository has the given tree"""

        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree}"
        response = requests.get(url, headers=headers, timeout=(30, 30))

        if response.status_code in (403, 429) and not token:
            raise Exception("GitHub API rate limit exceeded. Please provide a GitHub token using --token or GITHUB_TOKEN env var.")

        return response.status_code == 200

    # Check if URL contains a specific branch/commit
    if len(path_parts) > 2 and path_parts[2] == 'tree':
        def join_parts(i):
            return '/'.join(path_parts[i:])

        branches = fetch_branches(owner, repo)
        branch_names = map(lambda branch: branch.get("name"), branches)

        # Fetching branches is not successfully
        if len(branches) == 0:
            return

        # To check branch name
        relevant_path = join_parts(3)

        # Find a match with relevant path and get the branch name
        filter_gen = (name for name in branch_names if relevant_path.startswith(name))
        ref = next(filter_gen, None)

        # If match is not found, check for is it a tree
        if ref is None:
            tree = path_parts[3]
            ref = tree if check_tree(owner, repo, tree) else None

        # If it is neither a tree nor a branch name
        if ref is None:
            print("The given path does not match with any branch and any tree in the repository.\n"
                  "Please verify the path is exists.")
            return

        # Combine all parts after the ref as the path
        part_index = 5 if '/' in ref else 4
        specific_path = join_parts(part_index) if part_index < len(path_parts) else ""
    else:
        # Dont put the ref param to quiery
        # and let Github decide default branch
        ref = None
        specific_path = ""

    # Dictionary to store path -> content mapping
    files = {}
    skipped_files = []

    # --- ANSI colors ---
    C_GREEN  = "\033[92m"
    C_GRAY   = "\033[90m"
    C_RED    = "\033[91m"
    C_RESET  = "\033[0m"

    # --- Counters ---
    api_counters = {"processed": 0, "excluded": 0, "size_limit": 0, "non_text": 0, "entry": 0}
    api_skipped_size = []
    api_skipped_non_text = []

    # --- Try to fetch .gitignore ---
    gitignore_spec = None
    try:
        gi_url = f"https://api.github.com/repos/{owner}/{repo}/contents/.gitignore"
        gi_params = {"ref": ref} if ref is not None else {}
        gi_resp = requests.get(gi_url, headers=headers, params=gi_params, timeout=(10, 10))
        if gi_resp.status_code == 200:
            gi_data = gi_resp.json()
            if "content" in gi_data and gi_data.get("encoding") == "base64":
                gi_content = base64.b64decode(gi_data["content"]).decode('utf-8')
                gitignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", gi_content.splitlines())
                print("Loaded .gitignore patterns from repository via API.")
    except Exception:
        pass

    def fetch_contents(path):
        """Fetch contents of the repository at a specific path and commit"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref} if ref is not None else {}

        response = requests.get(url, headers=headers, params=params, timeout=(30, 30))

        if response.status_code in (403, 429) and 'rate limit exceeded' in response.text.lower():
            if not token:
                raise Exception("GitHub API rate limit exceeded. Please provide a GitHub token using --token or GITHUB_TOKEN env var.")
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            wait_time = max(reset_time - time.time(), 0) + 1
            print(f"Rate limit exceeded. Waiting for {wait_time:.0f} seconds...")
            time.sleep(wait_time)
            return fetch_contents(path)

        if response.status_code == 404:
            if not token:
                print("Error 404: Repository not found or is private.\n"
                      "If this is a private repository, please provide a valid GitHub token via the 'token' argument or set the GITHUB_TOKEN environment variable.")
            elif not path and ref == 'main':
                print("Error 404: Repository not found. Check if the default branch is not 'main'\n"
                      "Try adding branch name to the request i.e. python main.py --repo https://github.com/username/repo/tree/master")
            else:
                print(f"Error 404: Path '{path}' not found in repository or insufficient permissions with the provided token.\n"
                      f"Please verify the token has access to this repository and the path exists.")
            return

        if response.status_code != 200:
            print(f"Error fetching {path}: {response.status_code} - {response.text}")
            return

        contents = response.json()

        # Handle both single file and directory responses
        if not isinstance(contents, list):
            contents = [contents]

        for item in contents:
            item_path = item["path"]

            # Calculate relative path if requested
            if use_relative_paths and specific_path:
                # Make sure the path is relative to the specified subdirectory
                if item_path.startswith(specific_path):
                    rel_path = item_path[len(specific_path):].lstrip('/')
                else:
                    rel_path = item_path
            else:
                rel_path = item_path

            if item["type"] == "file":
                api_counters["entry"] += 1
                entry_num = api_counters["entry"]

                # Check if file should be included based on patterns
                if not should_include_file(rel_path, item["name"], gitignore_spec=gitignore_spec):
                    api_counters["excluded"] += 1
                    print(f"{C_GRAY}  [{entry_num}] {rel_path} [excluded]{C_RESET}")
                    continue

                # Check file size if available
                file_size = item.get("size", 0)
                if file_size > max_file_size:
                    api_counters["size_limit"] += 1
                    api_skipped_size.append(rel_path)
                    size_kb = file_size / 1024
                    print(f"{C_RED}  [{entry_num}] {rel_path} [size limit: {size_kb:.0f}KB]{C_RESET}")
                    continue

                # For files, get raw content
                if item.get("download_url"):
                    file_url = item["download_url"]
                    file_response = requests.get(file_url, headers=headers, timeout=(30, 30))

                    # Final size check in case content-length header is available but differs from metadata
                    content_length = int(file_response.headers.get('content-length', 0))
                    if content_length > max_file_size:
                        api_counters["size_limit"] += 1
                        api_skipped_size.append(rel_path)
                        size_kb = content_length / 1024
                        print(f"{C_RED}  [{entry_num}] {rel_path} [size limit: {size_kb:.0f}KB]{C_RESET}")
                        continue

                    if file_response.status_code == 200:
                        files[rel_path] = file_response.text
                        api_counters["processed"] += 1
                        print(f"{C_GREEN}  [{entry_num}] {rel_path} [processed]{C_RESET}")
                    else:
                        api_counters["non_text"] += 1
                        api_skipped_non_text.append(rel_path)
                        print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: HTTP {file_response.status_code}]{C_RESET}")
                else:
                    # Alternative method if download_url is not available
                    content_response = requests.get(item["url"], headers=headers, timeout=(30, 30))
                    if content_response.status_code == 200:
                        content_data = content_response.json()
                        if content_data.get("encoding") == "base64" and "content" in content_data:
                            # Check size of base64 content before decoding
                            if len(content_data["content"]) * 0.75 > max_file_size:  # Approximate size calculation
                                estimated_size = int(len(content_data["content"]) * 0.75)
                                api_counters["size_limit"] += 1
                                api_skipped_size.append(rel_path)
                                size_kb = estimated_size / 1024
                                print(f"{C_RED}  [{entry_num}] {rel_path} [size limit: {size_kb:.0f}KB]{C_RESET}")
                                continue

                            file_content = base64.b64decode(content_data["content"]).decode('utf-8')
                            files[rel_path] = file_content
                            api_counters["processed"] += 1
                            print(f"{C_GREEN}  [{entry_num}] {rel_path} [processed]{C_RESET}")
                        else:
                            api_counters["non_text"] += 1
                            api_skipped_non_text.append(rel_path)
                            print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: unexpected format]{C_RESET}")
                    else:
                        api_counters["non_text"] += 1
                        api_skipped_non_text.append(rel_path)
                        print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: HTTP {content_response.status_code}]{C_RESET}")

            elif item["type"] == "dir":
                # Check if directory should be excluded before recursing
                dir_excluded = False
                dir_reason = None

                if gitignore_spec and gitignore_spec.match_file(rel_path):
                    dir_excluded = True
                    dir_reason = "excluded (.gitignore)"

                if not dir_excluded and exclude_patterns:
                    dir_name = item["name"]  # basename of the directory
                    for pattern in exclude_patterns:
                        dir_pattern = pattern[:-2] if pattern.endswith("/*") else pattern
                        if fnmatch.fnmatch(item_path, dir_pattern) or fnmatch.fnmatch(rel_path, dir_pattern) or fnmatch.fnmatch(dir_name, dir_pattern):
                            dir_excluded = True
                            dir_reason = "excluded"
                            break

                if dir_excluded:
                    api_counters["entry"] += 1
                    api_counters["excluded"] += 1
                    print(f"{C_GRAY}  [{api_counters['entry']}] {rel_path}/ [{dir_reason}]{C_RESET}")
                    continue

                # Only recurse if directory is not excluded
                fetch_contents(item_path)

    # Start crawling from the specified path
    fetch_contents(specific_path)

    # --- Summary ---
    total_fetched = api_counters["processed"] + api_counters["excluded"] + api_counters["size_limit"] + api_counters["non_text"]
    print("\n--- Crawl Summary ---")
    print(f"  Total found : {total_fetched}")
    print(f"{C_GREEN}  Processed   : {api_counters['processed']}{C_RESET}")
    if api_counters["excluded"] > 0:
        print(f"{C_GRAY}  Excluded    : {api_counters['excluded']}{C_RESET}")
    if api_counters["size_limit"] > 0:
        print(f"{C_RED}  Size limit  : {api_counters['size_limit']}{C_RESET}")
        for sf in api_skipped_size:
            print(f"{C_RED}    - {sf}{C_RESET}")
    if api_counters["non_text"] > 0:
        print(f"{C_RED}  Non-text    : {api_counters['non_text']}{C_RESET}")
        for sf in api_skipped_non_text:
            print(f"{C_RED}    - {sf}{C_RESET}")
    print("---------------------")

    return {
        "files": files,
        "stats": {
            "downloaded_count": len(files),
            "skipped_count": len(skipped_files),
            "skipped_files": skipped_files,
            "base_path": specific_path if use_relative_paths else None,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns
        }
    }

# Example usage
if __name__ == "__main__":
    # Get token from environment variable (recommended for private repos)
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("Warning: No GitHub token found in environment variable 'GITHUB_TOKEN'.\n"
              "Private repositories will not be accessible without a token.\n"
              "To access private repos, set the environment variable or pass the token explicitly.")

    repo_url = "https://github.com/pydantic/pydantic/tree/6c38dc93f40a47f4d1350adca9ec0d72502e223f/pydantic"

    # Example: Get Python and Markdown files, but exclude test files
    result = crawl_github_files(
        repo_url,
        token=github_token,
        max_file_size=1 * 1024 * 1024,  # 1 MB in bytes
        use_relative_paths=True,  # Enable relative paths
        include_patterns={"*.py", "*.md"},  # Include Python and Markdown files
    )

    files = result["files"]
    stats = result["stats"]

    print(f"\nDownloaded {stats['downloaded_count']} files.")
    print(f"Skipped {stats['skipped_count']} files due to size limits or patterns.")
    print(f"Base path for relative paths: {stats['base_path']}")
    print(f"Include patterns: {stats['include_patterns']}")
    print(f"Exclude patterns: {stats['exclude_patterns']}")

    # Display all file paths in the dictionary
    print("\nFiles in dictionary:")
    for file_path in sorted(files.keys()):
        print(f"  {file_path}")

    # Example: accessing content of a specific file
    if files:
        sample_file = next(iter(files))
        print(f"\nSample file: {sample_file}")
        print(f"Content preview: {files[sample_file][:200]}...")
