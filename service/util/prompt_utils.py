import os


def load_prompt_with_values(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as fh:
        content = fh.read()
    if '{{VALUES}}' not in content:
        return content
    values_path = os.path.join(os.path.dirname(path), 'values.md')
    try:
        with open(values_path, 'r', encoding='utf-8') as fh:
            values_text = fh.read().strip()
    except FileNotFoundError:
        return content
    return content.replace('{{VALUES}}', values_text)
