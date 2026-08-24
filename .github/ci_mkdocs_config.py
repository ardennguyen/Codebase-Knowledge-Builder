"""CI helper: create base mkdocs.yml and Mermaid init JS for GitHub Pages deployment.

Called by .github/workflows/deploy-docs.yml to generate the MkDocs config
and JS files in the output directory. Uses plain file writes to avoid
shell heredoc / quoting issues in GitHub Actions.
"""

import pathlib

OUTPUT_DIR = pathlib.Path("output/Codebase-Knowledge-Builder")

# ── mkdocs.yml ──────────────────────────────────────────────────────
MKDOCS_YML = """\
site_name: Codebase Knowledge Builder API Reference
site_url: https://ardennguyen.github.io/Codebase-Knowledge-Builder/
theme:
  name: material
  features:
    - content.code.copy
    - navigation.indexes
  palette:
    - scheme: default
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
plugins:
  - search
  - panzoom:
      include_selectors:
        - ".mermaid-raw"
markdown_extensions:
  - pymdownx.highlight:
      anchor_linenums: true
      use_pygments: true
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid-raw
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.inlinehilite
extra_javascript:
  - https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js
  - javascripts/mermaid-init.js
nav:
  - Home: index.md
  - Architecture & Design: design.md
"""

# ── mermaid-init.js ─────────────────────────────────────────────────
MERMAID_INIT_JS = """\
// Initialize Mermaid on .mermaid-raw elements (bypasses Material theme override)
// Material for MkDocs targets .mermaid class for its own color overrides.
// By using .mermaid-raw, diagrams render with Mermaid's default theme:
// yellow subgraph backgrounds, lavender nodes, clean rectangles.
document.addEventListener('DOMContentLoaded', function() {
  if (typeof mermaid !== 'undefined') {
    mermaid.initialize({ startOnLoad: false, theme: 'default' });
    mermaid.run({ querySelector: '.mermaid-raw' });
  }
});
"""

if __name__ == "__main__":
    # Write mkdocs.yml
    mkdocs_path = OUTPUT_DIR / "mkdocs.yml"
    mkdocs_path.write_text(MKDOCS_YML, encoding="utf-8")
    print(f"  Created {mkdocs_path}")

    # Write mermaid-init.js
    js_dir = OUTPUT_DIR / "docs" / "javascripts"
    js_dir.mkdir(parents=True, exist_ok=True)
    js_path = js_dir / "mermaid-init.js"
    js_path.write_text(MERMAID_INIT_JS, encoding="utf-8")
    print(f"  Created {js_path}")
