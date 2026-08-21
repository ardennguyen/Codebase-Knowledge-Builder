{language_instruction}Write a complete formal API and internal engineering documentation reference page (in Markdown format) for the module `{abstraction_name}` in the project `{project_name}`.

Module Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete API Index{structure_note}:
{full_chapter_listing}

Context from previous modules{prev_summary_note}:
{previous_chapters_summary}

Source Code Context:
{file_context_str}

Instructions for the API reference page (Generate content in {language} unless specified otherwise):
- Start with a clear heading `# {abstraction_name}`.
- Below the heading, explicitly state the original file path this module represents.
- Provide a technical overview of this file's purpose and behavior in the system.

- Extract ALL public and internal classes, methods, functions, AND important class properties/fields.
- CRITICAL: You MUST include all private methods, protected methods (e.g., methods starting with `_` or `__`), and internal helper functions present in the Source Code Context above. Do not skip any classes or functions.

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
# Minimal usage example
```

- Document EVERYTHING present in the Source Code Context above. Group methods and properties under their respective class headings (`## ClassName`).
- Include the ACTUAL code snippets when helpful, but focus primarily on documenting the signatures and contracts.
- Link to other modules using proper Markdown links: [OtherModule](filename.md){link_lang_note}.
- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the API reference Markdown output: