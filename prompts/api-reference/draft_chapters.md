{language_instruction}Write a complete formal API and internal engineering documentation reference page (in Markdown format) for the source file `{abstraction_name}` in the project `{project_name}`.
This is a 1:1 file-to-page mapping — each page documents exactly ONE source code file exhaustively.

File Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete API Index{structure_note}:
{full_chapter_listing}

Context from previous pages{prev_summary_note}:
{previous_chapters_summary}

Source Code Context:
{file_context_str}

Instructions for the API reference page (Generate content in {language} unless specified otherwise):
- Start with a clear heading `# {abstraction_name}`.
- Below the heading, explicitly state the original file path this page documents.
- Provide a technical overview of this file's purpose, behavior, and role in the system.

- If this is not the first page in the API Index, begin with a brief transition noting how this file relates to the previous one. Reference the previous page with a proper Markdown link using its name{link_lang_note}.

- This is an EXHAUSTIVE internal reference. Extract ALL classes, methods, functions, AND important class properties/fields defined in this file.
- CRITICAL: You MUST include all private methods, protected methods (e.g., methods starting with `_` or `__`), and internal helper functions present in the Source Code Context above. Do not skip any classes or functions — document EVERYTHING in this file.

- FUNCTION-BY-FUNCTION BREAKDOWN (CRITICAL): Do NOT dump the entire source file and call it documentation. Instead, go method-by-method:
  1. Give each public method/function its own `###` subsection using the template below
  2. For each method, show its signature and the core implementation logic (10-50 lines, using `// ...` to skip boilerplate)
  3. Follow each code block with a prose paragraph explaining the behavior, edge cases, and error handling
  If the file implements multiple distinct features or handlers (e.g., 8 button click handlers), each MUST get its own documented subsection — do not lump them into one giant code block.

- Generate standard Markdown API documentation enforcing this exact structure for each method/function:

### `function_or_method_name()`
**Visibility**: (Specify Public, Protected, or Private)
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

- Group methods and properties under their respective class headings (`## ClassName`). For top-level functions not inside a class, group them under `## Module-Level Functions`.

- IMPORTANT: You MUST reference ACTUAL code from the provided Source Code Context — never invent examples. However, DO NOT dump the entire source file into one massive code block. Instead, extract method-by-method.

- NO INVENTED CODE: Every code block, usage example, and snippet MUST come from the actual Source Code Context provided above. If no usage example exists in the source for a method, show the method's own implementation as the example. Never fabricate hypothetical calling code.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear — in their original language, with original variable names, and original inline comments. Never translate, rephrase, or modify code or inline comments. Your own explanations belong in prose paragraphs outside the code fence.

- CODE BLOCK SIZE: For each documented method/function, show its signature and the core implementation logic in a code block of 10-50 lines. Use `// ...` (or the language's comment syntax) to skip boilerplate, repetitive branches, or trivial setup within the method body. NEVER exceed 50 lines in one code block. Follow each code block with a prose paragraph explaining the implementation behavior.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of technical explanation immediately after it — describe the behavior, implementation strategy, error handling, and edge cases. Do NOT just show code with a one-liner description.

- When the file defines control flows, inheritance hierarchies, state machines, or node/pipeline architectures, you MUST include Mermaid diagrams using fenced code blocks (```mermaid). NEVER use ASCII art, box-drawing characters (+---+, |, v), or plaintext diagrams — they render poorly in web documentation. Choose the appropriate Mermaid diagram type:
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `sequenceDiagram` — for request/response flows that cross multiple components
  * `flowchart` — for decision logic, branching, pipeline stages, or node architecture
  * `stateDiagram` — for entity lifecycle states
  Include diagrams when they add clarity; omit them for simple data-class or utility files.
  MERMAID RENDERING RULES: Every mermaid code block MUST start with `%%{init: {'theme': 'default'}}%%` on the first line before any diagram type declaration. Keep node labels SHORT (max 40 characters) — abbreviate long names. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead. For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat horizontal sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, highlight entry/start nodes by adding `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` and applying it with `class nodeId entryNode`. Leave all other nodes with default Mermaid styling — do NOT color every node.

- Link to other documented files using proper Markdown links: [OtherFile](filename.md){link_lang_note}. Use the Complete API Index above to find the correct filename. Translate the surrounding prose text, not the code.

- PAGE LENGTH: Aim for 3,000-8,000 words per reference page. This limit includes prose AND code — use per-method extraction (not whole-file dumps) to stay within it. Only if the file defines more than 20 classes or 60+ methods should you fall back to a summary table for the least significant items:
  | Class/Function | Visibility | Responsibility | Key Methods |
  Even then, fully document as many as possible and use the table only for trivial accessors or boilerplate wrappers.

- End the page with a brief "See Also" section listing related files with Markdown links{link_lang_note}, based on imports or call relationships visible in the source code.

- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the API reference Markdown output: