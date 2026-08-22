{language_instruction}Write a comprehensive Architecture Deep-Dive chapter (in Markdown format) for the project `{project_name}` focusing on: "{abstraction_name}". This is Chapter {chapter_num}.
The reader is a senior engineer or technical PM who has just joined this project and needs to build a solid technical baseline quickly.

Component Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Document Structure{structure_note}:
{full_chapter_listing}

Context from previous chapters{prev_summary_note}:
{previous_chapters_summary}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str}

Instructions for the chapter (Generate content in {language} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided component name.

- If this is not the first chapter, begin with a brief transition from the previous chapter{instruction_lang_note}, referencing it with a proper Markdown link using its name{link_lang_note}.

- Begin with a technical overview structured as follows{instruction_lang_note}:
  1. **Architectural Role**: What this component does and WHY it exists as a separate concern. What would happen if it didn't exist?
  2. **Design Patterns**: Which patterns are used and what tradeoffs they represent (not just naming the pattern — explain WHY this pattern was chosen over alternatives).
  3. **Core Responsibilities**: A bullet list of 3-7 key things this component is accountable for.
  4. **Key Dependencies**: Which other components does this one rely on? Draw an ASCII or Mermaid diagram showing this component in context with its immediate neighbors.

- Dive into the implementation. The reader is experienced — don't explain basic programming concepts. Instead focus on{instruction_lang_note}:
  * How the key classes are structured and WHY they're structured that way
  * The critical code paths — what happens on the "happy path" vs error/edge cases
  * Non-obvious design decisions visible in the code (naming conventions, error handling strategy, caching policy, etc.)
  * Concurrency model, thread safety considerations, and any shared mutable state

- FUNCTION-BY-FUNCTION BREAKDOWN (CRITICAL): Do NOT write a brief architectural overview and then dump the source code. Instead, identify EVERY major feature, option, handler, or workflow in this component and give each its own `###` subsection. For each feature/handler:
  1. State what it does and when it is triggered (button click, event, API call, etc.)
  2. Trace the control flow step-by-step through the key internal methods it calls
  3. Show ONLY the 20-50 most significant lines of code for that feature (extracted selectively with `// ...` for boilerplate)
  4. Explain the logic, edge cases, and error handling AFTER the code block
  If a single class file implements 8 distinct operations (e.g., Option 1 through Option 8), each operation MUST get its own subsection with its own code analysis — do not lump them together.
  WITHIN SUBSECTIONS: If a method is longer than 50 lines, split it into 2-3 logical segments (e.g., setup/validation → core logic → result handling). Show each segment as a separate code block (20-40 lines) with its own analysis paragraph between blocks.

- IMPORTANT: You MUST extract and include ACTUAL code snippets from the provided file context — never invent examples. However, DO NOT dump entire source files. Instead, selectively extract the most architecturally significant methods, classes, or code sections.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear{code_comment_note}. Your explanatory notes go in prose paragraphs OUTSIDE the code fence, not as modified inline comments.

- CODE BLOCK SIZE: Keep individual code blocks to 20-50 lines each. The absolute maximum is 60 lines — only for tightly coupled struct definitions, P/Invoke declarations, or similar indivisible blocks. Use `// ...` (or the language's comment syntax) to skip boilerplate, repetitive branches, or trivial accessors. NEVER exceed 60 lines in one code block.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of analysis immediately after it — explain WHY the code is structured that way, what design decisions are visible, what edge cases it handles, and what an engineer should pay attention to. The overall chapter should be at least 55% prose and at most 45% code by line count.

- SELECTIVE CODE EXTRACTION: For each file in this component, extract ONLY:
  * The class/struct declaration and its most critical 3-5 methods (the ones that carry the core logic)
  * Any non-obvious initialization, configuration, or state management code
  * Error handling or edge-case logic that reveals architectural decisions
  Do NOT paste entire files. If a file has 50 methods, show the 5 most important ones and describe the rest in a brief summary table:
  | Method/Property | Responsibility | Key Behavior |

- Describe the internal execution flow or state transitions{instruction_lang_note}. You MUST generate Mermaid diagrams using fenced code blocks (```mermaid). NEVER use ASCII art, box-drawing characters (+---+, |, v), or plaintext diagrams — they render poorly in web documentation. Choose the diagram type based on what aspect of the code you're illustrating:
  * `sequenceDiagram` — for request/response flows that cross multiple components or services
  * `flowchart` — for decision logic, branching, or pipeline stages within a single component
  * `erDiagram` — for data model relationships (database schemas, entity hierarchies)
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `stateDiagram` — for entity lifecycle states (e.g., pending → confirmed → settled)
  Use AT LEAST 2 different diagram types per chapter when appropriate.
  Keep the diagrams technically precise. {mermaid_lang_note}.
  MERMAID RENDERING RULES: Every mermaid code block MUST start with `%%{{init: {{'theme': 'default'}}}}%%` on the first line before any diagram type declaration. Keep node labels SHORT (max 40 characters) — abbreviate long names. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead (e.g., "and" not "&"). For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat horizontal sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, highlight entry/start nodes by adding `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` and applying it with `class nodeId entryNode`. Leave all other nodes with default Mermaid styling — do NOT color every node.

- Explicitly call out any important dependencies, constraints, concurrency models, or scaling characteristics{instruction_lang_note}.

- IMPORTANT: When referencing other components covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Document Structure above to find the correct filename{link_lang_note}. Translate the surrounding text.

- Add a "Practical Notes for New Team Members" subsection near the end covering{instruction_lang_note}:
  * Where to find the relevant configuration (config files, environment variables, feature flags)
  * Common debugging entry points (which logs to check, which methods to breakpoint)
  * Known quirks or technical debt visible in the code
  * How this component typically surfaces in code reviews (what changes are common)

- CHAPTER LENGTH: Aim for 5,000-10,000 words per chapter. This limit includes prose AND code — use selective extraction to stay within it. For components with many files (>15), show extracted code for the 3-5 most architecturally significant files. For the rest, provide a summary table:
  | File | Key Class/Type | Responsibility | Key Methods/Fields |
  rather than full code listings.

- End the chapter with a brief technical summary of what was covered{instruction_lang_note} and a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide the architecture deep-dive Markdown output (DON'T need ```markdown``` tags):
