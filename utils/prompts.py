"""
Reusable prompt and response helpers.

Contains:
- Prompt template loaders (load_prompt_template)
- LLM response parsers (parse_yaml_response, parse_grouping_response, parse_facts_response)
- Inline prompt builders for nodes that don't load from prompts/{mode}/ templates
"""

import os
import re

import yaml


def parse_file_index(idx_value):
    """Extract the first integer from an LLM-returned file index value.

    Handles multiple formats the LLM may produce:
    - Plain int: 3
    - Annotated string: "3 # path/to/file.py"
    - Range notation: "0-3" → returns first number only (caller handles ranges)

    Returns:
        int or None if no digits found.
    """
    nums = re.findall(r"\d+", str(idx_value))
    return int(nums[0]) if nums else None


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
    # A reply cut off at max tokens (llm_common.TruncatedResponse) can still contain a parseable
    # fenced prefix that silently drops items — raise so the node retries instead.
    if getattr(response, "truncated", False):
        raise ValueError("LLM response was truncated before the YAML block completed")
    try:
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        return yaml.safe_load(yaml_str)
    except Exception as e:
        raise ValueError(f"Failed to parse YAML: {e}") from e


def parse_grouping_response(response):
    """Parse the group_modules.md reply (sections + descriptions + dependencies).

    When the whole block is not valid YAML, each top-level block (``sections:``, ``descriptions:``,
    ``dependencies:``) is parsed on its own and the ones that parse are kept, so one malformed
    description costs neither the grouped sidebar nor the dependencies. A section ``role`` written in
    backticks (invalid YAML) is unwrapped first. Raises when ``sections`` cannot be recovered, and for
    truncated replies.
    """
    try:
        return parse_yaml_response(response)
    except ValueError:
        if getattr(response, "truncated", False) or "```yaml" not in response:
            raise
        yaml_str = response.split("```yaml", 1)[1].split("```", 1)[0]
        yaml_str = re.sub(r"(?m)^(\s*(?:-\s+)?role\s*:\s*)`([^`\n]*)`", r"\1\2", yaml_str)
        parsed = {}
        for chunk in re.split(r"(?m)^(?=(?:sections|descriptions|dependencies)\s*:)", yaml_str):
            try:
                part = yaml.safe_load(chunk)
            except Exception:
                continue
            if isinstance(part, dict):
                parsed.update(part)
        if not isinstance(parsed.get("sections"), list):
            raise ValueError("Failed to parse YAML: no sections list in the grouping reply") from None
        return parsed


FACTS_KEYS = ("symbols", "dependencies", "config", "errors")
# Opening fence in any case, possibly indented (under a bullet); the closing fence must sit at the same
# indentation: quoted source lines inside the |- blocks are always indented deeper and may contain ```
# themselves (Markdown in strings or docstrings), which would otherwise end the block early
_FACTS_BLOCK_RE = re.compile(r"(?msi)^([ \t]*)```ya?ml[^\n]*\n(.*?)^\1```[ \t]*$")
_FACTS_OPEN_RE = re.compile(r"(?msi)^([ \t]*)```ya?ml[^\n]*\n(.*)")
# A quote written as a plain scalar (`signature: def run(self):`), the most common reply mistake: its colon
# or `#` breaks the YAML. Rewritten as a |- block scalar before the lenient re-parse.
_PLAIN_QUOTE_RE = re.compile(r"(?m)^([ \t]*(?:- )?)(signature|evidence):[ \t]+(?![|>\"'])(\S.*)$")


def _load_strings(text: str):
    """YAML with every scalar kept as the reply's text: ``404``, ``on``, ``3.10`` stay strings."""
    return yaml.load(text, Loader=yaml.BaseLoader)  # BaseLoader builds only str / list / dict: safe


def _block_quotes(text: str) -> str:
    return _PLAIN_QUOTE_RE.sub(lambda m: f"{m[1]}{m[2]}: |-\n{' ' * (len(m[1]) + 2)}{m[3]}", text)


def parse_facts_response(response) -> dict:
    """Parse the extract_facts.md reply → ``{"symbols": [...], "dependencies": [...], "config": [...], "errors": [...], "unparsed": n}``.

    Scalars stay strings (``yaml.BaseLoader``). When the block is not valid YAML, quotes written as plain
    scalars are rewritten as block scalars and the block re-parsed; failing that, each list is parsed on
    its own, and inside a broken list each item, so one malformed quote costs one fact. ``unparsed``
    counts the items that were still lost (and list items that are not mappings), so they count as
    claimed-but-unverified. A missing or null list becomes ``[]``. Raises for truncated replies and when
    none of the four lists is present.
    """
    if getattr(response, "truncated", False):
        raise ValueError("LLM response was truncated before the YAML block completed")
    match = _FACTS_BLOCK_RE.search(response) or _FACTS_OPEN_RE.search(response)
    if not match:
        raise ValueError("Failed to parse YAML: no ```yaml block in the facts reply")
    indent = match.group(1)
    yaml_str = "\n".join(line.removeprefix(indent) for line in match.group(2).split("\n"))
    unparsed = 0
    try:
        data = _load_strings(yaml_str)
    except Exception:
        try:
            data = _load_strings(_block_quotes(yaml_str))
        except Exception:
            data, unparsed = _salvage_yaml_lists(_block_quotes(yaml_str), FACTS_KEYS)
    if not isinstance(data, dict) or not any(key in data for key in FACTS_KEYS):
        raise ValueError("Failed to parse YAML: no fact lists in the facts reply")
    result = {}
    for key in FACTS_KEYS:
        items = data.get(key)
        items = items if isinstance(items, list) else []
        result[key] = [item for item in items if isinstance(item, dict)]
        unparsed += len(items) - len(result[key])
    result["unparsed"] = unparsed
    return result


def _salvage_yaml_lists(yaml_str: str, keys: tuple) -> tuple[dict, int]:
    """Parse each top-level ``key:`` list of a broken YAML block on its own; a list that still fails is
    parsed item by item (split at its own ``- `` indentation) and keeps the items that parse.
    Returns ``(lists, number of items lost)``."""
    names = "|".join(keys)
    parsed, lost = {}, 0
    for chunk in re.split(rf"(?m)^(?=(?:{names})\s*:)", yaml_str):
        head = re.match(rf"({names})\s*:", chunk)
        if not head:
            continue
        try:
            part = _load_strings(chunk)
        except Exception:
            part = None
        if isinstance(part, dict):
            parsed.update(part)
            continue
        body = chunk[head.end() :]
        first = re.search(r"(?m)^([ \t]*)- ", body)
        if not first:
            continue
        indent = first.group(1)
        items = []
        for piece in re.split(rf"(?m)^(?={re.escape(indent)}- )", body):
            if not piece.startswith(f"{indent}- "):
                continue
            text = "\n".join(line.removeprefix(indent) for line in piece.split("\n"))
            try:
                item = _load_strings(text)
            except Exception:
                lost += 1
                continue
            if isinstance(item, list) and item and isinstance(item[0], dict):
                items.append(item[0])
            else:
                lost += 1
        parsed[head.group(1)] = items
    return parsed, lost


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
