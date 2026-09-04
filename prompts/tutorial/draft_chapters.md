{language_instruction}Write a very beginner-friendly tutorial chapter (in Markdown format) for the project `{project_name}` about the concept: "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Full Project Directory Structure:
{directory_tree}

Complete Tutorial Structure{structure_note}:
{full_chapter_listing}

Your documentation page location: {current_doc_path}

Context from previous chapters{prev_summary_note}:
{previous_chapters_summary}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str}

Instructions for the chapter (Generate content in {language} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided concept name.

PAGE SKELETON (MANDATORY): Every chapter MUST follow this section ordering. You may SKIP a section if the concept has no relevant content for it, but you MUST NOT invent new `##` headings or rename these. ALL other content belongs inside these sections as `###`/`####` sub-sections or prose paragraphs.
HEADING TRANSLATION RULE: The `##` headings below are shown in English for reference only. You MUST translate ALL `##` headings to {language}. Output ONLY the translated heading — do NOT append the English original in parentheses (e.g., write `## Tổng quan Kỹ thuật`, NOT `## Tổng quan Kỹ thuật (Technical Overview)`). This rule also applies to `###` and `####` sub-headings you create.

```
## Motivation & Use Case       ← always first: what problem does this solve?
## Key Concepts                ← break down the abstraction into learnable pieces
## How It Works                ← usage examples, inputs/outputs
## Under the Hood              ← internal implementation walkthrough + mermaid diagrams
## Summary                     ← what was learned, transition to next chapter
```

SECTION HEADING RULES:
- The `##` headings above are the ONLY allowed `##` headings. Do NOT invent `##` headings like "Pipeline Context", "Performance Characteristics", "Architectural Overview", or "Key Capabilities" — fold that content into the appropriate section above.
- `###` and `####` headings are free-form (for individual features, code walkthrough phases).

FUNCTION DOCUMENTATION DEPTH — scale proportionally to complexity:
  Determine depth by analyzing the function's logical structure — NOT by counting lines:
  * **Simple** (single responsibility, linear flow): One code block + one explanation paragraph.
  * **Multi-phase** (distinct logical phases): Split into `####` sub-sections, one per logical phase. Each phase gets its own code block + explanation paragraph.
  * **Very large** (many distinct phases): Start with a brief phase overview, then a `####` sub-section for each. There is NO cap on sub-sections.
  The `####` phase names must describe the actual phase — NOT generic labels like "Implementation Walkthrough: Part 1".
  CONSISTENCY: If two chapters cover functions of similar complexity, they MUST get similar documentation depth.

- If this is not the first chapter, begin with a brief transition from the previous chapter{instruction_lang_note}, referencing it with a proper Markdown link using its name{link_lang_note}.

- Begin with a high-level motivation explaining what problem this abstraction solves{instruction_lang_note}. Start with a central use case as a concrete example. The whole chapter should guide the reader to understand how to solve this use case. Make it very minimal and friendly to beginners.

- If the abstraction is complex, break it down into key concepts. Explain each concept one-by-one in a very beginner-friendly way{instruction_lang_note}.

- Explain how to use this abstraction to solve the use case{instruction_lang_note}. Give example inputs and outputs for code snippets (if the output isn't values, describe at a high level what will happen{instruction_lang_note}).

- FUNCTION-BY-FUNCTION BREAKDOWN: Do NOT give a high-level overview and then dump the source code. Instead, identify each major feature, handler, or workflow in this component and give each its own `###` subsection. For each one:
  1. Explain what it does and when it is triggered
  2. Walk through the internal steps it performs in a numbered list or prose paragraph
  3. Show the key 10-20 lines of actual code that implement it (use `// ...` to skip boilerplate)
  4. Explain the code immediately after the block — what each significant line does and why
  If a single class implements multiple distinct operations, each operation MUST get its own subsection — do not lump them together.
  WITHIN SUBSECTIONS: If a method or handler is longer than 20 lines, do NOT show it as one block. Instead, split it into 2-4 logical segments (e.g., validation → core logic → cleanup). Show each segment as a separate code block (10-20 lines) with its own explanation paragraph between blocks. The reader should understand EACH segment before moving to the next.

- IMPORTANT: You MUST extract and include the ACTUAL code snippets from the provided file context. Do not write generic examples or cut code short; present the exact implementation.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear{code_comment_note}. Never translate, rephrase, or modify code or inline comments. Your own explanations belong in prose paragraphs outside the code fence.

- CODE BLOCK SIZE: Keep each code block to 10-20 lines. The absolute maximum for any single code block is 30 lines — only when showing a tightly coupled struct/class definition that cannot be meaningfully split. Use `// ...` to skip boilerplate. NEVER exceed 30 lines in one code block.

- EXPLANATION RATIO: For every code block, you MUST write at least one full paragraph (3-5 sentences minimum) of explanation immediately after it. The overall chapter should be at least 60% prose and at most 40% code by line count. If you find yourself showing code block after code block with only a single sentence between them, STOP and add more explanation — describe what the code achieves, why it's designed this way, what edge cases it handles, and how it connects to the next block.

- Describe the internal implementation to help understand what's under the hood{instruction_lang_note}. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called{instruction_lang_note}. You MUST generate Mermaid diagrams using fenced code blocks (```mermaid) to visualize this. DIAGRAM RULES (ABSOLUTE): NEVER use ASCII art, box-drawing characters (+---+, |, v, -->), or plaintext diagrams anywhere in the document — not in the overview, not in architecture diagrams, not anywhere. Every diagram MUST use fenced ```mermaid code blocks. Choose the Mermaid diagram type based on what aspect of the code you're illustrating:
  * `sequenceDiagram` — for request/response flows that cross multiple components or services
  * `flowchart TD` — for decision logic, branching, or pipeline stages within a single component (MUST use TD direction)
  * `erDiagram` — for data model relationships (database schemas, entity hierarchies)
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `stateDiagram` — for entity lifecycle states (e.g., pending → confirmed → settled)
  Include at least 2 different diagram types per chapter when the component warrants it.
  Keep the diagrams minimal and clean to ensure clarity. {mermaid_lang_note}.
  MERMAID RENDERING RULES: All flowcharts MUST use `flowchart TD` (top-down). Never use LR, RL, or BT. All process nodes MUST use rectangular brackets with quoted labels: `nodeId["Label"]`. Never use rounded `("Label")`, stadium `(["Label"])`, hexagon, or other shapes. Decision nodes MAY use diamond shape: `nodeId{{"Decision?"}}`. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead (standard accented letters/diacritics are fully supported inside quotes). For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, define `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` ONCE at the end of the diagram, then apply `class nodeId entryNode` to the first node of the overall flow AND the first node inside each subgraph. Leave ALL other nodes with default Mermaid styling — do NOT add custom colors, fills, or styles to non-entry nodes. Do NOT use `%%{{init}}%%` directives — the site handles theming automatically.
  MERMAID LANGUAGE RULES: All diagram text — node labels, decision diamond texts, edge labels, and subgraph titles — MUST be written in the same language as the rest of the document{mermaid_lang_note}. Node identifiers (IDs) MUST remain ASCII alphanumeric (e.g. `startNode`, `stepInit`), but the displayed label inside quotes MUST use the target language with proper diacritics.

- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but make them similarly simple and beginner-friendly. Explain{instruction_lang_note}.

- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links with relative paths. Each chapter's doc path is shown in the Structure above as `(doc: path.md)`. The link target filename MUST be copied EXACTLY and VERBATIM from the `(doc: ...)` annotation — NEVER re-derive, re-slugify, or guess filenames. Compute the relative path from your location ({current_doc_path}) to the target{link_lang_note}.

- Heavily use analogies and examples throughout{instruction_lang_note} to help beginners understand.

- CHAPTER LENGTH: Aim for 3,000-6,000 words per chapter. This limit includes prose AND code. If the component spans many files, focus on the 3-5 most representative files and briefly reference the rest by name and role. Pick ONE primary use-case scenario and trace it end-to-end rather than exhaustively documenting every method.

- End the chapter with a brief conclusion that summarizes what was learned{instruction_lang_note} and provides a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.

- Ensure the tone is welcoming and easy for a newcomer to understand{tone_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):
