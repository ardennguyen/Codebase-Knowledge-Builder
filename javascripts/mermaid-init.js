// Initialize Mermaid on .mermaid-raw elements (bypasses Material theme override)
// Material for MkDocs targets .mermaid class for its own color overrides.
// By using .mermaid-raw, diagrams render with Mermaid's default theme:
// yellow subgraph backgrounds, lavender nodes, clean rectangles.
//
// pymdownx.superfences fence_code_format wraps content as:
//   <pre class="mermaid-raw"><code>flowchart TD ...</code></pre>
// Mermaid expects the diagram text directly in the target element,
// so we unwrap the <code> child before calling mermaid.run().
(function() {
  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    try {
      // Unwrap: move <code> text content up to <pre> and remove <code>
      document.querySelectorAll('pre.mermaid-raw > code').forEach(function(code) {
        var pre = code.parentElement;
        pre.textContent = code.textContent;
      });
      mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose'
      });
      mermaid.run({ querySelector: '.mermaid-raw' }).catch(function(err) {
        console.warn('Mermaid render error:', err);
      });
    } catch (e) {
      console.warn('Mermaid init error:', e);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMermaid);
  } else {
    initMermaid();
  }
})();
