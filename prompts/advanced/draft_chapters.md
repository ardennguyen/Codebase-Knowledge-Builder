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

- IMPORTANT: You MUST extract and include the ACTUAL code snippets from the provided file context. Do not write generic examples or cut code short; present the exact implementation.

- CODE FIDELITY: Inside fenced code blocks, preserve ALL original source code and comments EXACTLY as they appear{code_comment_note}. Your explanatory notes go in prose paragraphs OUTSIDE the code fence, not as modified inline comments.

- Provide the actual source code for the most important files in this component{instruction_lang_note}. Code blocks can be as long as needed for complete classes. For files that are less critical, provide a summary table instead of full code.

- Describe the internal execution flow or state transitions{instruction_lang_note}. It's highly recommended to generate Mermaid diagrams. Choose the diagram type based on what aspect of the code you're illustrating:
  * `sequenceDiagram` — for request/response flows that cross multiple components or services
  * `flowchart` — for decision logic, branching, or pipeline stages within a single component
  * `erDiagram` — for data model relationships (database schemas, entity hierarchies)
  * `classDiagram` — for inheritance, composition, or factory patterns
  * `stateDiagram` — for entity lifecycle states (e.g., pending → confirmed → settled)
  Use AT LEAST 2 different diagram types per chapter when appropriate.
  Keep the diagrams technically precise. {mermaid_lang_note}.

- Explicitly call out any important dependencies, constraints, concurrency models, or scaling characteristics{instruction_lang_note}.

- IMPORTANT: When referencing other components covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Document Structure above to find the correct filename{link_lang_note}. Translate the surrounding text.

- Add a "Practical Notes for New Team Members" subsection near the end covering{instruction_lang_note}:
  * Where to find the relevant configuration (config files, environment variables, feature flags)
  * Common debugging entry points (which logs to check, which methods to breakpoint)
  * Known quirks or technical debt visible in the code
  * How this component typically surfaces in code reviews (what changes are common)

- CHAPTER LENGTH: Aim for 5,000-10,000 words per chapter. For components with many files (>15), show full code for the 3-5 most architecturally significant files. For the rest, provide a summary table:
  | File | Key Class/Type | Responsibility | Key Methods/Fields |
  rather than full code listings.

- End the chapter with a brief technical summary of what was covered{instruction_lang_note} and a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide the architecture deep-dive Markdown output (DON'T need ```markdown``` tags):
