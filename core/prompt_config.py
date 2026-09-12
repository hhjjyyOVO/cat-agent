from __future__ import annotations

import os
from pathlib import Path


PROMPT_SECTIONS = {
    "chat": "CHAT_SYSTEM",
    "feeding": "FEEDING_SYSTEM",
    "vision": "VISION_SYSTEM",
}


def default_prompt_path() -> Path:
    env_path = os.getenv("AI_SYSTEM_PROMPTS_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / "data" / "system_prompts.txt"


def load_system_prompts(path: str | Path | None = None) -> dict[str, str]:
    prompt_path = Path(path) if path else default_prompt_path()
    if not prompt_path.exists():
        return {}

    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in prompt_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().upper()
            sections.setdefault(current_section, [])
            continue
        if current_section is None:
            continue
        if line.startswith("#"):
            continue
        sections[current_section].append(raw_line.rstrip())

    return {
        key: "\n".join(lines).strip()
        for key, section_name in PROMPT_SECTIONS.items()
        if (lines := sections.get(section_name))
    }


def get_system_prompt(name: str, path: str | Path | None = None) -> str:
    return load_system_prompts(path).get(name.strip().lower(), "")
