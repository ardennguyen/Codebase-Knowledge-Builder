"""Internationalization (i18n) — auto-translation of missing UI strings.

Extracted from output.py to break the circular dependency chain
output.py → call_llm.py → token_utils.py → output.py.
The output module now delegates translation to this module, which is the
only place that imports call_llm from the output subsystem.
"""

import csv
import json
import os
import re


def auto_translate(lang_col, language, csv_path, use_cache, thinking_level):
    """Auto-translate missing strings via LLM and write back into strings.csv.

    Args:
        lang_col: Lowercase language column name in CSV (e.g., "vietnamese").
        language: Capitalized language display name (e.g., "Vietnamese").
        csv_path: Absolute path to strings.csv.
        use_cache: Whether LLM caching is enabled.
        thinking_level: LLM thinking level for translation calls.

    Returns:
        True if translations were written (caller should reload strings), False otherwise.
    """
    from utils.output import emit_raw

    if lang_col == "english":
        return False

    if not csv_path or not os.path.exists(csv_path):
        return False

    # Collect strings that have no translation in the target language column
    missing = {}
    is_new_column = False
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        is_new_column = lang_col not in fieldnames
        for row in reader:
            key = row.get("STRING_KEY", "").strip()
            if not key or key.startswith("#"):
                continue
            # Check if the language column exists and has a value
            lang_text = row.get(lang_col, "").strip() if lang_col in fieldnames else ""
            if lang_text:
                continue  # Already translated

            english_text = row.get("english", "").strip()
            if english_text:
                missing[key] = english_text

    if not missing:
        return False

    # Report what we found
    if is_new_column:
        emit_raw("PROGRESS", f"[i18n] New language '{language}' — adding column to strings.csv")
    emit_raw("PROGRESS", f"[i18n] {len(missing)} strings need translation to {language}")

    # Batch translate via LLM
    try:
        from utils.call_llm import call_llm

        entries_json = json.dumps(missing, ensure_ascii=False, indent=2)

        # Load prompt template from prompts/common/translate_strings.md
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "prompts",
            "common",
            "translate_strings.md",
        )
        with open(prompt_path, encoding="utf-8") as pf:
            prompt_template = pf.read()
        prompt = prompt_template.format(language=language, entries=entries_json)

        emit_raw("PROGRESS", f"[i18n] Calling LLM to translate {len(missing)} strings...")
        response = call_llm(prompt, use_cache=use_cache, thinking_level=thinking_level)

        # Extract JSON from response
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response, re.DOTALL)
        if json_match:
            translations = json.loads(json_match.group())
            translated_count = len(translations)

            # Write translations back into strings.csv
            _write_translations_to_csv(csv_path, lang_col, fieldnames, translations)
            emit_raw("SUCCESS", f"[i18n] Translated {translated_count}/{len(missing)} strings — saved to strings.csv")
            return True
        emit_raw("WARNING", "[i18n] LLM response did not contain valid JSON — falling back to English")

    except Exception as e:
        emit_raw("WARNING", f"[i18n] Translation failed: {e} — falling back to English")

    return False


def _write_translations_to_csv(csv_path, lang_col, fieldnames, translations):
    """Write LLM translations back into strings.csv, persisting them for future runs.

    If the target language column doesn't exist, it is added to the CSV.
    """
    rows = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        # Add language column if it doesn't exist
        if lang_col not in fieldnames:
            fieldnames.append(lang_col)
        for row in reader:
            key = row.get("STRING_KEY", "").strip()
            if key in translations:
                row[lang_col] = translations[key]
            rows.append(row)

    # Write with BOM so Excel opens as UTF-8 without extra import steps
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
