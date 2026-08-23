"""CI helper: create base mkdocs.yml and vibrant Mermaid CSS for GitHub Pages deployment.

Called by .github/workflows/deploy-docs.yml to generate the MkDocs config
and CSS files in the output directory. Uses plain file writes to avoid
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
        - ".mermaid"
markdown_extensions:
  - pymdownx.highlight:
      anchor_linenums: true
      use_pygments: true
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.inlinehilite
extra_css:
  - stylesheets/mermaid-vibrant.css
nav:
  - Home: index.md
  - Architecture & Design: design.md
"""

# ── mermaid-vibrant.css ─────────────────────────────────────────────
MERMAID_CSS = """\
/* Vibrant Mermaid diagram theme — overrides Material's muted colors */
.mermaid .cluster rect {
  fill: #ffffde !important;
  stroke: #aaaa33 !important;
  stroke-width: 1px !important;
}
.mermaid .cluster text {
  fill: #333 !important;
}
.mermaid .node rect,
.mermaid .node polygon,
.mermaid .node circle {
  fill: #ECECFF !important;
  stroke: #9370DB !important;
  stroke-width: 1px !important;
}
.mermaid .nodeLabel {
  color: #333 !important;
}
.mermaid .edgeLabel {
  background-color: #e8e8e8 !important;
  color: #333 !important;
}
.mermaid .edge-pattern-solid {
  stroke: #333 !important;
}
"""

if __name__ == "__main__":
    # Write mkdocs.yml
    mkdocs_path = OUTPUT_DIR / "mkdocs.yml"
    mkdocs_path.write_text(MKDOCS_YML, encoding="utf-8")
    print(f"  Created {mkdocs_path}")

    # Write mermaid-vibrant.css
    css_dir = OUTPUT_DIR / "docs" / "stylesheets"
    css_dir.mkdir(parents=True, exist_ok=True)
    css_path = css_dir / "mermaid-vibrant.css"
    css_path.write_text(MERMAID_CSS, encoding="utf-8")
    print(f"  Created {css_path}")
