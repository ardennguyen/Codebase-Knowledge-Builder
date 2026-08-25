{language_instruction}Write a complete formal SDK documentation reference page (in Markdown format) for the module `{abstraction_name}` in the project `{project_name}`.

Module Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Full Project Directory Structure:
{directory_tree}

Complete SDK Index{structure_note}:
{full_chapter_listing}

Your documentation page location: {current_doc_path}

Context from previous modules{prev_summary_note}:
{previous_chapters_summary}

Source Code Context:
{file_context_str}

Instructions for the SDK reference page (Generate content in {language} unless specified otherwise):

PAGE SKELETON (MANDATORY): Every page MUST follow this exact section ordering. Translate section headings to {language}. You may SKIP a section if the module has no relevant content for it, but you MUST NOT invent new `##` headings or rename these. ALL other content belongs inside these sections as `###`/`####` sub-sections or prose paragraphs.

```
# {abstraction_name}

## Technical Overview          ← always first, 1-3 paragraphs + mermaid diagram
## Public API                  ← exported classes, functions, methods for SDK consumers
## Configuration & Options     ← only if the module has config objects, builders, options
## Data Structures             ← types, schemas, return structures, response objects
## Error Handling              ← error types, exception patterns the consumer must handle
## See Also                    ← always last
```

SECTION HEADING RULES:
- The `##` headings above are the ONLY allowed `##` headings. Do NOT invent `##` headings like "Pipeline Context", "Performance Characteristics", "Architectural Overview", or "Key Capabilities" — fold that content into Technical Overview or the relevant function's explanation.
- `###` and `####` headings are free-form (for individual functions, classes, phases).

Now the detailed rules:

- Start with a clear heading `# {abstraction_name}`.
- The `## Technical Overview`: 1-3 paragraphs on what this module does for the SDK consumer and how it fits into the overall SDK. Include a mermaid diagram if the module involves complex integration patterns.

- If this is not the first module in the SDK Index, begin with a brief transition noting how this module relates to the previous one. Reference the previous module with a proper Markdown link using its name{link_lang_note}.

- Extract the primary public-facing APIs, classes, and methods relevant for an SDK consumer. Focus on what a developer needs to integrate this module. You DO NOT need to document internal helper methods or private functions unless they are crucial for understanding the architecture.

FUNCTION DOCUMENTATION DEPTH — scale proportionally to complexity:
  Every function/method gets its own `###` entry. Determine depth by analyzing the function's logical structure — NOT by counting lines:
  * **Simple** (single responsibility, linear flow): One code block + one explanation paragraph under `###`.
  * **Multi-phase** (distinct logical phases): Split into `####` sub-sections, one per logical phase. Each phase gets its own code block + explanation paragraph.
  * **Very large** (many distinct phases, nested loops, multiple branching paths): Start with a brief phase overview listing all phases, then a `####` sub-section for each. There is NO cap — if a function has 12 logical phases, create 12 `####` sub-sections.
  The `####` phase names must describe the actual phase — NOT generic labels like "Implementation Walkthrough: Part 1". Use descriptive names derived from what the code does.
  CONSISTENCY: Functions of similar complexity across different modules in the same project MUST get similar documentation depth.

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

- Document all public-facing APIs present in the Source Code Context above. Group methods under their respective class headings (`## ClassName` — this is an exception to the skeleton: class headings replace `## Public API` when the module is class-based).

- IMPORTANT: You MUST reference ACTUAL code from the provided Source Code Context — never invent examples. However, DO NOT dump entire source files. Instead, extract the most significant public methods and classes selectively.

- NO INVENTED CODE: Every code block, usage example, and snippet MUST be derived from the actual Source Code Context provided above. Extract real call sites, test cases, or construct examples strictly from the method's actual signature and visible behavior. Never fabricate hypothetical integration code that doesn't exist in the source.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear — in their original language, with original variable names, and original inline comments. Never translate, rephrase, or modify code or inline comments. Your own explanations belong in prose paragraphs outside the code fence.

- CODE BLOCK SIZE: Keep individual code blocks to 10-50 lines each. Use `// ...` (or the language's comment syntax) to skip boilerplate, repetitive branches, or internal plumbing. NEVER exceed 50 lines in one code block. Follow each code block with a prose paragraph explaining the usage pattern and integration implications.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of explanation immediately after it — describe what the SDK consumer needs to know about behavior, return values, error handling, and integration patterns. Do NOT just show code with a one-liner description.

- DATA STRUCTURES (MANDATORY): In the `## Data Structures` section, document ALL types, classes used as data containers, return value schemas, response objects, and configuration objects defined or returned by this module. For each structure, include:
  * A field-by-field table: `| Field | Type | Description |`
  * Example values where visible in the source code
  * If a function returns a complex dict/list/object (not a simple scalar), document its shape here even if there is no formal type definition.
  Skip this section ONLY if every function in the module returns simple scalars (strings, numbers, booleans) or None/void.

- DIAGRAM RULES (ABSOLUTE — applies to ALL visual diagrams in the document):
  NEVER use ASCII art, box-drawing characters (+---+, |, v, -->), or plaintext diagrams anywhere — not in the overview section, not in architecture diagrams, not anywhere. Every diagram MUST use fenced ```mermaid code blocks. If you are tempted to draw a text-art box diagram, STOP and write a ```mermaid flowchart TD instead.
  Include Mermaid diagrams for: complex integration patterns, initialization flows, state management, and architectural overviews. Choose the appropriate type:
  * `sequenceDiagram` — for request/response flows showing how the SDK consumer interacts with the module
  * `flowchart TD` — for decision logic, configuration branching, or setup pipelines (MUST use TD direction)
  * `classDiagram` — for inheritance hierarchies or builder/factory patterns the consumer needs to understand
  * `stateDiagram` — for entity lifecycle states the consumer must track
  Include diagrams when they help a developer understand HOW to use the module; omit them for simple utility modules.
  MERMAID RENDERING RULES: All flowcharts MUST use `flowchart TD` (top-down). Never use LR, RL, or BT. All process nodes MUST use rectangular brackets with quoted labels: `nodeId["Label"]`. Never use rounded `("Label")`, stadium `(["Label"])`, hexagon, or other shapes. Decision nodes MAY use diamond shape: `nodeId{{"Decision?"}}`. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead. For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, define `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` ONCE at the end of the diagram, then apply `class nodeId entryNode` to the first node of the overall flow AND the first node inside each subgraph. Leave ALL other nodes with default Mermaid styling — do NOT add custom colors, fills, or styles to non-entry nodes. Do NOT use `%%{init}%%` directives — the site handles theming automatically.

- Link to other modules using Markdown links with relative paths. Each module's doc path is shown in the Index above as `(doc: path.md)`. Compute the relative path from your location ({current_doc_path}) to the target{link_lang_note}. Translate the surrounding prose text, not the code.

- PAGE LENGTH: Aim for 3,000-6,000 words per SDK reference page. This limit includes prose AND code — use selective extraction (not whole-file dumps) to stay within it. Only if the module exposes more than 20 public classes should you fall back to a summary table for the least important items:
  | Class/Function | Responsibility | Key Methods |
  Even then, fully document as many as possible and use the table only for trivial accessors or simple data containers.

- End the page with the `## See Also` section listing related modules with Markdown links{link_lang_note}.

- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the SDK reference Markdown output: