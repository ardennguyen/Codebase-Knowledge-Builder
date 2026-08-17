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

- IMPORTANT: You MUST extract and include the ACTUAL code snippets from the provided file context. Do not write generic examples or cut code short; present the exact implementation.

- Each code block should be BELOW 10 lines! If longer code blocks are needed, break them down into smaller pieces and walk through them one-by-one. Aggresively simplify the code to make it minimal. Use comments{code_comment_note} to skip non-important implementation details. Each code block should have a beginner friendly explanation right after it{instruction_lang_note}.

- Describe the internal implementation to help understand what's under the hood{instruction_lang_note}. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called{instruction_lang_note}. It's highly recommended to generate a Mermaid diagram to visualize this. Choose the most appropriate Mermaid diagram type based on the specific code context (e.g., use `flowchart` for logic flows, `stateDiagram` for state machines, `sequenceDiagram` for interactions, `erDiagram` for data models, or `classDiagram` for object structures). Keep the diagram minimal and clean to ensure clarity. {mermaid_lang_note}.

- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but make them similarly simple and beginner-friendly. Explain{instruction_lang_note}.

- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Tutorial Structure above to find the correct filename and the chapter title{link_lang_note}. Translate the surrounding text.

- Use mermaid diagrams to illustrate complex concepts (```mermaid``` format). {mermaid_lang_note}.

- Heavily use analogies and examples throughout{instruction_lang_note} to help beginners understand.

- End the chapter with a brief conclusion that summarizes what was learned{instruction_lang_note} and provides a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.

- Ensure the tone is welcoming and easy for a newcomer to understand{tone_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):
