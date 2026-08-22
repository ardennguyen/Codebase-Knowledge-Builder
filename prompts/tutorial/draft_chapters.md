{language_instruction}Write a very beginner-friendly tutorial chapter (in Markdown format) for the project `{project_name}` about the concept: "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Tutorial Structure{structure_note}:
{full_chapter_listing}

Context from previous chapters{prev_summary_note}:
{previous_chapters_summary}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str}

Instructions for the chapter (Generate content in {language} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided concept name.

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

- Describe the internal implementation to help understand what's under the hood{instruction_lang_note}. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called{instruction_lang_note}. You MUST generate Mermaid diagrams using fenced code blocks (```mermaid) to visualize this. NEVER use ASCII art, box-drawing characters (+---+, |, v), or plaintext diagrams — they render poorly in web documentation. Choose the Mermaid diagram type based on what aspect of the code you're illustrating:
  * `sequenceDiagram` — for request/response flows that cross multiple components or services
  * `flowchart` — for decision logic, branching, or pipeline stages within a single component
  * `erDiagram` — for data model relationships (database schemas, entity hierarchies)
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `stateDiagram` — for entity lifecycle states (e.g., pending → confirmed → settled)
  Include at least 2 different diagram types per chapter when the component warrants it.
  Keep the diagrams minimal and clean to ensure clarity. {mermaid_lang_note}.
  MERMAID RENDERING RULES: Every mermaid code block MUST start with `%%{{init: {{'theme': 'default'}}}}%%` on the first line before any diagram type declaration. Keep node labels SHORT (max 40 characters) — abbreviate long names. Do not embed newlines inside node label quotes. Avoid special characters (`&`, `<`, `>`) in labels — use words instead. For diagrams with 6+ nodes, use `subgraph` blocks to group related nodes and prevent flat horizontal sprawl.
  MERMAID STYLING RULES: For flowchart diagrams, highlight entry/start nodes by adding `classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5;` and applying it with `class nodeId entryNode`. Leave all other nodes with default Mermaid styling — do NOT color every node.

- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but make them similarly simple and beginner-friendly. Explain{instruction_lang_note}.

- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Tutorial Structure above to find the correct filename and the chapter title{link_lang_note}. Translate the surrounding text.

- Heavily use analogies and examples throughout{instruction_lang_note} to help beginners understand.

- CHAPTER LENGTH: Aim for 3,000-6,000 words per chapter. This limit includes prose AND code. If the component spans many files, focus on the 3-5 most representative files and briefly reference the rest by name and role. Pick ONE primary use-case scenario and trace it end-to-end rather than exhaustively documenting every method.

- End the chapter with a brief conclusion that summarizes what was learned{instruction_lang_note} and provides a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.

- Ensure the tone is welcoming and easy for a newcomer to understand{tone_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):
