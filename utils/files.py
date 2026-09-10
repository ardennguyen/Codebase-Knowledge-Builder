"""File and content helpers used by multiple nodes."""

import os
from collections import defaultdict


def build_directory_tree(files_data):
    """Build a compact directory tree string from the list of (path, content) tuples.

    Groups files by directory and formats as a hierarchical tree with file indices.
    Used by ContextRouter, IdentifyAbstractions, MapAbstractions, and CombineTutorial
    to give LLMs structural context about the project layout.
    """
    dir_files = defaultdict(list)
    for i, (path, _content) in enumerate(files_data):
        dirname = os.path.dirname(path) or "."
        basename = os.path.basename(path)
        dir_files[dirname].append(f"{basename} (idx:{i})")

    lines = []
    for dirname in sorted(dir_files.keys()):
        lines.append(f"{dirname}/")
        lines.extend(f"  {fname}" for fname in sorted(dir_files[dirname]))
    return "\n".join(lines)


def get_content_for_indices(files_data, indices):
    """Get file content for specific indices from files_data list."""
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content  # Use index + path as key for context
    return content_map
