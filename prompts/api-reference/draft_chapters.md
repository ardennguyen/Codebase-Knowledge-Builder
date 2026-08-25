{language_instruction}Write a complete formal API and internal engineering documentation reference page (in Markdown format) for the source file `{abstraction_name}` in the project `{project_name}`.
This is a 1:1 file-to-page mapping — each page documents exactly ONE source code file exhaustively.

File Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Full Project Directory Structure:
{directory_tree}

Complete API Index{structure_note}:
{full_chapter_listing}

Your documentation page location: {current_doc_path}

Context from previous pages{prev_summary_note}:
{previous_chapters_summary}

Source Code Context:
{file_context_str}

Instructions for the API reference page (Generate content in {language} unless specified otherwise):

PAGE SKELETON (MANDATORY): Every page MUST follow this exact section ordering. Translate section headings to {language}. You may SKIP a section if the file has no relevant content for it, but you MUST NOT invent new `##` headings or rename these. ALL other content belongs inside these sections as `###`/`####` sub-sections or prose paragraphs.

```
# {abstraction_name}
> **Source:** `path/to/file`

## Technical Overview          ← always first, 1-3 paragraphs + mermaid diagram
## Public API                  ← exported/public classes and functions
## Internal Helpers            ← private/internal functions, nested helpers
## Data Structures             ← types, schemas, return structures, config objects
## Error Handling              ← notable error patterns, custom exceptions
## See Also                    ← always last
```

Section grouping criteria — apply to ANY programming language or file type:
- **Public API**: Symbols that are part of the file's external contract — imported by other files, exported, or callable by external consumers. Determine visibility using the language's own conventions (access modifiers, naming conventions, export mechanisms, header declarations, etc.).
- **Internal Helpers**: Symbols used only within this file — private methods, nested functions, utility closures, file-scoped helpers. If the language has no explicit visibility system, use context: is it called only within this file? Then it's internal.
- **Data Structures**: ALL types, classes, structs, interfaces, enums, schemas, AND complex return value shapes (e.g., a function returning a dict/object with multiple fields — document its structure here). Include field-by-field tables for each. For non-typed languages (HTML, CSS, config files), document the structural contracts instead (e.g., expected attributes, class naming conventions, selector patterns).

SECTION HEADING RULES:
- The `##` headings above are the ONLY allowed `##` headings. Do NOT invent `##` headings like "Standalone Execution Block", "Pipeline Context and Data Flow", "Performance Characteristics", "Architectural Traversal Logic", or "Key Architectural Capabilities" — fold that content into Technical Overview or the relevant function's explanation.
- `###` and `####` headings are free-form (for individual functions, classes, phases).

Now the detailed rules:

- Start with `# {abstraction_name}`.
- Below the heading, state the source file path: `> **Source:** \`path/to/file.ext\``
- The `## Technical Overview` section: 1-3 paragraphs on purpose, behavior, and system role. Include a mermaid diagram if the file has control flows, pipelines, or architectural patterns.

- If this is not the first page in the API Index, begin with a brief transition noting how this file relates to the previous one. Reference the previous page with a proper Markdown link using its name{link_lang_note}.

- This is an EXHAUSTIVE internal reference. Extract ALL classes, methods, functions, AND important class properties/fields defined in this file.
- CRITICAL: You MUST include all private methods, protected methods (e.g., methods starting with `_` or `__`), and internal helper functions present in the Source Code Context above. Do not skip any classes or functions — document EVERYTHING in this file.

FUNCTION DOCUMENTATION DEPTH — scale proportionally to complexity:
  Every function/method gets its own `###` entry. Determine depth by analyzing the function's logical structure — NOT by counting lines:
  * **Simple** (single responsibility, linear flow): One code block + one explanation paragraph under `###`.
  * **Multi-phase** (distinct logical phases — e.g., validation → core logic → cleanup → result formatting): Split into `####` sub-sections, one per logical phase. Each phase gets its own code block + explanation paragraph.
  * **Very large** (many distinct phases, nested loops, multiple branching paths): Start with a brief phase overview listing all phases, then a `####` sub-section for each. There is NO cap — if a function has 12 logical phases, create 12 `####` sub-sections.
  The `####` phase names must describe the actual phase — NOT generic labels like "Implementation Walkthrough: Part 1" or "Section A". Use descriptive names derived from what the code does (e.g., "Tree Traversal", "Filter Chain", "Response Assembly", "Cache Invalidation").
  CONSISTENCY: Functions of similar complexity across different files in the same project MUST get similar documentation depth. Do not over-document a trivial helper or under-document a complex orchestrator.

- Generate standard Markdown API documentation enforcing this exact structure for each method/function:

### `function_or_method_name()`
**Visibility**: (Public, Protected, or Private)
**Signature**: `def _function_name(arg1: type) -> type:` (or equivalent in the source language)

**Description**: Technical description of the behavior and internal implementation details. What does this actually do under the hood?

**Parameters**:
* `arg1` (type): Description of the argument.

**Returns**:
* `type`: Description of the return value.

**Raises**:
* `ExceptionType`: When/why it is raised internally.

**Example**:
```python
# Show ACTUAL usage from the source code — extract a real call site, test case,
# or the method's own implementation. NEVER invent example code.
```

- IMPORTANT: You MUST reference ACTUAL code from the provided Source Code Context — never invent examples. However, DO NOT dump the entire source file into one massive code block. Instead, extract method-by-method.

- NO INVENTED CODE: Every code block, usage example, and snippet MUST come from the actual Source Code Context provided above. If no usage example exists in the source for a method, show the method's own implementation as the example. Never fabricate hypothetical calling code.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear — in their original language, with original variable names, and original inline comments. Never translate, rephrase, or modify code or inline comments. Your own explanations belong in prose paragraphs outside the code fence.

- CODE BLOCK SIZE: For each documented method/function, show its signature and the core implementation logic in a code block of 10-50 lines. Use `// ...` (or the language's comment syntax) to skip boilerplate, repetitive branches, or trivial setup within the method body. NEVER exceed 50 lines in one code block. Follow each code block with a prose paragraph explaining the implementation behavior.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of technical explanation immediately after it — describe the behavior, implementation strategy, error handling, and edge cases. Do NOT just show code with a one-liner description.

- DATA STRUCTURES (MANDATORY): In the `## Data Structures` section, document ALL types, classes used as data containers, return value schemas, and configuration objects defined or returned by this file. For each structure, include:
  * A field-by-field table: `| Field | Type | Description |`
  * Example values where visible in the source code
  * If a function returns a complex dict/list/object (not a simple scalar), document its shape here even if there is no formal type definition.
  Skip this section ONLY if every function in the file returns simple scalars (strings, numbers, booleans) or None/void.

- DIAGRAM RULES (ABSOLUTE — applies to ALL visual diagrams in the document):
  NEVER use ASCII art, box-drawing characters (+---+, |, v, -->), or plaintext diagrams anywhere — not in the overview section, not in architecture diagrams, not anywhere. Every diagram MUST use fenced ```mermaid code blocks. If you are tempted to draw a text-art box diagram, STOP and write a ```mermaid flowchart TD instead.
  Include Mermaid diagrams for: control flows, inheritance hierarchies, state machines, node/pipeline architectures, and architectural overviews. Choose the appropriate type:
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `sequenceDiagram` — for request/response flows that cross multiple components
  * `flowchart TD` — for decision logic, branching, pipeline stages, node architecture, or architectural overviews (MUST use TD direction)
  * `stateDiagram` — for entity lifecycle states
  Include diagrams when they add clarity; omit them for simple data-class or utility files.
  MERMAID RENDERING RULES: All flowcharts MUST use `flowchart TD` (top-down). Never use LR, RL, or BT. All process nodes MUST use rectangular brackets with quoted labels: `nodeId["Label"]`. Never use rounded `("Label")`, stadium `(["Label"])`, hexagon, or other shapes. Decision nodes MAY use diamond shape: `nodeId{{"Decision?"}}`. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead. For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, define `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` ONCE at the end of the diagram, then apply `class nodeId entryNode` to the first node of the overall flow AND the first node inside each subgraph. Leave ALL other nodes with default Mermaid styling — do NOT add custom colors, fills, or styles to non-entry nodes. Do NOT use `%%{init}%%` directives — the site handles theming automatically.

- Link to other documented files using Markdown links with relative paths. Each file's doc path is shown in the Index above as `(doc: path.md)`. Compute the relative path from your location ({current_doc_path}) to the target{link_lang_note}. Translate the surrounding prose text, not the code.

- PAGE LENGTH: Aim for 3,000-8,000 words per reference page. This limit includes prose AND code — use per-method extraction (not whole-file dumps) to stay within it. Only if the file defines more than 20 classes or 60+ methods should you fall back to a summary table for the least significant items:
  | Class/Function | Visibility | Responsibility | Key Methods |

- End the page with the `## See Also` section listing related files with Markdown links{link_lang_note}, based on imports or call relationships visible in the source code.

- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the API reference Markdown output: