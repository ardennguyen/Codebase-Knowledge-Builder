{language_instruction}Write a complete formal SDK documentation reference page (in Markdown format) for the module `{abstraction_name}` in the project `{project_name}`.

Module Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete SDK Index{structure_note}:
{full_chapter_listing}

Context from previous modules{prev_summary_note}:
{previous_chapters_summary}

Source Code Context:
{file_context_str}

Instructions for the SDK reference page (Generate content in {language} unless specified otherwise):
- Start with a clear heading `# {abstraction_name}`.
- Provide a technical overview of this module's behavior and what capability it provides to SDK consumers.

- If this is not the first module in the SDK Index, begin with a brief transition noting how this module relates to the previous one. Reference the previous module with a proper Markdown link using its name{link_lang_note}.

- Extract the primary public-facing APIs, classes, and methods relevant for an SDK consumer. Focus on what a developer needs to integrate this module. You DO NOT need to document internal helper methods or private functions unless they are crucial for understanding the architecture.

- FUNCTION-BY-FUNCTION BREAKDOWN (CRITICAL): Do NOT dump the entire source code and call it documentation. Instead, go method-by-method:
  1. Give each public method/function its own `###` subsection using the template below
  2. For each method, show its signature and a focused code excerpt (10-50 lines, using `// ...` to skip boilerplate)
  3. Follow each code block with a prose paragraph explaining what the SDK consumer needs to know
  If the module exposes multiple distinct features or operations, each MUST get its own documented subsection — do not lump them together.

- Generate standard Markdown API documentation enforcing this exact structure for each public method/function:

### `function_or_method_name()`
**Signature**: `def function_name(arg1: type) -> type:` (or equivalent in the source language)

**Description**: What does this function do for the developer? Focus on usage, not internal implementation.

**Parameters**:
* `arg1` (type): Description of the argument.

**Returns**:
* `type`: Description of the return value.

**Example**:
```python
# Show a REAL-WORLD usage example derived from actual source code patterns.
# Extract from tests, existing call sites, or construct from the method's
# actual signature and behavior. NEVER invent hypothetical code.
```

- Document all public-facing APIs present in the Source Code Context above. Group methods under their respective class headings (`## ClassName`).

- IMPORTANT: You MUST reference ACTUAL code from the provided Source Code Context — never invent examples. However, DO NOT dump entire source files. Instead, extract the most significant public methods and classes selectively.

- NO INVENTED CODE: Every code block, usage example, and snippet MUST be derived from the actual Source Code Context provided above. Extract real call sites, test cases, or construct examples strictly from the method's actual signature and visible behavior. Never fabricate hypothetical integration code that doesn't exist in the source.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear — in their original language, with original variable names, and original inline comments. Never translate, rephrase, or modify code or inline comments. Your own explanations belong in prose paragraphs outside the code fence.

- CODE BLOCK SIZE: Keep individual code blocks to 10-50 lines each. Use `// ...` (or the language's comment syntax) to skip boilerplate, repetitive branches, or internal plumbing. NEVER exceed 50 lines in one code block. Follow each code block with a prose paragraph explaining the usage pattern and integration implications.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of explanation immediately after it — describe what the SDK consumer needs to know about behavior, return values, error handling, and integration patterns. Do NOT just show code with a one-liner description.

- When the module involves complex integration patterns, initialization flows, or state management, you MUST include Mermaid diagrams using fenced code blocks (```mermaid). NEVER use ASCII art, box-drawing characters (+---+, |, v), or plaintext diagrams — they render poorly in web documentation. Choose the appropriate Mermaid diagram type:
  * `sequenceDiagram` — for request/response flows showing how the SDK consumer interacts with the module
  * `flowchart` — for decision logic, configuration branching, or setup pipelines
  * `classDiagram` — for inheritance hierarchies or builder/factory patterns the consumer needs to understand
  * `stateDiagram` — for entity lifecycle states the consumer must track
  Include diagrams when they help a developer understand HOW to use the module; omit them for simple utility modules.
  MERMAID RENDERING RULES: Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead. For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat horizontal sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, highlight entry/start nodes (the first node of the overall flow AND the first node inside each subgraph) by adding `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` and applying it with `class nodeId entryNode`. Leave all other nodes with default Mermaid styling — do NOT color every node.

- Link to other modules using proper Markdown links: [OtherModule](filename.md){link_lang_note}. Use the Complete SDK Index above to find the correct filename. Translate the surrounding prose text, not the code.

- PAGE LENGTH: Aim for 3,000-6,000 words per SDK reference page. This limit includes prose AND code — use selective extraction (not whole-file dumps) to stay within it. Only if the module exposes more than 20 public classes should you fall back to a summary table for the least important items:
  | Class/Function | Responsibility | Key Methods |
  Even then, fully document as many as possible and use the table only for trivial accessors or simple data containers.

- End the page with a brief "See Also" section listing related modules with Markdown links{link_lang_note}.

- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the SDK reference Markdown output: