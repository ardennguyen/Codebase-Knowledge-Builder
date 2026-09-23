// Mermaid initialization for MkDocs Material.
//
// Material for MkDocs targets .mermaid class for its own color overrides.
// By using .mermaid-raw, diagrams render with Mermaid's default theme:
// yellow subgraph backgrounds, lavender nodes, clean rectangles.
//
// pymdownx.superfences fence_div_format emits the diagram source directly as:
//   <div class="mermaid-raw">flowchart TD ...</div>
// which is what mermaid.run() reads and what the panzoom plugin activates on (DIV/IMG only).
//
// securityLevel stays at Mermaid's default ('strict'): diagram source is LLM-generated.
//
// Mermaid's default theme draws edges in dark gray, which disappear on Material's
// dark (slate) palette, so diagrams get a light card there.
(function() {
  var style = document.createElement('style');
  style.textContent = '[data-md-color-scheme="slate"] .mermaid-raw { background-color: #fff; border-radius: .2rem; }';
  document.head.appendChild(style);

  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'default'
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
