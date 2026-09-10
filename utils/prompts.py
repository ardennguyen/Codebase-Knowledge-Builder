"""
Reusable prompt and response helpers.

Contains:
- Prompt template loaders (load_prompt_template)
- LLM response parsers (parse_yaml_response)
- Inline prompt builders for nodes that don't load from prompts/{mode}/ templates
"""

import os

import yaml


def load_prompt_template(template_name, advanced_mode=False, mode=None):
    """Load a prompt template file from the prompts/ directory."""
    if mode is None:
        prompt_dir = "advanced" if advanced_mode else "tutorial"
    else:
        prompt_dir = mode

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", prompt_dir, f"{template_name}.md")
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()
    from utils.output import emit_raw

    emit_raw("DEBUG", f"load_prompt_template | loaded '{template_name}.md' from prompts/{prompt_dir}/", dest="LOG")
    return content


def parse_yaml_response(response):
    """Extract and parse YAML from an LLM response fenced in ```yaml blocks."""
    try:
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        return yaml.safe_load(yaml_str)
    except Exception as e:
        raise ValueError(f"Failed to parse YAML: {e}") from e


def build_code_file_filter_prompt(project_name: str, file_listing: str) -> str:
    """Build the prompt for DeterministicFileMapper to filter non-code files.

    Used in api-reference mode to identify which files are actual code modules
    (APIs, functions, classes, business logic) vs. UI layouts, configs, assets.
    """
    return (
        f"For the project `{project_name}`, here is the list of all files in the codebase:\n\n"
        f"{file_listing}\n\n"
        f"Your task is to identify WHICH of these files are ACTUAL CODE files that contain "
        f"APIs, functions, classes, or core business logic.\n"
        f"EXCLUDE: UI layouts (like .xaml, .storyboard, .html), configuration files "
        f"(like .xml, .json, .manifest, .ini), static assets, build scripts "
        f"(like .csproj, .sln), and documentation.\n\n"
        f"Return ONLY a YAML list of the file indices that should be documented as code modules.\n\n"
        f"```yaml\n- 0\n- 1\n- 3\n```"
    )


def build_chapter_summary_prompt(chapter_num: int, abstraction_name: str, chapter_content: str, language: str = "english") -> str:
    """Build the prompt for generating a technical summary of a written chapter.

    Used after each chapter is generated to create a concise technical summary
    for cross-chapter context. The summary is fed into subsequent chapters'
    prompts so the LLM maintains coherence across the full document.

    The summary captures 4 technical dimensions with 3-5 sentences each:
    1. Component scope & responsibility
    2. Key classes/services/functions and their roles
    3. Implementation patterns & architectural decisions
    4. Inter-component interfaces & dependencies
    """
    lang_instruction = f"Write the entire summary in {language.capitalize()}. " if language.lower() != "english" else ""
    return (
        f"{lang_instruction}"
        f"Summarize the following documentation chapter as a structured technical brief. "
        f"For EACH of the 4 points below, write 3-5 concise technical sentences:\n\n"
        f"(1) **Component Scope & Responsibility**: What is the main technical domain this "
        f"chapter covers? What problems does it solve and what role does it play in the system?\n\n"
        f"(2) **Key Technical Elements**: What are the specific classes, services, functions, "
        f"data models, or protocols discussed? Name them and describe their concrete roles.\n\n"
        f"(3) **Implementation Patterns & Architecture**: What design patterns, communication "
        f"protocols, data flow strategies, error handling mechanisms, or security measures "
        f"are covered? How are they implemented?\n\n"
        f"(4) **System Integration & Dependencies**: How does this component interface with "
        f"other parts of the system? What does it consume from or provide to other components? "
        f"What are the key integration points?\n\n"
        f"---\n"
        f"Chapter {chapter_num}: {abstraction_name}\n"
        f"{chapter_content}"
    )
