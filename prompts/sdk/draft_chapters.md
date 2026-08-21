{language_instruction}Write a complete formal API and SDK documentation reference page (in Markdown format) for the module `{abstraction_name}` in the project `{project_name}`.

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

- Provide a technical overview of this module's behavior.

- Extract the primary public-facing APIs, classes, and methods relevant for an SDK consumer. You DO NOT need to document internal helper methods or private functions (unless they are crucial for understanding the architecture).

- Generate standard Markdown API documentation enforcing this exact structure for each:

### `function_or_method_name()`
**Signature**: `def _function_name(arg1: type) -> type:` (or equivalent in the source language)

**Description**: What does this function do for the user?

**Parameters**:
* `arg1` (type): Description of the argument.

**Returns**:
* `type`: Description of the return value.

**Example**:
```python
# Minimal usage example
```

- Document all public-facing APIs present in the Source Code Context above. Group methods under their respective class headings (`## ClassName`).
- Include the ACTUAL code snippets when helpful, but focus primarily on documenting the signatures and contracts.
- Link to other modules using proper Markdown links: [OtherModule](filename.md){link_lang_note}.
- Return ONLY valid Markdown content. Do not include conversational filler.

Now, directly provide the SDK reference Markdown output: