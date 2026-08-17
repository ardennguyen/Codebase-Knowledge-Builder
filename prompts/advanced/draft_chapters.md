{language_instruction}Write a comprehensive Architecture & API Reference section (in Markdown format) for the project `{project_name}` focusing on: "{abstraction_name}". This is Section {chapter_num}.

Component Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Reference Structure{structure_note}:
{full_chapter_listing}

Context from previous sections{prev_summary_note}:
{previous_chapters_summary}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str}

Instructions for the section (Generate content in {language} unless specified otherwise):
- Start with a clear heading (e.g., `# Section {chapter_num}: {abstraction_name}`). Use the provided component name.

- If this is not the first section, begin with a brief transition from the previous section{instruction_lang_note}, referencing it with a proper Markdown link using its name{link_lang_note}.

- Begin with a technical overview explaining the architectural role of this component, design patterns utilized, and its primary responsibilities{instruction_lang_note}. 

- Dive into the API and implementation details. Explain the core classes, interfaces, and methods{instruction_lang_note}. Assume the reader is an advanced software engineer.

- Provide representative code blocks illustrating how to interface with or extend this component{instruction_lang_note}. Code blocks can be as detailed as necessary, but omit boilerplate. Include inline comments focusing on non-obvious complexities, edge cases, or performance considerations{code_comment_note}.

- Describe the internal execution flow or state transitions{instruction_lang_note}. It's highly recommended to generate a Mermaid diagram to visualize this. Choose the most appropriate Mermaid diagram type based on the specific code context (e.g., use `flowchart` for logical routing, `stateDiagram` for state machines, `sequenceDiagram` for distributed interactions, `erDiagram` for data schemas, or `classDiagram` for inheritance and composition). Keep the diagram technically precise. {mermaid_lang_note}.

- Explicitly call out any important dependencies, constraints, concurrency models, or scaling characteristics{instruction_lang_note}.

- IMPORTANT: When referencing other core components covered in other sections, ALWAYS use proper Markdown links like this: [Section Title](filename.md). Use the Complete Reference Structure above to find the correct filename and the section title{link_lang_note}. Translate the surrounding text.

- Use standard, professional software engineering terminology throughout{instruction_lang_note}.

- End the section with a brief technical summary of what was covered{instruction_lang_note} and a transition to the next section{instruction_lang_note}. If there is a next section, use a proper Markdown link: [Next Section Title](next_chapter_filename){link_lang_note}.

- Output *only* the Markdown content for this section.

Now, directly provide the advanced technical Markdown output (DON'T need ```markdown``` tags):
